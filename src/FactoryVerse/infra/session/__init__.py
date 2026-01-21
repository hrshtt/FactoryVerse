"""Unified session management for FactoryVerse.

This module provides session management that combines:
- Execution environment (Jupyter or InProcess via Environment)
- Domain context (Environment tier4 runtime)
- File management (run directories, metadata)
- Trajectory streaming (event log)
- Lifecycle management (heartbeat, status)

Key abstractions:
- FactoryVerseSession: Combined execution + domain context (wraps Environment)
- FileManager: Run directory and metadata management
- TrajectoryWriter/Reader: File-based event streaming
- SessionLifecycle: Heartbeat and status tracking

Usage:
    from FactoryVerse.infra.session import FactoryVerseSession
    from FactoryVerse.infra.execution import JupyterExecutor

    # Create session with Jupyter execution
    session = FactoryVerseSession(
        session_id="my-run",
        executor=JupyterExecutor("/path/to/notebook.ipynb"),
        agent_id="agent_1"
    )
    await session.start()
    result = session.execute("print(walking)")
    await session.stop()

For direct Environment usage (recommended for new code):
    from FactoryVerse.environment import Environment, Tier

    env = Environment.for_testing()
    await env.initialize(up_to=Tier.RUNTIME)
    result = await env.tier4.execute_code("print(walking)")
    await env.shutdown()
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
