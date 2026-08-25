"""Environment - The canonical orchestrator for FactoryVerse.

Provides tiered composition of the complete runtime stack.
"""

import logging
from typing import Optional
from contextlib import asynccontextmanager

from .config import (
    EnvironmentConfig,
    RuntimeVariant,
    InteractionMode,
)
from .status import EnvironmentStatus
from .tiers.base import Tier, TierPrerequisiteError, TierInitializationError
from .tiers.tier1_factorio import Tier1Factorio
from .tiers.tier2_settings import Tier2Settings
from .tiers.tier3_python import Tier3Python
from .tiers.tier4_runtime import Tier4Runtime
from .tiers.tier5_specification import Tier5Specification
from .tiers.tier6_interaction import Tier6Interaction
from .orchestrator import Orchestrator

logger = logging.getLogger(__name__)


class Environment:
    """The canonical orchestrator for FactoryVerse.

    Composes and coordinates the complete runtime stack through 6 tiers:
    1. Factorio Infra - Client/Server with mods
    2. Settings - Scenario/save loading
    3. Python Infra - RCON + UDP connections
    4. Runtime - Agent modules
    5. Specification - System prompt
    6. Interaction - LLM orchestration

    Example:
        >>> async with Environment.for_agent(mode="autonomous") as env:
        ...     await env.tier6.run_loop()
    """

    def __init__(self, config: Optional[EnvironmentConfig] = None):
        """Initialize Environment with configuration.

        Args:
            config: Environment configuration (uses defaults if None)
        """
        self._config = config or EnvironmentConfig()

        # Initialize tier instances (not yet started)
        self._tier1: Optional[Tier1Factorio] = None
        self._tier2: Optional[Tier2Settings] = None
        self._tier3: Optional[Tier3Python] = None
        self._tier4: Optional[Tier4Runtime] = None
        self._tier5: Optional[Tier5Specification] = None
        self._tier6: Optional[Tier6Interaction] = None

        self._initialized_up_to: Optional[Tier] = None
        self._orchestrator: Optional[Orchestrator] = None

    @property
    def config(self) -> EnvironmentConfig:
        """Get environment configuration."""
        return self._config

    @property
    def tier1(self) -> Optional[Tier1Factorio]:
        """Tier 1: Factorio Infrastructure."""
        return self._tier1

    @property
    def tier2(self) -> Optional[Tier2Settings]:
        """Tier 2: Factorio Settings."""
        return self._tier2

    @property
    def tier3(self) -> Optional[Tier3Python]:
        """Tier 3: Python Infrastructure."""
        return self._tier3

    @property
    def tier4(self) -> Optional[Tier4Runtime]:
        """Tier 4: Runtime."""
        return self._tier4

    @property
    def tier5(self) -> Optional[Tier5Specification]:
        """Tier 5: Specification."""
        return self._tier5

    @property
    def tier6(self) -> Optional[Tier6Interaction]:
        """Tier 6: Interaction."""
        return self._tier6

    @property
    def orchestrator(self) -> Orchestrator:
        """High-level run orchestration.

        Provides convenient methods for common run patterns:
        - run_task: Run a task with verification
        - run_freeplay: Run open-ended exploration
        - run_batch: Run multiple jobs on available cells

        Example:
            >>> result = await env.orchestrator.run_task(
            ...     task="iron_plate_throughput",
            ...     model="claude-3-opus",
            ... )
        """
        if self._orchestrator is None:
            self._orchestrator = Orchestrator(self)
        return self._orchestrator

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    async def initialize(self, up_to: Tier = Tier.INTERACTION) -> None:
        """Initialize environment up to specified tier.

        Args:
            up_to: Highest tier to initialize (inclusive)

        Raises:
            TierPrerequisiteError: If prerequisites fail
            TierInitializationError: If tier initialization fails
        """
        # Sync agent_id between tier3 and tier4 configs
        # This ensures the UDP port tier3 listens on matches what tier4 tells Lua
        self._sync_agent_id()

        tier_classes = [
            (Tier.FACTORIO_INFRA, Tier1Factorio, "_tier1"),
            (Tier.SETTINGS, Tier2Settings, "_tier2"),
            (Tier.PYTHON_INFRA, Tier3Python, "_tier3"),
            (Tier.RUNTIME, Tier4Runtime, "_tier4"),
            (Tier.SPECIFICATION, Tier5Specification, "_tier5"),
            (Tier.INTERACTION, Tier6Interaction, "_tier6"),
        ]

        for tier_level, tier_class, attr_name in tier_classes:
            if tier_level > up_to:
                break

            # Create tier instance if not exists
            tier_instance = getattr(self, attr_name)
            if tier_instance is None:
                tier_instance = tier_class(self)
                setattr(self, attr_name, tier_instance)

            # Skip if already ready
            if tier_instance.is_ready:
                continue

            # Verify prerequisites
            prereq_result = await tier_instance.verify_prerequisites()
            if not prereq_result.satisfied:
                raise TierPrerequisiteError(
                    tier_level,
                    prereq_result.missing,
                    prereq_result.message,
                )

            # Initialize tier
            logger.info(f"Environment: Initializing {tier_level.name}...")
            await tier_instance.initialize()

            # Verify ready
            status = await tier_instance.verify_ready()
            if not status.is_ready:
                raise TierInitializationError(
                    tier_level, f"Tier verification failed: {status.error}"
                )

            self._initialized_up_to = tier_level
            logger.info(f"Environment: {tier_level.name} ready")

    async def shutdown(self) -> None:
        """Shutdown all tiers in reverse order."""
        tiers = [
            self._tier6,
            self._tier5,
            self._tier4,
            self._tier3,
            self._tier2,
            self._tier1,
        ]

        for tier in tiers:
            if tier is not None:
                try:
                    await tier.shutdown()
                except Exception as e:
                    logger.warning(f"Error shutting down {tier.tier_level.name}: {e}")

        self._initialized_up_to = None
        logger.info("Environment: Shutdown complete")

    async def reset(self, from_tier: Tier = Tier.RUNTIME) -> None:
        """Reset from specified tier upward.

        Lower tiers remain stable, higher tiers are reset.

        Args:
            from_tier: Tier to reset from (inclusive of all higher tiers)
        """
        tiers = [
            (Tier.INTERACTION, self._tier6),
            (Tier.SPECIFICATION, self._tier5),
            (Tier.RUNTIME, self._tier4),
            (Tier.PYTHON_INFRA, self._tier3),
            (Tier.SETTINGS, self._tier2),
            (Tier.FACTORIO_INFRA, self._tier1),
        ]

        # Reset tiers >= from_tier in reverse order
        for tier_level, tier in tiers:
            if tier_level >= from_tier and tier is not None:
                logger.info(f"Environment: Resetting {tier_level.name}...")
                await tier.reset()

        logger.info(f"Environment: Reset from {from_tier.name} complete")

    async def status(self) -> EnvironmentStatus:
        """Get status of all tiers."""
        statuses = EnvironmentStatus()

        if self._tier1:
            statuses.tier1 = await self._tier1.verify_ready()
        if self._tier2:
            statuses.tier2 = await self._tier2.verify_ready()
        if self._tier3:
            statuses.tier3 = await self._tier3.verify_ready()
        if self._tier4:
            statuses.tier4 = await self._tier4.verify_ready()
        if self._tier5:
            statuses.tier5 = await self._tier5.verify_ready()
        if self._tier6:
            statuses.tier6 = await self._tier6.verify_ready()

        return statuses

    # =========================================================================
    # Configuration Helpers
    # =========================================================================

    def _sync_agent_id(self) -> None:
        """Synchronize agent_id between tier3 and tier4 configs.

        This ensures the UDP port tier3 listens on matches what tier4 tells Lua.
        Priority: tier4.agent_id (the runtime agent) wins if set differently.
        """
        tier3_agent_id = self._config.tier3.agent_id
        tier4_agent_id = self._config.tier4.agent_id

        if tier3_agent_id != tier4_agent_id:
            # tier4 is the "real" agent, sync tier3 to match
            logger.warning(
                f"Environment: agent_id mismatch - tier3='{tier3_agent_id}', tier4='{tier4_agent_id}'. "
                f"Syncing tier3 to match tier4."
            )
            # Create a new PythonConfig with the correct agent_id
            # (pydantic models are immutable by default, so we need to recreate)
            from .config import PythonConfig
            tier3_dict = self._config.tier3.model_dump()
            tier3_dict["agent_id"] = tier4_agent_id
            self._config.tier3 = PythonConfig(**tier3_dict)
            logger.info(f"Environment: tier3.agent_id synced to '{tier4_agent_id}'")

    # =========================================================================
    # Context Manager
    # =========================================================================

    async def __aenter__(self) -> "Environment":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.shutdown()

    # =========================================================================
    # Convenience Constructors
    # =========================================================================

    @classmethod
    def for_agent(
        cls,
        mode: str = "autonomous",
        provider: str = "prime_intellect",
        model: Optional[str] = None,
        scenario: str = "freeplay",
        instance: str = "client",
        **kwargs,
    ) -> "Environment":
        """Create an environment for a full agent run (see EnvironmentConfig.for_run)."""
        config = EnvironmentConfig.for_run(
            instance=instance,
            scenario=scenario,
            provider=provider,
            model=model,
            interactive=(mode == "assisted"),
            **kwargs,
        )
        return cls(config=config)

    @classmethod
    def for_testing(
        cls,
        scenario: str = "test-ground",
        variant: str = "minimal",
    ) -> "Environment":
        """Create environment for testing.

        Args:
            scenario: Scenario to load
            variant: Runtime variant (minimal, full)
        """
        config = EnvironmentConfig.for_testing(
            scenario=scenario,
            variant=RuntimeVariant(variant),
        )
        return cls(config=config)

    @classmethod
    def for_notebook(
        cls,
        instance: str = "client",
        variant: str = "full",
    ) -> "Environment":
        """Create environment for Jupyter notebook exploration.

        Args:
            instance: Instance to connect to
            variant: Runtime variant
        """
        from .config import PythonConfig, RuntimeConfig

        config = EnvironmentConfig(
            tier3=PythonConfig(instance=instance),
            tier4=RuntimeConfig(variant=RuntimeVariant(variant)),
        )
        return cls(config=config)


# Convenience function for inline async context
@asynccontextmanager
async def create_environment(
    up_to: Tier = Tier.RUNTIME,
    **config_kwargs,
):
    """Create and initialize environment as async context manager.

    Args:
        up_to: Tier to initialize up to
        **config_kwargs: Passed to EnvironmentConfig

    Yields:
        Initialized Environment

    Example:
        >>> async with create_environment(up_to=Tier.RUNTIME) as env:
        ...     result = env.tier3.execute_lua("return game.tick")
    """
    config = EnvironmentConfig(**config_kwargs)
    env = Environment(config=config)

    try:
        await env.initialize(up_to=up_to)
        yield env
    finally:
        await env.shutdown()
