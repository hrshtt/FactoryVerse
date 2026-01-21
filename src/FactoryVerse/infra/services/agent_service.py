"""Agent orchestration service.

Unified service for creating, managing, and observing agent sessions.
Can be used by CLI, GUI, MCP, and other consumers.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any

from FactoryVerse.config import get_config
from FactoryVerse.infra.session import FactoryVerseSession
from FactoryVerse.infra.session.file_manager import (
    FileManager,
    SessionConfig,
    SessionPaths,
)
from FactoryVerse.infra.session.trajectory import TrajectoryWriter
from FactoryVerse.infra.session.lifecycle import SessionLifecycle, SessionStatus
from FactoryVerse.infra.execution import JupyterExecutor
from FactoryVerse.llm.client.factory import create_client_from_env
from FactoryVerse.llm.orchestrator import AgentOrchestrator, RuntimeProtocol
from FactoryVerse.llm.context import InitialStateGenerator
from FactoryVerse.infra.output import ConsoleOutput
from FactoryVerse.llm.prompts import generate_system_prompt

logger = logging.getLogger(__name__)


class SessionRuntimeAdapter:
    """Adapter to make FactoryVerseSession compatible with RuntimeProtocol.

    TODO: This should be removed by making FactoryVerseSession implement RuntimeProtocol directly.
    """

    def __init__(self, session: FactoryVerseSession):
        self._session = session

    def execute_dsl(self, code: str, metadata=None) -> str:
        result = self._session.execute_dsl(code)
        if result.is_error:
            return f"❌ Error: {result.error}"
        return result.output or ""

    def execute_duckdb(self, query: str, metadata=None) -> str:
        result = self._session.execute_duckdb(query)
        if result.is_error:
            return f"❌ Error: {result.error}"
        return result.output or ""

    def respond(self, message: str, metadata=None) -> str:
        return message

    def get_tool_definitions(self, mode: str = "autonomous"):
        return self._session.get_tool_definitions(mode)

    def execute_code(self, code: str, compress_output: bool = False) -> str:
        result = self._session.execute(code, compress_output=compress_output)
        if result.is_error:
            return f"Error: {result.error}"
        return result.output or ""


@dataclass
class AgentSession:
    """Represents an active agent session.

    Contains all components needed to run and observe an agent:
    - Session: Execution + domain context
    - Orchestrator: LLM turn loop
    - Trajectory: Event streaming for observation
    - Lifecycle: Status tracking
    """

    session_id: str
    session_dir: Path
    config: SessionConfig
    paths: SessionPaths
    session: FactoryVerseSession  # Execution + domain
    orchestrator: AgentOrchestrator
    trajectory_writer: TrajectoryWriter
    lifecycle: SessionLifecycle
    adapter: RuntimeProtocol  # Adapter for orchestrator

    @property
    def model(self) -> str:
        """Model name."""
        return self.config.model

    @property
    def mode(self) -> str:
        """Mode (assisted or autonomous)."""
        return self.config.mode

    @property
    def turn_number(self) -> int:
        """Current turn number."""
        return self.orchestrator.turn_number

    async def stop(self) -> None:
        """Stop the session and mark as complete."""
        logger.info(f"Stopping session {self.session_id}")

        # Mark lifecycle as complete
        self.lifecycle.complete(total_turns=self.turn_number)

        # Write session end to trajectory
        self.trajectory_writer.session_end(
            total_turns=self.turn_number, status="complete"
        )

        # Stop session
        await self.session.stop()

        # Update metadata
        self.config.mark_ended(total_turns=self.turn_number)
        file_mgr = FileManager()
        file_mgr.save_metadata(self.config)


class AgentService:
    """Unified service for agent orchestration.

    Provides:
    - Session creation and lifecycle management
    - Turn execution
    - Status tracking
    - Session listing

    Can be used by CLI, GUI, MCP, and other consumers.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        """Initialize agent service.

        Args:
            output_dir: Base output directory (default: from config)
        """
        self.config = get_config()
        self.file_mgr = FileManager(output_dir)
        self.file_mgr.initialize()

        # In-memory session registry
        self._sessions: Dict[str, AgentSession] = {}

    async def create_session(
        self,
        model: str,
        mode: str = "assisted",
        instance: Optional[str] = None,
        agent_id: str = "agent_1",
        provider: Optional[str] = None,
        max_turns: Optional[int] = None,
    ) -> AgentSession:
        """Create and start an agent session.

        Args:
            model: Model name (e.g., 'intellect-3', 'gpt-4o')
            mode: 'assisted' or 'autonomous'
            instance: Factorio instance name (auto-detect if None)
            agent_id: Agent identifier
            provider: LLM provider (auto-detect from env if None)
            max_turns: Maximum turns (None for unlimited)

        Returns:
            AgentSession ready to use

        Raises:
            RuntimeError: If session creation fails
        """
        logger.info(f"Creating agent session: model={model}, mode={mode}")

        # Create session config and directory
        session_config = self.file_mgr.create_session(
            model=model,
            mode=mode,
            config={
                "instance": instance,
                "agent_id": agent_id,
                "provider": provider,
            },
        )

        paths = self.file_mgr.get_session_paths(session_config)
        session_id = f"{model}/{session_config.run_id}"

        # Set environment variables for boilerplate
        os.environ["FV_SESSION_DIR"] = str(paths.session_dir)
        os.environ["FV_AGENT_ID"] = agent_id

        # Create execution environment
        executor = JupyterExecutor(paths.notebook)

        # Create FactoryVerseSession
        fv_session = FactoryVerseSession(
            session_id=session_id,
            executor=executor,
                        instance=instance,
            agent_id=agent_id,
            session_dir=paths.session_dir,
        )

        # Start session
        await fv_session.start()
        logger.info(f"Session {session_id} started")

        # Create trajectory writer
        trajectory_path = paths.session_dir / "trajectory.jsonl"
        trajectory_writer = TrajectoryWriter(trajectory_path)
        trajectory_writer.session_start(model=model, mode=mode)

        # Create lifecycle manager
        lifecycle = SessionLifecycle(paths.session_dir)
        lifecycle.start(model=model, mode=mode)

        # Create runtime adapter
        adapter = SessionRuntimeAdapter(fv_session)

        # Create LLM client
        llm_client = create_client_from_env(
            provider=provider,
            model=model,
        )

        # Generate system prompt
        system_prompt_path = paths.system_prompt
        system_prompt = generate_system_prompt(
            include_api_reference=True,
            include_schema=True,
            include_examples=False,
        )
        system_prompt_path.write_text(system_prompt)

        # Generate initial state
        initial_state_path = paths.initial_state
        state_gen = InitialStateGenerator(adapter)
        state_gen.generate_summary(paths.session_dir)

        # Create console output
        console = ConsoleOutput(enabled=True)

        # Create orchestrator
        orchestrator = AgentOrchestrator(
            llm_client=llm_client,
            runtime=adapter,
            system_prompt_path=str(system_prompt_path),
            chat_log_path=str(paths.chat_log),
            console_output=console,
            trajectory_writer=trajectory_writer,
            initial_state_path=str(initial_state_path),
            mode=mode,
        )

        if max_turns is not None:
            orchestrator.set_max_turns(max_turns)

        # Create AgentSession
        agent_session = AgentSession(
            session_id=session_id,
            session_dir=paths.session_dir,
            config=session_config,
            paths=paths,
            session=fv_session,
            orchestrator=orchestrator,
            trajectory_writer=trajectory_writer,
            lifecycle=lifecycle,
            adapter=adapter,
        )

        # Register session
        self._sessions[session_id] = agent_session

        logger.info(f"Agent session {session_id} created and ready")
        return agent_session

    async def continue_session(
        self,
        session_id: str,
        provider: Optional[str] = None,
        max_turns: Optional[int] = None,
    ) -> AgentSession:
        """Continue an existing session from trajectory.

        Loads a completed or paused session and reconstructs its state
        from trajectory.jsonl, allowing you to continue the conversation.

        Args:
            session_id: Session identifier (format: "model/run_id")
            provider: LLM provider (auto-detect from env if None)
            max_turns: Maximum turns (None for unlimited)

        Returns:
            AgentSession ready to continue

        Raises:
            KeyError: If session not found
            RuntimeError: If trajectory cannot be loaded
        """
        # Parse session_id
        parts = session_id.rsplit("/", 1)
        if len(parts) != 2:
            raise KeyError(f"Invalid session_id format: {session_id}")

        model, run_id = parts

        # Load session config
        session_config = self.file_mgr.load_metadata(model, run_id)
        if not session_config:
            raise KeyError(f"Session {session_id} not found")

        paths = self.file_mgr.get_session_paths(session_config)
        trajectory_path = paths.session_dir / "trajectory.jsonl"

        if not trajectory_path.exists():
            raise RuntimeError(f"Trajectory file not found: {trajectory_path}")

        logger.info(f"Continuing session {session_id} from trajectory")

        # Read trajectory
        from FactoryVerse.infra.session.trajectory import TrajectoryReader

        trajectory_reader = TrajectoryReader(trajectory_path)

        # Get session info
        session_info = trajectory_reader.get_session_info()
        if not session_info:
            raise RuntimeError("Cannot determine session info from trajectory")

        # Use mode from session info or config
        mode = session_info.get("mode") or session_config.mode

        # Set environment variables
        os.environ["FV_SESSION_DIR"] = str(paths.session_dir)
        agent_id = session_config.config.get("agent_id", "agent_1")
        os.environ["FV_AGENT_ID"] = agent_id

        # Create execution environment
        executor = JupyterExecutor(paths.notebook)

        # Create FactoryVerseSession
        instance = session_config.config.get("instance")
        fv_session = FactoryVerseSession(
            session_id=session_id,
            executor=executor,
                        instance=instance,
            agent_id=agent_id,
            session_dir=paths.session_dir,
        )

        # Start session
        await fv_session.start()
        logger.info(f"Session {session_id} started")

        # Create trajectory writer (append mode - will continue writing)
        # Note: We don't write session_start again - trajectory already has it
        trajectory_writer = TrajectoryWriter(trajectory_path)

        # Create lifecycle manager
        lifecycle = SessionLifecycle(paths.session_dir)
        lifecycle.resume()  # Resume from paused/complete state

        # Create runtime adapter
        adapter = SessionRuntimeAdapter(fv_session)

        # Create LLM client
        llm_client = create_client_from_env(
            provider=provider,
            model=model,
        )

        # Load system prompt
        system_prompt_path = paths.system_prompt
        system_prompt = None
        if system_prompt_path.exists():
            system_prompt = system_prompt_path.read_text()
        else:
            # Generate if missing
            system_prompt = generate_system_prompt(
                include_api_reference=True,
                include_schema=True,
                include_examples=False,
            )
            system_prompt_path.write_text(system_prompt)

        # Load initial state
        initial_state_path = paths.initial_state
        initial_state = None
        if initial_state_path.exists():
            initial_state = initial_state_path.read_text()
        else:
            # Generate if missing
            state_gen = InitialStateGenerator(adapter)
            state_gen.generate_summary(paths.session_dir)
            if initial_state_path.exists():
                initial_state = initial_state_path.read_text()

        # Create console output
        console = ConsoleOutput(enabled=True)

        # Create orchestrator
        orchestrator = AgentOrchestrator(
            llm_client=llm_client,
            runtime=adapter,
            system_prompt_path=str(system_prompt_path),
            chat_log_path=str(paths.chat_log),
            console_output=console,
            trajectory_writer=trajectory_writer,
            initial_state_path=None,  # We'll load it manually
            mode=mode,
        )

        # Load trajectory state into orchestrator
        orchestrator.load_from_trajectory(
            trajectory_reader=trajectory_reader,
            system_prompt=system_prompt,
            initial_state=initial_state,
        )

        if max_turns is not None:
            orchestrator.set_max_turns(max_turns)

        # Create AgentSession
        agent_session = AgentSession(
            session_id=session_id,
            session_dir=paths.session_dir,
            config=session_config,
            paths=paths,
            session=fv_session,
            orchestrator=orchestrator,
            trajectory_writer=trajectory_writer,
            lifecycle=lifecycle,
            adapter=adapter,
        )

        # Register session
        self._sessions[session_id] = agent_session

        logger.info(
            f"Session {session_id} continued from trajectory, ready for turn {agent_session.turn_number}"
        )
        return agent_session

    async def run_turn(self, session_id: str, user_message: str) -> str:
        """Run a single turn in a session.

        Args:
            session_id: Session identifier
            user_message: User's message

        Returns:
            Agent's response text

        Raises:
            KeyError: If session not found
        """
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Session {session_id} not found")

        # Update heartbeat
        session.lifecycle.heartbeat(current_turn=session.turn_number)

        # Run turn
        response = await session.orchestrator.run_turn(user_message)

        # Update heartbeat again
        session.lifecycle.heartbeat(current_turn=session.turn_number)

        return response

    async def stop_session(self, session_id: str) -> None:
        """Stop a running session.

        Args:
            session_id: Session identifier

        Raises:
            KeyError: If session not found
        """
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Session {session_id} not found")

        await session.stop()
        del self._sessions[session_id]

        logger.info(f"Session {session_id} stopped")

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        """Get a session by ID.

        Args:
            session_id: Session identifier

        Returns:
            AgentSession if found, None otherwise
        """
        return self._sessions.get(session_id)

    def get_session_status(self, session_id: str) -> Optional[SessionStatus]:
        """Get current status of a session.

        Checks both in-memory sessions and file-based lifecycle.
        For old sessions without session.json, checks if trajectory.jsonl exists
        to determine if it's a completed session.

        Args:
            session_id: Session identifier

        Returns:
            SessionStatus if found, None otherwise
        """
        # Check in-memory first
        if session_id in self._sessions:
            return SessionStatus.RUNNING

        # Check file-based lifecycle
        # Parse session_id (format: "model/run_id" where model may contain slashes)
        # Model names can be like "anthropic/claude-sonnet-4.5", so we need to
        # split from the right - last part is run_id, everything before is model
        parts = session_id.rsplit("/", 1)  # Split from right, max 1 split
        if len(parts) != 2:
            return None

        model, run_id = parts
        session_config = self.file_mgr.load_metadata(model, run_id)
        if not session_config:
            return None

        paths = self.file_mgr.get_session_paths(session_config)
        lifecycle = SessionLifecycle(paths.session_dir)
        status = lifecycle.get_status()

        # If no session.json exists (old sessions), treat as COMPLETE
        # Old sessions before SessionLifecycle was added are completed sessions
        if status is None:
            # If we have metadata.json, it's a valid old session - treat as complete
            # (Even if trajectory.jsonl doesn't exist yet, it's still a completed session)
            return SessionStatus.COMPLETE

        return status

    def list_sessions(
        self,
        model: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[SessionConfig]:
        """List all sessions.

        Combines in-memory sessions with file-based sessions.

        Args:
            model: Optional model filter
            limit: Maximum sessions to return

        Returns:
            List of SessionConfig, sorted by start time (newest first)
        """
        # Get file-based sessions
        file_sessions = self.file_mgr.list_sessions(model=model, limit=limit)

        # Add in-memory sessions (they may not be in file system yet)
        for session in self._sessions.values():
            # Check if already in list
            if not any(
                s.run_id == session.config.run_id and s.model == session.config.model
                for s in file_sessions
            ):
                file_sessions.append(session.config)

        # Sort by start time (newest first)
        file_sessions.sort(key=lambda s: s.started_at, reverse=True)

        if limit:
            file_sessions = file_sessions[:limit]

        return file_sessions

    def get_registered_agents(self) -> List[Dict[str, Any]]:
        """List all persistent agents from the registry.

        Returns:
            List of agent profiles as dictionaries.
        """
        from FactoryVerse.agent.core.registry import AgentRegistry

        # Initialize registry using config paths
        registry_dir = self.config.fv_output_dir / "agents"
        registry = AgentRegistry(registry_dir)

        profiles = registry.list_agents()
        return [p.model_dump() for p in profiles]
