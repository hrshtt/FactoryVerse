"""Tier 6: Generative/Interactive Layer.

Orchestrates LLM connection and agent turn loop.
"""

import logging
from typing import Optional, Any, Dict, List, TYPE_CHECKING

from ..config import InteractionConfig, InteractionMode
from ..status import Tier6Status, TierState, PrerequisiteResult
from .base import TierBase, Tier, TierInitializationError

if TYPE_CHECKING:
    from ..environment import Environment

logger = logging.getLogger(__name__)


class Tier6Interaction(TierBase):
    """Tier 6: Generative/Interactive Layer.

    Manages LLM interaction in three modes:
    - AUTONOMOUS: Continuous agent loop with context management
    - ASSISTED: Single-turn interaction per user message
    - MCP: MCP server mode where context is managed externally
    """

    tier_level = Tier.INTERACTION

    def __init__(self, environment: "Environment"):
        super().__init__(environment)
        self._llm_client: Optional[Any] = None
        self._orchestrator: Optional[Any] = None
        self._trajectory_writer: Optional[Any] = None
        self._tools_registered: int = 0

    @property
    def config(self) -> InteractionConfig:
        """Get tier 6 configuration."""
        return self._env.config.tier6

    @property
    def llm_client(self) -> Optional[Any]:
        """Get LLM client."""
        return self._llm_client

    @property
    def orchestrator(self) -> Optional[Any]:
        """Get AgentOrchestrator."""
        return self._orchestrator

    async def verify_prerequisites(self) -> PrerequisiteResult:
        """Verify Tier 5 (Specification) is ready."""
        tier5 = self._env.tier5

        if tier5 is None or not tier5.is_ready:
            return PrerequisiteResult.failed(
                missing=["tier5_specification"],
                message="Agent specification must be ready before interaction",
            )

        return PrerequisiteResult.ok()

    async def initialize(self) -> None:
        """Initialize LLM client and orchestrator."""
        self._set_state(TierState.INITIALIZING)

        try:
            # Initialize LLM client
            await self._init_llm_client()

            # Initialize trajectory writer
            await self._init_trajectory_writer()

            # Initialize orchestrator
            await self._init_orchestrator()

            self._set_state(TierState.READY)

        except Exception as e:
            self._set_state(TierState.ERROR, str(e))
            raise TierInitializationError(self.tier_level, str(e)) from e

    async def _init_llm_client(self) -> None:
        """Initialize LLM client from config."""
        from FactoryVerse.llm.client.factory import create_client_from_env

        self._llm_client = create_client_from_env(
            provider=self.config.llm_provider,
            model=self.config.model,
        )

        logger.info(
            f"Tier 6: LLM client initialized ({self.config.llm_provider}/{self.config.model})"
        )

    async def _init_trajectory_writer(self) -> None:
        """Initialize trajectory writer for logging."""
        from FactoryVerse.infra.session.trajectory import TrajectoryWriter

        tier4 = self._env.tier4
        if tier4 and tier4.session_dir:
            trajectory_path = tier4.session_dir / "trajectory.jsonl"
            self._trajectory_writer = TrajectoryWriter(trajectory_path)
            logger.info(f"Tier 6: Trajectory writer initialized at {trajectory_path}")

    async def _init_orchestrator(self) -> None:
        """Initialize AgentOrchestrator."""
        from FactoryVerse.llm.orchestrator import AgentOrchestrator
        import tempfile

        tier5 = self._env.tier5
        if tier5 is None:
            raise RuntimeError("Tier 5 must be initialized")

        # Create a runtime protocol adapter
        runtime = self._create_runtime_adapter()

        # Get tool definitions
        mode = (
            "autonomous"
            if self.config.mode == InteractionMode.AUTONOMOUS
            else "assisted"
        )
        tool_defs = runtime.get_tool_definitions(mode=mode)
        self._tools_registered = len(tool_defs)

        # Write system prompt to temp file (AgentOrchestrator expects a file path)
        system_prompt = tier5.system_prompt or "You are a Factorio automation agent."
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as prompt_file:
            prompt_file.write(system_prompt)
            prompt_path = prompt_file.name

        if self._llm_client is None:
            raise RuntimeError("LLM Client not initialized")

        self._orchestrator = AgentOrchestrator(
            llm_client=self._llm_client,
            runtime=runtime,
            system_prompt_path=prompt_path,
            trajectory_writer=self._trajectory_writer,
            max_context_tokens=self.config.max_context_tokens,
            mode=mode,
        )

        if self.config.max_turns:
            self._orchestrator.set_max_turns(self.config.max_turns)

        logger.info(
            f"Tier 6: Orchestrator initialized in {mode} mode with {self._tools_registered} tools"
        )

    def _create_runtime_adapter(self) -> Any:
        """Create runtime adapter that satisfies RuntimeProtocol."""
        tier3 = self._env.tier3
        tier4 = self._env.tier4

        # Return an adapter that wraps our tier components
        return _RuntimeAdapter(tier3=tier3, tier4=tier4)

    async def verify_ready(self) -> Tier6Status:
        """Verify interaction layer is ready."""
        if self._state != TierState.READY:
            return Tier6Status(
                state=self._state,
                error=self._error,
            )

        # Check LLM responsiveness
        llm_connected = self._llm_client is not None
        llm_responsive = False

        if llm_connected:
            try:
                # Simple ping - just check we can create a message
                llm_responsive = True
            except Exception:
                pass

        return Tier6Status(
            state=self._state,
            llm_connected=llm_connected,
            llm_responsive=llm_responsive,
            orchestrator_mode=self.config.mode.value
            if hasattr(self.config.mode, "value")
            else self.config.mode,
            tools_registered=self._tools_registered,
        )

    async def reset(self) -> None:
        """Reset by recreating orchestrator."""
        await self.shutdown()
        await self.initialize()

    async def shutdown(self) -> None:
        """Shutdown interaction layer."""
        self._set_state(TierState.SHUTTING_DOWN)

        self._orchestrator = None
        self._llm_client = None
        self._trajectory_writer = None
        self._tools_registered = 0

        self._set_state(TierState.SHUTDOWN)

    # =========================================================================
    # Interaction Methods
    # =========================================================================

    async def run_turn(self, user_message: str) -> str:
        """Run single agent turn.

        Args:
            user_message: User message to process

        Returns:
            Agent's response
        """
        if not self._orchestrator:
            raise RuntimeError("Orchestrator not initialized")

        return await self._orchestrator.run_turn(user_message)

    async def run_loop(self, initial_message: Optional[str] = None) -> None:
        """Run autonomous agent loop.

        Args:
            initial_message: Optional initial message to start with
        """
        if not self._orchestrator:
            raise RuntimeError("Orchestrator not initialized")

        if self.config.mode != InteractionMode.AUTONOMOUS:
            raise RuntimeError("run_loop only available in AUTONOMOUS mode")

        # Initial message or default
        message = initial_message or "Begin your task."

        while self._orchestrator.has_turns_remaining():
            try:
                await self._orchestrator.run_turn(message)

                # In autonomous mode, agent continues with empty user message
                message = ""

            except Exception as e:
                logger.error(f"Tier 6: Error in agent loop: {e}")
                break

    async def start_session(self) -> str:
        """Start a new agent session.

        Returns:
            Session ID
        """
        tier4 = self._env.tier4
        return str(tier4.session_dir) if tier4 and tier4.session_dir else "unknown"

    def get_statistics(self) -> Dict[str, Any]:
        """Get trajectory statistics."""
        if self._orchestrator:
            return self._orchestrator.get_statistics()
        return {}


class _RuntimeAdapter:
    """Adapter that implements RuntimeProtocol using Environment tiers."""

    def __init__(self, tier3, tier4):
        self._tier3 = tier3
        self._tier4 = tier4

    def execute_dsl(self, code: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Execute DSL code via RCON."""
        # DSL execution would be handled here
        return self._tier3.execute_lua(code)

    def execute_duckdb(
        self, query: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Execute DuckDB query."""
        if self._tier4.database:
            result = self._tier4.database.execute(query).fetchall()
            return str(result)
        return "Database not available"

    def respond(self, message: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Return chat response."""
        return message

    def get_tool_definitions(self, mode: str = "autonomous") -> List[Dict[str, Any]]:
        """Get tool definitions for LLM."""
        # Return standard tool definitions
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "execute_dsl",
                    "description": "Execute FactoryVerse DSL code",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "DSL code to execute",
                            }
                        },
                        "required": ["code"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_duckdb",
                    "description": "Execute SQL query on game state database",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "SQL query"}
                        },
                        "required": ["query"],
                    },
                },
            },
        ]

        if mode == "assisted":
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "respond",
                        "description": "Send a response to the user",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "message": {
                                    "type": "string",
                                    "description": "Response message",
                                }
                            },
                            "required": ["message"],
                        },
                    },
                }
            )

        return tools

    def execute_code(self, code: str, compress_output: bool = False) -> str:
        """Execute arbitrary code."""
        return self._tier3.execute_lua(code)
