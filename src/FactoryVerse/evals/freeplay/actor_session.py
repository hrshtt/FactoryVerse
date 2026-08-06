"""Transport-independent execution boundary for one embodied actor lease."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import signal
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, TYPE_CHECKING

from .models import utc_now

if TYPE_CHECKING:
    from .supervisor import FreeplaySupervisor


class ExecutionTimedOut(TimeoutError):
    """Raised inside submitted Python when its execution deadline expires."""


@contextmanager
def execution_deadline(seconds: float) -> Iterator[None]:
    """Interrupt Python executed on the Unix main thread after ``seconds``."""
    if (
        seconds <= 0
        or threading.current_thread() is not threading.main_thread()
        or not hasattr(signal, "setitimer")
    ):
        yield
        return

    def _timeout(signum, frame):
        raise ExecutionTimedOut(f"Python execution exceeded {seconds:.1f}s")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _timeout)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def _error(kind: str, message: str) -> Dict[str, str]:
    return {"kind": kind, "message": message}


def _execution_error_message(output: str) -> str:
    """Extract the useful exception headline without discarding its traceback."""
    match = re.search(r"(?:^|\n)Error:\s*([^\n]+)", output)
    if match:
        return match.group(1).strip()
    for line in output.splitlines():
        line = line.strip()
        if line:
            return line
    return "Python execution failed"


class ActorRuntimeSession:
    """Owns serialized execution for one physical actor and runtime namespace.

    This class deliberately has no campaign lifecycle operations. Provisioning,
    checkpointing, revocation, resume, and finalization remain trusted
    ``FreeplaySupervisor`` responsibilities.
    """

    ACTOR_OPERATIONS = ("status", "execute")

    def __init__(
        self,
        supervisor: "FreeplaySupervisor",
        *,
        default_timeout: float = 300.0,
        maximum_timeout: float = 1800.0,
    ):
        environment = supervisor.environment
        if environment is None or environment.tier4 is None:
            raise RuntimeError("Supervisor runtime is not ready")
        if not supervisor.session_id:
            raise RuntimeError("Supervisor has no active runtime session")

        manifest = supervisor.store.manifest()
        actor_id = environment.tier4.agent_id or manifest.get("agent_id")
        if not actor_id:
            raise RuntimeError("Runtime has no embodied actor identity")

        self.supervisor = supervisor
        self.actor_id = str(actor_id)
        self.runtime_session_id = supervisor.session_id
        self.default_timeout = default_timeout
        self.maximum_timeout = maximum_timeout
        self.execution_count = 0
        self._lock = asyncio.Lock()

    def describe(self, preflight: Dict[str, Any]) -> Dict[str, Any]:
        manifest = self.supervisor.store.manifest()
        return {
            "event": "ready",
            "protocol_version": 3,
            "campaign_id": self.supervisor.store.campaign_id,
            "actor_id": self.actor_id,
            "runtime_session_id": self.runtime_session_id,
            # Compatibility alias for protocol-v1 consumers.
            "session_id": self.runtime_session_id,
            "game_tick": preflight["game_tick"],
            "operations": list(self.ACTOR_OPERATIONS),
            "documentation": manifest["documentation"],
            "capability_profile": manifest["capability_profile"],
        }

    async def handle(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle one actor request independently of its wire transport."""
        request_id = request.get("id")
        operation = request.get("op")
        started = time.time()
        self._record("actor_request", {"request": request})

        if not isinstance(operation, str):
            response = self._failure(
                request_id,
                operation=None,
                kind="invalid_request",
                message="Missing string field: op",
            )
        elif operation not in self.ACTOR_OPERATIONS:
            response = self._failure(
                request_id,
                operation=operation,
                kind="forbidden_operation",
                message=(
                    f"Operation {operation!r} is not available to an actor runtime; "
                    "campaign lifecycle is supervisor-owned"
                ),
            )
        else:
            try:
                async with self._lock:
                    if operation == "status":
                        response = await self._status(request_id)
                    else:
                        response = await self._execute(request_id, request)
            except Exception as exc:
                response = self._failure(
                    request_id,
                    operation=operation,
                    kind="runtime_internal",
                    message=f"{type(exc).__name__}: {exc}",
                )

        response["elapsed_seconds"] = time.time() - started
        self._record("actor_response", {"response": response})
        return response

    async def _status(self, request_id: Any) -> Dict[str, Any]:
        environment = self.supervisor.environment
        if environment is None or environment.tier3 is None:
            raise RuntimeError("Runtime environment is unavailable")
        return self._identity(
            {
                "id": request_id,
                "ok": True,
                "op": "status",
                "game_tick": environment.tier3.get_game_tick(),
                "execution_count": self.execution_count,
                "game_events": await self._drain_game_events(),
            }
        )

    async def _drain_game_events(self) -> list[Dict[str, Any]]:
        """Consume pending temporal events into the actor protocol response.

        Coding harnesses already receive this response after every submitted
        Python block, so carrying events here provides capability changes at
        the same turn boundary without a second transport or an MCP server.
        """
        environment = self.supervisor.environment
        tier4 = environment.tier4 if environment is not None else None
        event_stream = tier4.events if tier4 is not None else None
        if event_stream is None:
            return []

        events = await event_stream.drain(timeout=0.05)
        return [event.to_dict() for event in events]

    async def _execute(
        self, request_id: Any, request: Dict[str, Any]
    ) -> Dict[str, Any]:
        source = request.get("source")
        legacy_code = request.get("code")
        if source is None:
            source = legacy_code
        elif legacy_code is not None and legacy_code != source:
            return self._failure(
                request_id,
                operation="execute",
                kind="invalid_request",
                message="Fields source and code disagree; provide only source",
            )
        if not isinstance(source, str) or not source.strip():
            return self._failure(
                request_id,
                operation="execute",
                kind="invalid_request",
                message="Missing non-empty string field: source",
            )

        logical_path = request.get("logical_path")
        if logical_path is not None and not isinstance(logical_path, str):
            return self._failure(
                request_id,
                operation="execute",
                kind="invalid_request",
                message="logical_path must be a string when provided",
            )

        source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
        claimed_sha256 = request.get("source_sha256")
        if claimed_sha256 is not None and claimed_sha256 != source_sha256:
            return self._failure(
                request_id,
                operation="execute",
                kind="source_hash_mismatch",
                message="source_sha256 does not match the submitted source",
                source_sha256=source_sha256,
                logical_path=logical_path,
            )

        try:
            requested_timeout = float(
                request.get("timeout_seconds", self.default_timeout)
            )
        except (TypeError, ValueError):
            return self._failure(
                request_id,
                operation="execute",
                kind="invalid_request",
                message="timeout_seconds must be numeric",
                source_sha256=source_sha256,
                logical_path=logical_path,
            )
        if not math.isfinite(requested_timeout):
            return self._failure(
                request_id,
                operation="execute",
                kind="invalid_request",
                message="timeout_seconds must be finite",
                source_sha256=source_sha256,
                logical_path=logical_path,
            )
        timeout = min(max(requested_timeout, 0.1), self.maximum_timeout)

        environment = self.supervisor.environment
        if environment is None or environment.tier3 is None or environment.tier4 is None:
            raise RuntimeError("Runtime environment is unavailable")

        tick_before = environment.tier3.get_game_tick()
        trajectory = environment.tier4.trajectory_writer
        turn = self.execution_count + 1
        if trajectory:
            trajectory.tool_start("execute_python", turn=turn, iteration=1)
            trajectory.tool_code(source, turn=turn, lang="python")

        with execution_deadline(timeout):
            output = await environment.tier4.execute_code(
                source,
                compress_output=bool(request.get("compress_output", False)),
            )
        tick_after = environment.tier3.get_game_tick()
        game_events = await self._drain_game_events()
        timed_out = "ExecutionTimedOut" in output
        success = (
            not output.startswith("Error:")
            and "\nError: " not in output
            and not timed_out
        )
        self.execution_count += 1
        if trajectory:
            trajectory.tool_result(output, turn=turn, success=success)
            trajectory.turn_complete(turn=turn)
        self.supervisor.store.update_session(
            self.runtime_session_id,
            execution_count=self.execution_count,
            last_game_tick=tick_after,
        )

        response = self._identity(
            {
                "id": request_id,
                "ok": success,
                "op": "execute",
                "output": output,
                "game_events": game_events,
                "timed_out": timed_out,
                "timeout_seconds": timeout,
                "game_tick_before": tick_before,
                "game_tick_after": tick_after,
                "execution_index": self.execution_count,
                "source_sha256": source_sha256,
                "logical_path": logical_path,
            }
        )
        if not success:
            response["error"] = _error(
                "execution_timeout" if timed_out else "execution_error",
                _execution_error_message(output),
            )
        return response

    def _failure(
        self,
        request_id: Any,
        *,
        operation: Optional[str],
        kind: str,
        message: str,
        **details: Any,
    ) -> Dict[str, Any]:
        return self._identity(
            {
                "id": request_id,
                "ok": False,
                "op": operation,
                "error": _error(kind, message),
                **details,
            }
        )

    def _identity(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            **payload,
            "campaign_id": self.supervisor.store.campaign_id,
            "actor_id": self.actor_id,
            "runtime_session_id": self.runtime_session_id,
        }

    def _record(self, direction: str, payload: Dict[str, Any]) -> None:
        self.supervisor.store.append_protocol(
            {
                "direction": direction,
                "recorded_at": utc_now(),
                "campaign_id": self.supervisor.store.campaign_id,
                "actor_id": self.actor_id,
                "runtime_session_id": self.runtime_session_id,
                **payload,
            }
        )
