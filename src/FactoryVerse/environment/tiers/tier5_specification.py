"""Tier 5: Agent Specification.

Orchestrates system prompt generation and task definition.
"""

import logging
from typing import Optional, Dict, Any, TYPE_CHECKING

from ..config import SpecificationConfig
from ..status import Tier5Status, TierState, PrerequisiteResult
from .base import TierBase, Tier, TierInitializationError

if TYPE_CHECKING:
    from ..environment import Environment

logger = logging.getLogger(__name__)


class Tier5Specification(TierBase):
    """Tier 5: Agent Specification.

    Composes system prompt from templates and runtime state:
    - Core system prompt with role/capabilities
    - API reference documentation
    - Database schema reference
    - Task-specific instructions
    - Initial state summary (agent's starting situation)
    """

    tier_level = Tier.SPECIFICATION

    def __init__(self, environment: "Environment"):
        super().__init__(environment)
        self._system_prompt: Optional[str] = None
        self._api_reference: Optional[str] = None
        self._schema_reference: Optional[str] = None
        self._task_definition: Optional[Dict[str, Any]] = None
        self._initial_state: Optional[str] = None

    @property
    def config(self) -> SpecificationConfig:
        """Get tier 5 configuration."""
        return self._env.config.tier5

    @property
    def system_prompt(self) -> Optional[str]:
        """Get complete system prompt."""
        return self._system_prompt

    @property
    def api_reference(self) -> Optional[str]:
        """Get API reference documentation."""
        return self._api_reference

    @property
    def schema_reference(self) -> Optional[str]:
        """Get database schema reference."""
        return self._schema_reference

    @property
    def initial_state(self) -> Optional[str]:
        """Get initial state summary."""
        return self._initial_state

    async def verify_prerequisites(self) -> PrerequisiteResult:
        """Verify Tier 4 (Runtime) is ready."""
        tier4 = self._env.tier4

        if tier4 is None or not tier4.is_ready:
            return PrerequisiteResult.failed(
                missing=["tier4_runtime"],
                message="Runtime must be initialized to generate prompts",
            )

        return PrerequisiteResult.ok()

    async def initialize(self) -> None:
        """Generate system prompt from templates and runtime state."""
        self._set_state(TierState.INITIALIZING)

        try:
            # Generate components
            if self.config.include_api_reference:
                await self._generate_api_reference()

            if self.config.include_schema_reference:
                await self._generate_schema_reference()

            # Load or generate task definition
            if self.config.task_name:
                await self._load_task_definition(self.config.task_name)

            # Compose full system prompt
            await self._compose_system_prompt()

            # Generate initial state (orients the agent about its situation)
            if self.config.include_initial_state:
                await self._generate_initial_state()

            self._set_state(TierState.READY)

        except Exception as e:
            self._set_state(TierState.ERROR, str(e))
            raise TierInitializationError(self.tier_level, str(e)) from e

    async def _generate_api_reference(self) -> None:
        """Generate API reference documentation."""
        from FactoryVerse.llm.prompts.api_reference import generate_api_reference

        self._api_reference = generate_api_reference()
        logger.info(
            f"Tier 5: API reference generated ({len(self._api_reference)} chars)"
        )

    async def _generate_schema_reference(self) -> None:
        """Generate database schema reference."""
        from FactoryVerse.llm.prompts.schema_reference import generate_schema_reference

        # generate_schema_reference() introspects schema definitions, no DB needed
        self._schema_reference = generate_schema_reference()
        logger.info(
            f"Tier 5: Schema reference generated ({len(self._schema_reference)} chars)"
        )

    async def _load_task_definition(self, task_name: str) -> None:
        """Load task definition by name."""
        # Future: Load from tasks registry
        self._task_definition = {
            "name": task_name,
            "description": f"Task: {task_name}",
            # Additional task fields would be loaded here
        }
        logger.info(f"Tier 5: Task '{task_name}' loaded")

    async def _compose_system_prompt(self) -> None:
        """Compose full system prompt from components."""
        from FactoryVerse.llm.prompts.system_prompt import generate_system_prompt

        # Generate with pre-computed components
        self._system_prompt = generate_system_prompt(
            include_api_reference=self.config.include_api_reference,
            include_schema=self.config.include_schema_reference,
            api_reference=self._api_reference,
            schema_reference=self._schema_reference,
        )

        logger.info(
            f"Tier 5: System prompt composed ({len(self._system_prompt)} chars)"
        )

    async def _generate_initial_state(self) -> None:
        """Generate initial state summary showing agent's starting situation.

        Uses InitialStateGenerator to execute code and capture outputs,
        creating a document that orients the agent about:
        - Current position and inventory
        - Nearby resources and entities
        - Available technologies and recipes
        """
        from FactoryVerse.llm.context.initial_state import InitialStateGenerator

        tier4 = self._env.tier4
        if tier4 is None or tier4.session_dir is None:
            logger.warning("Tier 5: Cannot generate initial state - no session directory")
            return

        # Create a runtime adapter for code execution
        runtime_adapter = _InitialStateRuntimeAdapter(self._env)

        try:
            generator = InitialStateGenerator(runtime_adapter)
            self._initial_state = generator.generate_summary(tier4.session_dir)
            logger.info(
                f"Tier 5: Initial state generated ({len(self._initial_state)} chars)"
            )
        except Exception as e:
            logger.warning(f"Tier 5: Initial state generation failed: {e}")
            self._initial_state = None

    async def verify_ready(self) -> Tier5Status:
        """Verify specification is ready."""
        if self._state != TierState.READY:
            return Tier5Status(
                state=self._state,
                error=self._error,
            )

        return Tier5Status(
            state=self._state,
            system_prompt_generated=self._system_prompt is not None,
            prompt_length=len(self._system_prompt) if self._system_prompt else 0,
            task_defined=self._task_definition is not None,
            task_valid=self._task_definition is not None,  # Simplified validation
        )

    async def reset(self) -> None:
        """Reset by regenerating prompt."""
        await self.shutdown()
        await self.initialize()

    async def shutdown(self) -> None:
        """Clear specification state."""
        self._system_prompt = None
        self._api_reference = None
        self._schema_reference = None
        self._task_definition = None
        self._initial_state = None
        self._set_state(TierState.SHUTDOWN)

    # =========================================================================
    # Prompt Modification Methods
    # =========================================================================

    async def regenerate(self) -> str:
        """Regenerate system prompt with current state.

        Returns:
            New system prompt
        """
        await self._compose_system_prompt()
        return self._system_prompt or ""

    def set_task(self, task_name: str, task_definition: Dict[str, Any]) -> None:
        """Set task definition manually.

        Args:
            task_name: Task name
            task_definition: Task definition dict
        """
        self._task_definition = {
            "name": task_name,
            **task_definition,
        }


class _InitialStateRuntimeAdapter:
    """Adapter for InitialStateGenerator that executes code via Tier 3/4.

    InitialStateGenerator expects a runtime with execute_code() method.
    This adapter bridges between Environment tiers and that interface.
    """

    def __init__(self, env: "Environment"):
        self._env = env

    def execute_code(self, code: str, compress_output: bool = False) -> str:
        """Execute Python code and return output.

        The code expects these variables to be available:
        - walking, crafting, research, inventory (from embodied_actions)
        - remote_view (for SQL queries)
        - rcon_client, agent_id (for direct RCON calls)

        We build a namespace with these and exec the code.
        """
        tier3 = self._env.tier3
        tier4 = self._env.tier4

        if tier3 is None or tier4 is None:
            return "Error: Environment tiers not initialized"

        # Build execution namespace with expected variables
        namespace = {
            # Agent ID and RCON client (for direct Lua calls)
            "agent_id": tier4.agent_id,
            "rcon_client": tier3.rcon_helper.rcon_client if tier3.rcon_helper else None,
            # Remote view for SQL queries
            "remote_view": tier4.remote_view,
            # Embodied actions
            "walking": tier4._movement if hasattr(tier4, "_movement") else None,
            "crafting": tier4._crafting if hasattr(tier4, "_crafting") else None,
            "research": tier4._research if hasattr(tier4, "_research") else None,
            "inventory": tier4._inventory if hasattr(tier4, "_inventory") else None,
            "reachable_view": tier4.reachable_view,
            # Standard library
            "json": __import__("json"),
        }

        # Capture output
        import io
        import sys

        stdout_capture = io.StringIO()
        old_stdout = sys.stdout

        try:
            sys.stdout = stdout_capture
            exec(code, namespace)
            output = stdout_capture.getvalue()
        except Exception as e:
            output = f"Error: {e}"
        finally:
            sys.stdout = old_stdout

        return output.strip()
