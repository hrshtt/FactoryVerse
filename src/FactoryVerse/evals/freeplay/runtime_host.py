"""JSONL transport adapter for one supervisor-owned actor runtime session."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict

from .actor_session import (
    ActorRuntimeSession,
    ExecutionTimedOut,
    execution_deadline,
)
from .supervisor import FreeplaySupervisor


PROTOCOL_PREFIX = "FV_EVAL_JSON "

__all__ = [
    "ExecutionTimedOut",
    "FreeplayRuntimeHost",
    "PROTOCOL_PREFIX",
    "execution_deadline",
]


class FreeplayRuntimeHost:
    """Expose an ``ActorRuntimeSession`` over newline-delimited JSON."""

    def __init__(
        self,
        supervisor: FreeplaySupervisor,
        *,
        default_timeout: float = 300.0,
        maximum_timeout: float = 1800.0,
    ):
        self.supervisor = supervisor
        self.actor_session = ActorRuntimeSession(
            supervisor,
            default_timeout=default_timeout,
            maximum_timeout=maximum_timeout,
        )

    @property
    def execution_count(self) -> int:
        return self.actor_session.execution_count

    def ready_event(self, preflight: Dict[str, Any]) -> Dict[str, Any]:
        return self.actor_session.describe(preflight)

    async def handle(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return await self.actor_session.handle(request)

    async def serve_stdio(self, preflight: Dict[str, Any]) -> Dict[str, Any]:
        close_reason = "actor_transport_eof"
        result: Dict[str, Any]
        try:
            self._emit(self.ready_event(preflight))
            while True:
                line = await asyncio.to_thread(sys.stdin.readline)
                if line == "":
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError("request must be a JSON object")
                except Exception as exc:
                    self._emit(
                        {
                            "id": None,
                            "ok": False,
                            "error": {
                                "kind": "invalid_json",
                                "message": f"Invalid JSON request: {exc}",
                            },
                        }
                    )
                    continue

                response = await self.handle(request)
                self._emit(response)
        except Exception:
            close_reason = "actor_transport_error"
            raise
        finally:
            result = await self.supervisor.finish(
                reason=close_reason,
                checkpoint=True,
                execution_count=self.execution_count,
            )
        return result

    @staticmethod
    def _emit(payload: Dict[str, Any]) -> None:
        print(
            PROTOCOL_PREFIX + json.dumps(payload, sort_keys=True, default=str),
            flush=True,
        )
