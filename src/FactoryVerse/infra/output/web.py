"""Output handler protocol and implementations.

This module defines the OutputHandler protocol that any output
consumer (console, web UI, file logger) can implement.
"""

from typing import Protocol, Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import threading


class OutputHandler(Protocol):
    """Protocol for output handlers.

    Any class implementing this protocol can receive agent activity events.
    """

    def user_message(self, message: str) -> None:
        """Handle user message."""
        ...

    def assistant_response(self, message: str, turn_number: int) -> None:
        """Handle assistant text response."""
        ...

    def llm_thinking(self, iteration: int) -> None:
        """Handle LLM thinking indicator."""
        ...

    def tool_call_start(self, tool_name: str, iteration: int) -> None:
        """Handle tool call start."""
        ...

    def tool_call_code(self, code: str, language: str = "python") -> None:
        """Handle tool call code display."""
        ...

    def tool_result(self, result: str, is_error: bool = False) -> None:
        """Handle tool result."""
        ...

    def turn_complete(self, turn_number: int) -> None:
        """Handle turn completion."""
        ...

    def system_notification(self, notification: str) -> None:
        """Handle game notification."""
        ...

    def error(self, message: str) -> None:
        """Handle error message."""
        ...


@dataclass
class AgentEvent:
    """A single event in the agent's activity stream."""

    event_type: str  # 'user', 'assistant', 'tool_start', 'tool_code', 'tool_result', 'notification', 'turn_complete'
    timestamp: datetime
    turn_number: int
    data: Dict[str, Any]


@dataclass
class TurnData:
    """Data for a single turn, aggregating all events."""

    turn_number: int
    user_message: Optional[str] = None
    assistant_response: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    notifications: List[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class WebOutput:
    """Output handler that captures events for web UI consumption.

    Thread-safe storage of agent activity that the NiceGUI viewer can poll.
    """

    def __init__(self):
        self._events: List[AgentEvent] = []
        self._turns: Dict[int, TurnData] = {}
        self._current_turn = 0
        self._current_tool: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()

    def _add_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Add event to stream (thread-safe)."""
        with self._lock:
            event = AgentEvent(
                event_type=event_type,
                timestamp=datetime.now(),
                turn_number=self._current_turn,
                data=data,
            )
            self._events.append(event)

    def _get_or_create_turn(self, turn_number: int) -> TurnData:
        """Get or create turn data."""
        if turn_number not in self._turns:
            self._turns[turn_number] = TurnData(
                turn_number=turn_number, started_at=datetime.now()
            )
        return self._turns[turn_number]

    # OutputHandler protocol methods

    def user_message(self, message: str) -> None:
        with self._lock:
            turn = self._get_or_create_turn(self._current_turn)
            turn.user_message = message
        self._add_event("user", {"message": message})

    def assistant_response(self, message: str, turn_number: int) -> None:
        with self._lock:
            self._current_turn = turn_number
            turn = self._get_or_create_turn(turn_number)
            turn.assistant_response = message
        self._add_event("assistant", {"message": message, "turn": turn_number})

    def llm_thinking(self, iteration: int) -> None:
        self._add_event("thinking", {"iteration": iteration})

    def tool_call_start(self, tool_name: str, iteration: int) -> None:
        with self._lock:
            self._current_tool = {
                "name": tool_name,
                "iteration": iteration,
                "code": None,
                "language": None,
                "result": None,
                "is_error": False,
            }
        self._add_event("tool_start", {"tool_name": tool_name, "iteration": iteration})

    def tool_call_code(self, code: str, language: str = "python") -> None:
        with self._lock:
            if self._current_tool:
                self._current_tool["code"] = code
                self._current_tool["language"] = language
        self._add_event("tool_code", {"code": code, "language": language})

    def tool_result(self, result: str, is_error: bool = False) -> None:
        with self._lock:
            if self._current_tool:
                self._current_tool["result"] = result
                self._current_tool["is_error"] = is_error
                # Finalize and store the tool call
                turn = self._get_or_create_turn(self._current_turn)
                turn.tool_calls.append(self._current_tool.copy())
                self._current_tool = None
        self._add_event("tool_result", {"result": result, "is_error": is_error})

    def turn_complete(self, turn_number: int) -> None:
        with self._lock:
            self._current_turn = turn_number
            turn = self._get_or_create_turn(turn_number)
            turn.completed_at = datetime.now()
        self._add_event("turn_complete", {"turn": turn_number})

    def system_notification(self, notification: str) -> None:
        with self._lock:
            turn = self._get_or_create_turn(self._current_turn)
            turn.notifications.append(notification)
        self._add_event("notification", {"message": notification})

    def error(self, message: str) -> None:
        self._add_event("error", {"message": message})

    def info(self, message: str) -> None:
        self._add_event("info", {"message": message})

    def success(self, message: str) -> None:
        self._add_event("success", {"message": message})

    def max_iterations_warning(self, turn_number: int) -> None:
        self._add_event(
            "warning", {"message": f"Turn {turn_number}: Max iterations reached"}
        )

    # API for UI consumption

    def get_events(self, since_index: int = 0) -> List[AgentEvent]:
        """Get events since a given index (for incremental updates)."""
        with self._lock:
            return self._events[since_index:]

    def get_turns(self) -> Dict[int, TurnData]:
        """Get all turn data."""
        with self._lock:
            return self._turns.copy()

    def get_turn(self, turn_number: int) -> Optional[TurnData]:
        """Get data for a specific turn."""
        with self._lock:
            return self._turns.get(turn_number)

    def get_current_turn_number(self) -> int:
        """Get current turn number."""
        with self._lock:
            return self._current_turn

    def get_stats(self) -> Dict[str, Any]:
        """Get summary statistics."""
        with self._lock:
            total_tool_calls = sum(len(t.tool_calls) for t in self._turns.values())
            errors = sum(
                1
                for t in self._turns.values()
                for tc in t.tool_calls
                if tc.get("is_error")
            )
            return {
                "total_turns": len(self._turns),
                "current_turn": self._current_turn,
                "total_tool_calls": total_tool_calls,
                "errors": errors,
                "success_rate": ((total_tool_calls - errors) / total_tool_calls * 100)
                if total_tool_calls > 0
                else 100,
                "total_events": len(self._events),
            }
