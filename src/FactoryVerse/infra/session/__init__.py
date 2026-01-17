"""Unified session management for FactoryVerse.

This module provides session management that combines:
- Execution environment (Jupyter or InProcess)
- Domain context (boilerplate loading)
- File management (run directories, metadata)
- Trajectory streaming (event log)
- Lifecycle management (heartbeat, status)

Key abstractions:
- FactoryVerseSession: Combined execution + domain context
- FileManager: Run directory and metadata management
- TrajectoryWriter/Reader: File-based event streaming
- SessionLifecycle: Heartbeat and status tracking

Usage:
    from FactoryVerse.infra.session import FactoryVerseSession
    from FactoryVerse.infra.execution import JupyterExecutor
    from FactoryVerse.infra.boilerplate import Scope

    # Create session with Jupyter execution
    session = FactoryVerseSession(
        session_id="my-run",
        executor=JupyterExecutor("/path/to/notebook.ipynb"),
        scope=Scope.RUNTIME
    )
    await session.start()
    result = session.execute("print(runtime.agent_id)")
    await session.stop()
"""

from FactoryVerse.infra.session.session import FactoryVerseSession
from FactoryVerse.infra.session.file_manager import (
    FileManager,
    SessionConfig,
    SessionPaths,
)
from FactoryVerse.infra.session.trajectory import (
    TrajectoryWriter,
    TrajectoryReader,
    TrajectoryEvent,
    TurnData,
    EventType,
)
from FactoryVerse.infra.session.lifecycle import (
    SessionLifecycle,
    SessionState,
    SessionStatus,
)

__all__ = [
    # Session
    "FactoryVerseSession",
    # File management
    "FileManager",
    "SessionConfig",
    "SessionPaths",
    # Trajectory
    "TrajectoryWriter",
    "TrajectoryReader",
    "TrajectoryEvent",
    "TurnData",
    "EventType",
    # Lifecycle
    "SessionLifecycle",
    "SessionState",
    "SessionStatus",
]
