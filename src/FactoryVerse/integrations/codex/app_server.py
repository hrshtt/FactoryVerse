"""Minimal reusable client for the Codex app-server JSON-RPC protocol."""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


class CodexAppServerError(RuntimeError):
    """Codex app-server failed or violated the expected protocol."""


@dataclass(frozen=True)
class CodexTurnResult:
    """The final assistant message and identifiers for one completed turn."""

    thread_id: str
    turn_id: str
    text: str


class CodexAppServer:
    """Own one local ``codex app-server`` process.

    This transport is intentionally unaware of FactoryVerse.  Callers supply
    their own developer instructions, goals, user inputs, and output schemas.
    """

    def __init__(
        self,
        *,
        executable: str = "codex",
        request_timeout_seconds: float = 30.0,
        event_log_path: Optional[Path] = None,
        stderr_path: Optional[Path] = None,
        client_name: str = "factoryverse-codex-integration",
        client_version: str = "1.0.0",
    ):
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        self.executable = executable
        self.request_timeout_seconds = request_timeout_seconds
        self.event_log_path = Path(event_log_path) if event_log_path else None
        self.stderr_path = Path(stderr_path) if stderr_path else None
        self.client_name = client_name
        self.client_version = client_version
        self.process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._pending: Dict[int, asyncio.Future[Dict[str, Any]]] = {}
        self._notifications: Dict[str, asyncio.Queue[Dict[str, Any]]] = {}
        self._reader_task: Optional[asyncio.Task[None]] = None
        self._stderr_task: Optional[asyncio.Task[None]] = None

    async def version(self) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                self.executable,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise CodexAppServerError(
                f"Codex executable was not found: {self.executable}"
            ) from exc
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15.0)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise CodexAppServerError(
                "Timed out while checking Codex CLI version"
            ) from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise CodexAppServerError(f"Codex version check failed: {detail}")
        return stdout.decode("utf-8", errors="replace").strip()

    async def start(self) -> Dict[str, Any]:
        if self.process is not None:
            raise CodexAppServerError("Codex app-server is already started")
        try:
            self.process = await asyncio.create_subprocess_exec(
                self.executable,
                "app-server",
                "--stdio",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise CodexAppServerError(
                f"Codex executable was not found: {self.executable}"
            ) from exc
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        try:
            initialized = await self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": self.client_name,
                        "version": self.client_version,
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            await self.notify("initialized", {})
        except Exception:
            await self.close()
            raise
        return initialized

    async def close(self) -> None:
        process = self.process
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
            with contextlib.suppress(Exception):
                await process.stdin.wait_closed()
        try:
            await asyncio.wait_for(process.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (self._reader_task, self._stderr_task) if task),
            return_exceptions=True,
        )
        self._fail_pending(CodexAppServerError("Codex app-server closed"))
        self.process = None

    async def start_thread(
        self,
        *,
        cwd: Path,
        developer_instructions: str,
        model: Optional[str] = None,
        sandbox: str = "workspace-write",
        approval_policy: str = "never",
    ) -> str:
        params: Dict[str, Any] = {
            "cwd": str(Path(cwd).resolve()),
            "developerInstructions": developer_instructions,
            "sandbox": sandbox,
            "approvalPolicy": approval_policy,
            "ephemeral": False,
        }
        if model:
            params["model"] = model
        response = await self.request("thread/start", params)
        return self._thread_id(response, "thread/start")

    async def resume_thread(
        self,
        thread_id: str,
        *,
        cwd: Path,
        developer_instructions: str,
        model: Optional[str] = None,
        sandbox: str = "workspace-write",
        approval_policy: str = "never",
    ) -> str:
        params: Dict[str, Any] = {
            "threadId": thread_id,
            "cwd": str(Path(cwd).resolve()),
            "developerInstructions": developer_instructions,
            "sandbox": sandbox,
            "approvalPolicy": approval_policy,
        }
        if model:
            params["model"] = model
        response = await self.request("thread/resume", params)
        resumed = self._thread_id(response, "thread/resume")
        if resumed != thread_id:
            raise CodexAppServerError(
                f"thread/resume returned unexpected thread id: {resumed!r}"
            )
        return resumed

    async def set_goal(
        self,
        thread_id: str,
        objective: str,
        *,
        status: str = "active",
        token_budget: Optional[int] = None,
    ) -> Dict[str, Any]:
        objective = objective.strip()
        if not objective:
            raise ValueError("Codex goal objective must not be empty")
        if len(objective) > 4000:
            raise ValueError("Codex goal objective exceeds 4000 characters")
        params: Dict[str, Any] = {
            "threadId": thread_id,
            "objective": objective,
            "status": status,
        }
        if token_budget is not None:
            if token_budget <= 0:
                raise ValueError("Codex goal token budget must be positive")
            params["tokenBudget"] = token_budget
        return await self.request("thread/goal/set", params)

    async def get_goal(self, thread_id: str) -> Optional[Dict[str, Any]]:
        response = await self.request("thread/goal/get", {"threadId": thread_id})
        goal = response.get("goal")
        return goal if isinstance(goal, dict) else None

    async def run_turn(
        self,
        *,
        thread_id: str,
        prompt: str,
        output_schema: Optional[Dict[str, Any]] = None,
        timeout_seconds: float,
    ) -> CodexTurnResult:
        params: Dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
        }
        if output_schema is not None:
            params["outputSchema"] = output_schema
        response = await self.request("turn/start", params)
        turn = response.get("turn") or {}
        turn_id = turn.get("id")
        if not isinstance(turn_id, str) or not turn_id:
            raise CodexAppServerError("turn/start returned no turn id")

        while True:
            completed = await self.wait_notification(
                "turn/completed", timeout=timeout_seconds
            )
            if completed.get("threadId") != thread_id:
                continue
            completed_turn = completed.get("turn") or {}
            if completed_turn.get("id") != turn_id:
                continue
            if completed_turn.get("status") != "completed":
                raise CodexAppServerError(
                    f"turn {turn_id} ended as {completed_turn.get('status')}: "
                    f"{completed_turn.get('error')}"
                )
            messages = [
                item.get("text")
                for item in completed_turn.get("items", [])
                if isinstance(item, dict)
                and item.get("type") == "agentMessage"
                and isinstance(item.get("text"), str)
            ]
            if not messages:
                raise CodexAppServerError(
                    f"turn {turn_id} produced no final agent message"
                )
            return CodexTurnResult(
                thread_id=thread_id,
                turn_id=turn_id,
                text=messages[-1],
            )

    async def request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        await self._send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        try:
            return await asyncio.wait_for(future, timeout=self.request_timeout_seconds)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise CodexAppServerError(
                f"Codex app-server request timed out: {method}"
            ) from exc

    async def notify(self, method: str, params: Dict[str, Any]) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def wait_notification(
        self, method: str, *, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        queue = self._notifications.setdefault(method, asyncio.Queue())
        if timeout is None:
            return await queue.get()
        return await asyncio.wait_for(queue.get(), timeout=timeout)

    async def _send(self, message: Dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise CodexAppServerError("Codex app-server is not running")
        self._record("client", message)
        payload = json.dumps(message, separators=(",", ":")) + "\n"
        self.process.stdin.write(payload.encode("utf-8"))
        try:
            await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise CodexAppServerError("Codex app-server stdin closed") from exc

    async def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            while line := await self.process.stdout.readline():
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise CodexAppServerError(
                        "Codex app-server emitted non-JSON stdout"
                    ) from exc
                self._record("server", message)
                self._dispatch_message(message)
        except Exception as exc:
            self._fail_pending(exc)

    async def _read_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        while chunk := await self.process.stderr.read(8192):
            if self.stderr_path is None:
                continue
            self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
            with self.stderr_path.open("ab") as handle:
                handle.write(chunk)

    def _dispatch_message(self, message: Any) -> None:
        if not isinstance(message, dict):
            self._fail_pending(
                CodexAppServerError("app-server message is not an object")
            )
            return
        if "id" in message and ("result" in message or "error" in message):
            request_id = message.get("id")
            if not isinstance(request_id, int):
                return
            future = self._pending.pop(request_id, None)
            if future is None:
                return
            if message.get("error") is not None:
                future.set_exception(
                    CodexAppServerError(
                        f"Codex app-server rejected request {request_id}: "
                        f"{message['error']}"
                    )
                )
            else:
                result = message.get("result")
                future.set_result(result if isinstance(result, dict) else {})
            return
        method = message.get("method")
        params = message.get("params")
        if isinstance(method, str):
            queue = self._notifications.setdefault(method, asyncio.Queue())
            queue.put_nowait(params if isinstance(params, dict) else {})

    def _record(self, direction: str, message: Dict[str, Any]) -> None:
        if self.event_log_path is None:
            return
        self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.event_log_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {"direction": direction, "message": message},
                    sort_keys=True,
                    default=str,
                )
                + "\n"
            )

    def _fail_pending(self, exc: BaseException) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(exc)
        self._pending.clear()

    @staticmethod
    def _thread_id(response: Dict[str, Any], operation: str) -> str:
        thread = response.get("thread") or {}
        thread_id = thread.get("id")
        if not isinstance(thread_id, str) or not thread_id:
            raise CodexAppServerError(f"{operation} returned no thread id")
        return thread_id
