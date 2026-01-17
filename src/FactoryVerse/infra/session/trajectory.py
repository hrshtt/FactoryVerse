"""Trajectory management for agent sessions.

This module provides file-based event streaming for agent sessions:
- TrajectoryWriter: Append events to trajectory.jsonl
- TrajectoryReader: Read/tail events, reconstruct turn state
- TrajectoryEvent: Event schema

The trajectory.jsonl file is the source of truth for session history.
Both CLI and GUI consumers read from this file.
"""

import json
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from enum import Enum


class EventType(str, Enum):
    """Event types in trajectory stream."""

    SESSION_START = "session_start"
    SESSION_END = "session_end"
    USER_MESSAGE = "user_message"
    TOOL_START = "tool_start"
    TOOL_CODE = "tool_code"
    TOOL_RESULT = "tool_result"
    ASSISTANT_RESPONSE = "assistant_response"
    TURN_COMPLETE = "turn_complete"
    NOTIFICATION = "notification"
    THINKING = "thinking"
    ERROR = "error"
    COMPLETION_STATS = "completion_stats"


@dataclass
class TrajectoryEvent:
    """A single event in the trajectory stream."""

    type: str
    ts: float
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {"type": self.type, "ts": self.ts, **self.data}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TrajectoryEvent":
        """Create from dictionary."""
        event_type = d.pop("type")
        ts = d.pop("ts")
        return cls(type=event_type, ts=ts, data=d)

    @property
    def timestamp(self) -> datetime:
        """Get timestamp as datetime."""
        return datetime.fromtimestamp(self.ts)


@dataclass
class TurnData:
    """Reconstructed data for a single turn.

    Shared structure used by both CLI and GUI consumers.
    """

    turn_number: int
    user_message: Optional[str] = None
    assistant_response: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    notifications: List[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def is_complete(self) -> bool:
        """Check if turn is complete."""
        return self.completed_at is not None


class TrajectoryWriter:
    """Append events to trajectory.jsonl (thread-safe).

    Usage:
        writer = TrajectoryWriter(session_dir / "trajectory.jsonl")
        writer.session_start(model="intellect-3", mode="assisted")
        writer.user_message("What iron patches?", turn=1)
        writer.tool_start("execute_duckdb", turn=1, iteration=1)
        writer.tool_code("SELECT ...", turn=1, lang="sql")
        writer.tool_result("...", turn=1, success=True)
        writer.assistant_response("I found...", turn=1)
        writer.turn_complete(turn=1)
        writer.session_end(total_turns=1)
    """

    def __init__(self, trajectory_path: Path):
        """Initialize trajectory writer.

        Args:
            trajectory_path: Path to trajectory.jsonl file
        """
        self.path = Path(trajectory_path)
        self._lock = threading.Lock()
        self._current_turn = 0

    def _write(self, event_type: str, **data) -> None:
        """Write event to trajectory file (thread-safe)."""
        event = {"type": event_type, "ts": time.time(), **data}
        with self._lock:
            with open(self.path, "a") as f:
                f.write(json.dumps(event) + "\n")

    # Session lifecycle events

    def session_start(self, model: str, mode: str) -> None:
        """Write session start event."""
        self._write(EventType.SESSION_START, model=model, mode=mode)

    def session_end(self, total_turns: int, status: str = "complete") -> None:
        """Write session end event."""
        self._write(EventType.SESSION_END, total_turns=total_turns, status=status)

    # Turn events

    def user_message(self, content: str, turn: int) -> None:
        """Write user message event."""
        self._current_turn = turn
        self._write(EventType.USER_MESSAGE, content=content, turn=turn)

    def assistant_response(self, content: str, turn: int) -> None:
        """Write assistant response event."""
        self._write(EventType.ASSISTANT_RESPONSE, content=content, turn=turn)

    def turn_complete(self, turn: int) -> None:
        """Write turn complete event."""
        self._write(EventType.TURN_COMPLETE, turn=turn)

    # Tool events

    def tool_start(self, tool_name: str, turn: int, iteration: int) -> None:
        """Write tool start event."""
        self._write(
            EventType.TOOL_START, tool=tool_name, turn=turn, iteration=iteration
        )

    def tool_code(self, code: str, turn: int, lang: str = "python") -> None:
        """Write tool code event."""
        self._write(EventType.TOOL_CODE, code=code, turn=turn, lang=lang)

    def tool_result(self, result: str, turn: int, success: bool = True) -> None:
        """Write tool result event."""
        self._write(EventType.TOOL_RESULT, result=result, turn=turn, success=success)

    # Other events

    def notification(
        self, message: str, turn: int, data: Optional[Dict] = None
    ) -> None:
        """Write notification event."""
        self._write(EventType.NOTIFICATION, message=message, turn=turn, data=data or {})

    def thinking(self, turn: int, iteration: int) -> None:
        """Write thinking event."""
        self._write(EventType.THINKING, turn=turn, iteration=iteration)

    def error(self, message: str, turn: Optional[int] = None) -> None:
        """Write error event."""
        self._write(EventType.ERROR, message=message, turn=turn or self._current_turn)

    def completion_stats(self, turn: int, usage: Dict[str, int]) -> None:
        """Write completion statistics event."""
        self._write(EventType.COMPLETION_STATS, turn=turn, usage=usage)


class TrajectoryReader:
    """Read events from trajectory.jsonl.

    Supports:
    - read_all(): Get all events
    - read_new(): Incremental reads for polling
    - build_turns(): Reconstruct TurnData from events

    Usage:
        reader = TrajectoryReader(session_dir / "trajectory.jsonl")

        # Full read
        events = reader.read_all()

        # Incremental (for polling)
        new_events = reader.read_new()  # Returns events since last read

        # Reconstruct turns
        turns = reader.build_turns()  # Dict[int, TurnData]
    """

    def __init__(self, trajectory_path: Path):
        """Initialize trajectory reader.

        Args:
            trajectory_path: Path to trajectory.jsonl file
        """
        self.path = Path(trajectory_path)
        self._offset = 0  # File offset for incremental reads

    def exists(self) -> bool:
        """Check if trajectory file exists."""
        return self.path.exists()

    def read_all(self) -> List[TrajectoryEvent]:
        """Read all events from trajectory.

        Returns:
            List of all events in order
        """
        if not self.exists():
            return []

        events = []
        with open(self.path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        events.append(TrajectoryEvent.from_dict(data))
                    except json.JSONDecodeError:
                        continue  # Skip malformed lines

        return events

    def read_new(self) -> List[TrajectoryEvent]:
        """Read events since last read (for polling).

        Returns:
            List of new events since last call
        """
        if not self.exists():
            return []

        events = []
        with open(self.path, "r") as f:
            f.seek(self._offset)
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        events.append(TrajectoryEvent.from_dict(data))
                    except json.JSONDecodeError:
                        continue

            self._offset = f.tell()

        return events

    def reset(self) -> None:
        """Reset read position to start of file."""
        self._offset = 0

    def build_turns(self) -> Dict[int, TurnData]:
        """Reconstruct turn data from event stream.

        Returns:
            Dict mapping turn number to TurnData
        """
        events = self.read_all()
        turns: Dict[int, TurnData] = {}
        current_tool: Optional[Dict[str, Any]] = None

        for event in events:
            turn_num = event.data.get("turn")

            if turn_num is not None:
                if turn_num not in turns:
                    turns[turn_num] = TurnData(turn_number=turn_num)
                turn = turns[turn_num]

                if event.type == EventType.USER_MESSAGE:
                    turn.user_message = event.data.get("content")
                    turn.started_at = event.timestamp

                elif event.type == EventType.TOOL_START:
                    current_tool = {
                        "name": event.data.get("tool"),
                        "iteration": event.data.get("iteration"),
                        "code": None,
                        "language": None,
                        "result": None,
                        "is_error": False,
                    }

                elif event.type == EventType.TOOL_CODE:
                    if current_tool:
                        current_tool["code"] = event.data.get("code")
                        current_tool["language"] = event.data.get("lang", "python")

                elif event.type == EventType.TOOL_RESULT:
                    if current_tool:
                        current_tool["result"] = event.data.get("result")
                        current_tool["is_error"] = not event.data.get("success", True)
                        turn.tool_calls.append(current_tool)
                        current_tool = None

                elif event.type == EventType.ASSISTANT_RESPONSE:
                    turn.assistant_response = event.data.get("content")

                elif event.type == EventType.TURN_COMPLETE:
                    turn.completed_at = event.timestamp

                elif event.type == EventType.NOTIFICATION:
                    turn.notifications.append(event.data.get("message", ""))

        return turns

    def get_session_info(self) -> Optional[Dict[str, Any]]:
        """Get session metadata from start event.

        Returns:
            Dict with model, mode, etc. or None if no start event
        """
        events = self.read_all()
        for event in events:
            if event.type == EventType.SESSION_START:
                return {
                    "model": event.data.get("model"),
                    "mode": event.data.get("mode"),
                    "started_at": event.timestamp,
                }
        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get summary statistics from trajectory.

        Returns:
            Dict with turn count, tool calls, errors, etc.
        """
        turns = self.build_turns()

        total_tool_calls = sum(len(t.tool_calls) for t in turns.values())
        errors = sum(
            1 for t in turns.values() for tc in t.tool_calls if tc.get("is_error")
        )

        return {
            "total_turns": len(turns),
            "completed_turns": sum(1 for t in turns.values() if t.is_complete),
            "total_tool_calls": total_tool_calls,
            "errors": errors,
            "success_rate": (
                ((total_tool_calls - errors) / total_tool_calls * 100)
                if total_tool_calls > 0
                else 100.0
            ),
            "token_usage": self._get_token_usage_stats(),
        }

    def _get_token_usage_stats(self) -> Dict[str, int]:
        """Aggregate token usage stats."""
        events = self.read_all()
        stats = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        for event in events:
            if event.type == EventType.COMPLETION_STATS:
                usage = event.data.get("usage", {})
                stats["prompt_tokens"] += usage.get("prompt_tokens", 0)
                stats["completion_tokens"] += usage.get("completion_tokens", 0)
                stats["total_tokens"] += usage.get("total_tokens", 0)

        return stats

    def build_message_history(self) -> List[Dict[str, Any]]:
        """Reconstruct message history from trajectory events.
        
        This reconstructs the message history in the format expected by
        AgentOrchestrator, including:
        - System prompt (from session start)
        - Initial state (if present)
        - User messages
        - Assistant responses
        - Tool calls and tool responses
        
        Returns:
            List of message dicts in the format expected by LLM clients
        """
        events = self.read_all()
        messages: List[Dict[str, Any]] = []
        
        # Track current turn state
        current_turn: Optional[int] = None
        current_tool_calls: List[Dict[str, Any]] = []
        current_tool_results: List[Dict[str, Any]] = []
        pending_assistant_response: Optional[str] = None
        tool_call_index = 0  # Track which tool call we're processing
        
        for event in events:
            if event.type == EventType.SESSION_START:
                # Note: System prompt is not stored in trajectory
                # It should be loaded from system_prompt.md file
                pass
                
            elif event.type == EventType.USER_MESSAGE:
                # Add any pending assistant response first
                if pending_assistant_response:
                    messages.append({
                        "role": "assistant",
                        "content": pending_assistant_response,
                    })
                    pending_assistant_response = None
                
                # If we have incomplete tool calls, finish them
                if current_tool_calls and current_tool_results:
                    # Add assistant message with tool calls
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": current_tool_calls,
                    })
                    # Add tool responses
                    messages.extend(current_tool_results)
                    current_tool_calls = []
                    current_tool_results = []
                    tool_call_index = 0
                
                # Add user message
                content = event.data.get("content", "")
                messages.append({
                    "role": "user",
                    "content": content,
                })
                current_turn = event.data.get("turn")
                current_tool_calls = []
                current_tool_results = []
                tool_call_index = 0
                
            elif event.type == EventType.TOOL_START:
                tool_name = event.data.get("tool")
                iteration = event.data.get("iteration", 1)
                turn = event.data.get("turn", current_turn or 0)
                call_id = f"call_{turn}_{tool_name}_{iteration}"
                
                current_tool_calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": "",  # Will be filled by TOOL_CODE
                    },
                })
                
            elif event.type == EventType.TOOL_CODE:
                code = event.data.get("code", "")
                lang = event.data.get("lang", "python")
                
                # Find the most recent tool call without arguments and add them
                if current_tool_calls:
                    # Find the last tool call that doesn't have arguments set
                    for tool_call in reversed(current_tool_calls):
                        if not tool_call["function"].get("arguments"):
                            if lang == "python":
                                tool_call["function"]["arguments"] = json.dumps({"code": code})
                            elif lang == "sql":
                                tool_call["function"]["arguments"] = json.dumps({"query": code})
                            else:
                                tool_call["function"]["arguments"] = json.dumps({"code": code})
                            break
                        
            elif event.type == EventType.TOOL_RESULT:
                result = event.data.get("result", "")
                success = event.data.get("success", True)
                
                # Find corresponding tool call
                if current_tool_calls and tool_call_index < len(current_tool_calls):
                    tool_call = current_tool_calls[tool_call_index]
                    call_id = tool_call["id"]
                    
                    # Add tool response
                    current_tool_results.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result,
                    })
                    tool_call_index += 1
                    
                    # If this completes a set of tool calls, add assistant message
                    if len(current_tool_results) == len(current_tool_calls):
                        messages.append({
                            "role": "assistant",
                            "content": None,
                            "tool_calls": current_tool_calls,
                        })
                        # Add all tool responses
                        messages.extend(current_tool_results)
                        current_tool_calls = []
                        current_tool_results = []
                        tool_call_index = 0
                        
            elif event.type == EventType.ASSISTANT_RESPONSE:
                # Store for next user message or end
                pending_assistant_response = event.data.get("content", "")
                
            elif event.type == EventType.TURN_COMPLETE:
                # If there's a pending assistant response, add it now
                if pending_assistant_response:
                    messages.append({
                        "role": "assistant",
                        "content": pending_assistant_response,
                    })
                    pending_assistant_response = None
                    
        # Add any final pending response
        if pending_assistant_response:
            messages.append({
                "role": "assistant",
                "content": pending_assistant_response,
            })
        
        # Handle any remaining incomplete tool calls
        if current_tool_calls and current_tool_results:
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": current_tool_calls,
            })
            messages.extend(current_tool_results)
            
        return messages
