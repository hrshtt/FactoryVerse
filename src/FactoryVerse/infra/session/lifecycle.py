"""Session lifecycle management.

Manages session.json file for tracking live/complete/orphaned status.
Enables decoupled observation - viewers can check if session is active
without being in the same process.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class SessionStatus(str, Enum):
    """Status of an agent session."""

    RUNNING = "running"  # Agent is actively running
    PAUSED = "paused"  # Agent paused, can resume
    COMPLETE = "complete"  # Session finished normally
    ORPHANED = "orphaned"  # Process died unexpectedly


@dataclass
class SessionState:
    """Current state of a session from session.json."""

    status: SessionStatus
    pid: Optional[int]
    started_at: str
    last_heartbeat: str
    current_turn: int
    model: str
    mode: str

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "pid": self.pid,
            "started_at": self.started_at,
            "last_heartbeat": self.last_heartbeat,
            "current_turn": self.current_turn,
            "model": self.model,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionState":
        return cls(
            status=SessionStatus(data["status"]),
            pid=data.get("pid"),
            started_at=data["started_at"],
            last_heartbeat=data["last_heartbeat"],
            current_turn=data.get("current_turn", 0),
            model=data["model"],
            mode=data["mode"],
        )


class SessionLifecycle:
    """Manage session.json lifecycle state.

    Provides:
    - Session start/complete/pause marking
    - Heartbeat updates for liveness detection
    - Status checking with orphan detection

    Usage:
        lifecycle = SessionLifecycle(session_dir)

        # Start session
        lifecycle.start(model="intellect-3", mode="assisted")

        # During turns
        lifecycle.heartbeat(current_turn=5)

        # Session end
        lifecycle.complete(total_turns=10)

        # From viewer
        status = lifecycle.get_status()  # May return ORPHANED
    """

    HEARTBEAT_TIMEOUT = 30  # Seconds before considering session stale

    def __init__(self, session_dir: Path):
        """Initialize lifecycle manager.

        Args:
            session_dir: Path to session directory
        """
        self.session_dir = Path(session_dir)
        self.session_file = self.session_dir / "session.json"

    def start(self, model: str, mode: str) -> None:
        """Mark session as running.

        Records current PID for orphan detection.
        """
        self.session_dir.mkdir(parents=True, exist_ok=True)

        state = SessionState(
            status=SessionStatus.RUNNING,
            pid=os.getpid(),
            started_at=datetime.now().isoformat(),
            last_heartbeat=datetime.now().isoformat(),
            current_turn=0,
            model=model,
            mode=mode,
        )
        self._write(state)

    def heartbeat(self, current_turn: int) -> None:
        """Update heartbeat timestamp.

        Should be called periodically during session.
        """
        state = self._read()
        if state:
            state.last_heartbeat = datetime.now().isoformat()
            state.current_turn = current_turn
            self._write(state)

    def complete(self, total_turns: int) -> None:
        """Mark session as complete."""
        state = self._read()
        if state:
            state.status = SessionStatus.COMPLETE
            state.current_turn = total_turns
            state.last_heartbeat = datetime.now().isoformat()
            self._write(state)

    def pause(self) -> None:
        """Mark session as paused."""
        state = self._read()
        if state:
            state.status = SessionStatus.PAUSED
            state.last_heartbeat = datetime.now().isoformat()
            self._write(state)

    def resume(self) -> None:
        """Resume a paused session."""
        state = self._read()
        if state and state.status == SessionStatus.PAUSED:
            state.status = SessionStatus.RUNNING
            state.pid = os.getpid()
            state.last_heartbeat = datetime.now().isoformat()
            self._write(state)

    def get_status(self) -> Optional[SessionStatus]:
        """Get current status with orphan detection.

        Checks if PID is alive and heartbeat is recent.

        Returns:
            Current status, or None if no session.json
        """
        state = self._read()
        if not state:
            return None

        # If marked complete/paused, trust that
        if state.status in (SessionStatus.COMPLETE, SessionStatus.PAUSED):
            return state.status

        # If running, check for orphan
        if state.status == SessionStatus.RUNNING:
            if self._is_orphaned(state):
                return SessionStatus.ORPHANED
            return SessionStatus.RUNNING

        return state.status

    def get_state(self) -> Optional[SessionState]:
        """Get full session state.

        Returns:
            SessionState or None if no session.json
        """
        state = self._read()
        if state and state.status == SessionStatus.RUNNING:
            if self._is_orphaned(state):
                state.status = SessionStatus.ORPHANED
        return state

    def _is_orphaned(self, state: SessionState) -> bool:
        """Check if session is orphaned.

        Orphaned if:
        - PID is no longer running, OR
        - Heartbeat is stale (> HEARTBEAT_TIMEOUT seconds)
        """
        # Check PID
        if state.pid:
            if not self._is_pid_alive(state.pid):
                return True

        # Check heartbeat
        try:
            last_hb = datetime.fromisoformat(state.last_heartbeat)
            age = (datetime.now() - last_hb).total_seconds()
            if age > self.HEARTBEAT_TIMEOUT:
                return True
        except (ValueError, TypeError):
            return True

        return False

    def _is_pid_alive(self, pid: int) -> bool:
        """Check if a process is running."""
        try:
            os.kill(pid, 0)  # Signal 0 = check existence
            return True
        except (OSError, ProcessLookupError):
            return False

    def _write(self, state: SessionState) -> None:
        """Write state to session.json."""
        with open(self.session_file, "w") as f:
            json.dump(state.to_dict(), f, indent=2)

    def _read(self) -> Optional[SessionState]:
        """Read state from session.json."""
        if not self.session_file.exists():
            return None

        try:
            with open(self.session_file, "r") as f:
                data = json.load(f)
            return SessionState.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            return None
