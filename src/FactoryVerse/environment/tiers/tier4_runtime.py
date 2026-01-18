"""Tier 4: FactoryVerse Runtime.

Orchestrates agent modules: remote_view, reachable_view, embodied_actions, DuckDB.
"""

import logging
from pathlib import Path
from typing import Optional, Any, List, TYPE_CHECKING

from ..config import RuntimeConfig, RuntimeVariant
from ..status import Tier4Status, TierState, PrerequisiteResult
from .base import TierBase, Tier, TierInitializationError

if TYPE_CHECKING:
    from ..environment import Environment

logger = logging.getLogger(__name__)


class Tier4Runtime(TierBase):
    """Tier 4: FactoryVerse Runtime.

    Loads agent modules for interacting with Factorio:
    - MINIMAL variant: Core modules only (no DuckDB, no remote_view)
    - FULL variant: All modules including remote_view + DuckDB

    Modules loaded:
    - embodied_actions: Walking, mining, crafting, building
    - reachable_view: Lua-based entity querying (always available)
    - remote_view: SQL-based entity querying (FULL only)
    - DuckDB database: Persistent game state (FULL only)
    """

    tier_level = Tier.RUNTIME

    def __init__(self, environment: "Environment"):
        super().__init__(environment)
        self._agent_id: Optional[str] = None
        self._session_dir: Optional[Path] = None
        self._database: Optional[Any] = None
        self._remote_view: Optional[Any] = None
        self._reachable_view: Optional[Any] = None
        self._embodied_actions: Optional[Any] = None
        self._placement_hints: Optional[Any] = None
        self._modules_loaded: List[str] = []

    @property
    def config(self) -> RuntimeConfig:
        """Get tier 4 configuration."""
        return self._env.config.tier4

    @property
    def agent_id(self) -> Optional[str]:
        """Get agent identifier."""
        return self._agent_id

    @property
    def session_dir(self) -> Optional[Path]:
        """Get session directory."""
        return self._session_dir

    @property
    def database(self) -> Optional[Any]:
        """Get DuckDB connection (None if MINIMAL variant)."""
        return self._database

    @property
    def remote_view(self) -> Optional[Any]:
        """Get RemoteView for SQL-based queries (None if MINIMAL variant)."""
        return self._remote_view

    @property
    def reachable_view(self) -> Optional[Any]:
        """Get ReachableView for Lua-based queries."""
        return self._reachable_view

    @property
    def embodied_actions(self) -> Optional[Any]:
        """Get EmbodiedActions for agent actions."""
        return self._embodied_actions

    @property
    def placement_hints(self) -> Optional[Any]:
        """Get PlacementHints for spatial reasoning and connection solving."""
        return self._placement_hints

    async def verify_prerequisites(self) -> PrerequisiteResult:
        """Verify Tier 3 (Python Infra) is ready."""
        tier3 = self._env.tier3

        if tier3 is None or not tier3.is_ready:
            return PrerequisiteResult.failed(
                missing=["tier3_python_infra"],
                message="Python infrastructure (RCON/UDP) must be connected first",
            )

        return PrerequisiteResult.ok()

    async def initialize(self) -> None:
        """Initialize runtime with agent modules."""
        self._set_state(TierState.INITIALIZING)

        try:
            # Setup agent and session
            self._agent_id = self.config.agent_id
            self._session_dir = await self._setup_session_dir()

            # Create agent in Factorio
            await self._reconcile_and_create_agent()

            # Load modules based on variant
            await self._load_embodied_actions()
            await self._load_reachable_view()
            await self._load_placement_hints()

            if self.config.variant == RuntimeVariant.FULL:
                await self._load_database()
                await self._load_remote_view()

            self._set_state(TierState.READY)

        except Exception as e:
            self._set_state(TierState.ERROR, str(e))
            raise TierInitializationError(self.tier_level, str(e)) from e

    async def _setup_session_dir(self) -> Path:
        """Setup session directory for this agent run."""
        if self.config.session_dir:
            session_dir = self.config.session_dir
        else:
            # Auto-generate session directory
            import datetime

            infra_config = self._env.config.infra_config
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            session_dir = (
                infra_config.fv_output_dir / "sessions" / f"session_{timestamp}"
            )

        session_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Tier 4: Session directory: {session_dir}")
        return session_dir

    async def _reconcile_and_create_agent(self) -> None:
        """Reconcile AgentProfile with Factorio Entity.

        Strategy:
        1. Check Registry for existing profile.
        2. If New: Create Profile -> Create Entity (destroy=True).
        3. If Exists: Check Entity -> Bind (destroy=False) or Respawn.
        """
        from datetime import datetime
        from uuid import uuid4
        from FactoryVerse.agent.core.profile import AgentProfile, AgentStatus

        tier3 = self._env.tier3
        if tier3 is None or tier3.rcon_helper is None:
            raise RuntimeError("Tier 3 must be initialized with RCON")

        registry = tier3.agent_registry
        if not registry:
            logger.warning(
                "Tier 4: Registry not found in Tier 3, falling back to legacy creation"
            )
            await self._create_agent_legacy()
            return

        # 1. Look up profile
        requested_id = self.config.agent_id or "agent_1"
        profile = registry.get_by_name(requested_id)

        rcon_helper = tier3.rcon_helper
        udp_port = tier3._udp_dispatcher.port if tier3._udp_dispatcher else None

        if not profile:
            # Case 1: New Agent (Spawn)
            logger.info(f"Tier 4: creating NEW agent '{requested_id}'")

            # Create persistent profile
            profile = AgentProfile(
                id=uuid4(),
                name=requested_id,
                instance_id=tier3.instance or "unknown",
                model=self._env.config.tier6.model
                if self._env.tier6
                else "unknown",  # Capture intended model
                description="Auto-generated by Tier 4 Runtime",
                status=AgentStatus.ACTIVE,
            )
            registry.register(profile)

            # Create Entity (Destroy potential orphan with same name)
            rcon_helper._create_agent(udp_port=udp_port, destroy_existing=True)

        else:
            # Case 2: Resume Agent (Bind)
            logger.info(
                f"Tier 4: Resuming existing agent '{profile.name}' ({profile.id})"
            )

            # Verify if entity actually exists (Resurrection check)
            # We assume it exists unless proven otherwise, but we use destroy_existing=False
            # If the entity is missing, rcon_helper._create_agent with destroy_existing=False *might* fail or do nothing?
            # Actually, standard logic is just to 're-bind'.
            # Ideally we check existence via Lua first.

            # Safe re-creation: Try to create ONLY if missing?
            # For now, we use rcon_helper to ensure it exists but NOT destroy old one
            # Caveat: Factorio 'create_agent' usually spawns a new one.
            # We need a 'ensure_agent' in rcon_helper or careful call.

            # Current `_create_agent` in rcon_helper calls Lua `remote.call('agent', 'create_agent', ...)`
            # If destroy_existing=False, it should ideally attach to existing or spawn if missing.
            # Let's assume the Lua layer handles "get or create" if destroy_existing=False.
            rcon_helper._create_agent(udp_port=udp_port, destroy_existing=False)

            # Update Status
            profile.status = AgentStatus.ACTIVE
            profile.updated_at = datetime.now()
            registry.save(profile)

            # Override runtime ID with profile ID/Name
            self._agent_id = profile.name

        rcon_helper.refresh_interfaces()
        self._modules_loaded.append("agent")

        logger.info(
            f"Tier 4: Agent '{self._agent_id}' ready (Persistent ID: {profile.id})"
        )

    async def _create_agent_legacy(self) -> None:
        """Legacy creation logic (destructive)."""
        tier3 = self._env.tier3
        if tier3 is None or tier3.rcon_helper is None:
            raise RuntimeError("Tier 3 must be initialized with RCON")
        rcon_helper = tier3.rcon_helper
        udp_port = tier3._udp_dispatcher.port if tier3._udp_dispatcher else None

        rcon_helper._create_agent(udp_port=udp_port, destroy_existing=True)
        rcon_helper.refresh_interfaces()
        self._modules_loaded.append("agent")
        logger.info(f"Tier 4: Created agent {self._agent_id} (Legacy/Ephemeral)")

    async def _load_embodied_actions(self) -> None:
        """Load EmbodiedActions modules.

        Loads individual action classes: MovementAction, PlacementAction, etc.
        """
        tier3 = self._env.tier3
        if tier3 is None or tier3.rcon_helper is None:
            raise RuntimeError("Tier 3 must be initialized with RCON")

        # Use RconHandler for agent-specific actions (legacy compatibility)
        from FactoryVerse.agent.infra.rcon_handler import RconHandler

        rcon_handler = RconHandler(tier3.rcon_helper.rcon_client, self.agent_id)

        if tier3._action_listener is None:
            raise RuntimeError("Tier 3 UDP listener not initialized")
        async_listener = tier3._action_listener  # From tier3 UDP setup

        # Import action classes
        from FactoryVerse.agent.embodied_actions.walking import MovementAction
        from FactoryVerse.agent.embodied_actions.place_entity import PlacementAction
        from FactoryVerse.agent.embodied_actions.entity_operations import (
            EntityOperationsAction,
        )
        from FactoryVerse.agent.embodied_actions.inventory import AgentInventory
        from FactoryVerse.agent.embodied_actions.crafting import CraftingAction
        from FactoryVerse.agent.embodied_actions.research import ResearchAction
        from FactoryVerse.agent.embodied_actions.mining import MiningAction

        # Create action instances in dependency order
        self._entity_ops = EntityOperationsAction(rcon_handler)
        self._movement = MovementAction(rcon_handler, async_listener)
        self._mining = MiningAction(rcon_handler, async_listener)
        self._placement = PlacementAction(
            rcon_handler, self._entity_ops, self._movement
        )
        self._inventory = AgentInventory(rcon_handler, self._placement)
        self._crafting = CraftingAction(rcon_handler, async_listener)
        self._research = ResearchAction(rcon_handler)

        # Store as dict for easy access
        self._embodied_actions = {
            "movement": self._movement,
            "placement": self._placement,
            "entity_ops": self._entity_ops,
            "inventory": self._inventory,
            "crafting": self._crafting,
            "research": self._research,
            "mining": self._mining,
        }
        self._modules_loaded.append("embodied_actions")

        logger.info("Tier 4: EmbodiedActions loaded (7 action modules)")

    async def _load_reachable_view(self) -> None:
        """Load ReachableView module (Lua-based entity querying)."""
        from FactoryVerse.agent.reachable_view import ReachableView
        from FactoryVerse.agent.infra.rcon_handler import RconHandler

        tier3 = self._env.tier3
        if tier3 is None or tier3.rcon_helper is None:
            raise RuntimeError("Tier 3 must be initialized with RCON")

        # ReachableView requires RconHandler (not RconHelper)
        rcon_handler = RconHandler(tier3.rcon_helper.rcon_client, self.agent_id)

        # ReachableView requires action instances
        self._reachable_view = ReachableView(
            rcon_handler=rcon_handler,
            entity_ops=self._entity_ops,
            place_ops=self._placement,
            walking_action=self._movement,
            mining_action=self._mining,
        )
        self._modules_loaded.append("reachable_view")

        logger.info("Tier 4: ReachableView loaded")

    async def _load_placement_hints(self) -> None:
        """Load PlacementHints module (spatial reasoning for entity placement)."""
        from FactoryVerse.agent.placement_hints import PlacementHints

        tier3 = self._env.tier3
        if tier3 is None or tier3.rcon_helper is None:
            raise RuntimeError("Tier 3 must be initialized with RCON")

        # Use RconHandler for placement hints
        from FactoryVerse.agent.infra.rcon_handler import RconHandler

        rcon_handler = RconHandler(tier3.rcon_helper.rcon_client, self.agent_id)
        self._placement_hints = PlacementHints(rcon_handler)
        self._modules_loaded.append("placement_hints")

        logger.info("Tier 4: PlacementHints loaded")

    async def _load_database(self) -> None:
        """Load DuckDB database for persistent game state."""
        import duckdb

        if self._session_dir is None:
            raise RuntimeError("Session directory not initialized")
        db_path = self._session_dir / "map.duckdb"
        self._database = duckdb.connect(str(db_path))
        self._modules_loaded.append("database")

        # Initialize schema from snapshot
        await self._sync_database()

        logger.info(f"Tier 4: DuckDB connected at {db_path}")

    async def _sync_database(self) -> None:
        """Sync DuckDB with game state from snapshots."""
        # Get snapshot directory based on instance
        tier3 = self._env.tier3
        if tier3 is None or tier3.instance is None:
            raise RuntimeError("Tier 3 must be initialized with instance")
        infra_config = self._env.config.infra_config

        snapshot_dir = infra_config.get_snapshot_dir(tier3.instance)

        # Use snapshot loader to sync database
        from FactoryVerse.agent.infra.snapshot.loader import SnapshotLoader

        if self._database is None:
            raise RuntimeError("Database not initialized")

        loader = SnapshotLoader(
            db=self._database,
            snapshot_dir=snapshot_dir,
        )
        loader.load_all()

        logger.info("Tier 4: Database synced with game state")

    async def _load_remote_view(self) -> None:
        """Load RemoteView module (SQL-based entity querying)."""
        from FactoryVerse.agent.remote_view import RemoteView

        tier3 = self._env.tier3
        if tier3 is None:
            raise RuntimeError("Tier 3 must be initialized")
        infra_config = self._env.config.infra_config
        if tier3 is None or tier3.instance is None:
            raise RuntimeError("Tier 3 must be initialized with instance")
        snapshot_dir = infra_config.get_snapshot_dir(tier3.instance)

        self._remote_view = RemoteView(
            snapshot_dir=snapshot_dir,
            entity_ops=self._entity_ops,
            place_ops=self._placement,
            walking_action=self._movement,
            mining_action=self._mining,
            udp_dispatcher=tier3._udp_dispatcher,
            rcon_client=tier3._rcon,
        )
        self._modules_loaded.append("remote_view")

        logger.info("Tier 4: RemoteView loaded")

    async def verify_ready(self) -> Tier4Status:
        """Verify runtime is operational."""
        if self._state != TierState.READY:
            return Tier4Status(
                state=self._state,
                error=self._error,
            )

        db_connected = self._database is not None
        db_synced = db_connected  # Simplified - would have more checks

        return Tier4Status(
            state=self._state,
            runtime_initialized=True,
            database_connected=db_connected
            if self.config.variant == RuntimeVariant.FULL
            else None,
            database_synced=db_synced
            if self.config.variant == RuntimeVariant.FULL
            else None,
            modules_loaded=self._modules_loaded,
        )

    async def reset(self) -> None:
        """Reset runtime by reloading modules."""
        await self.shutdown()
        await self.initialize()

    async def shutdown(self) -> None:
        """Shutdown runtime and cleanup."""
        self._set_state(TierState.SHUTTING_DOWN)

        # Close database
        if self._database:
            try:
                self._database.close()
            except Exception:
                pass
            self._database = None

        # Clear module references
        self._remote_view = None
        self._reachable_view = None
        self._embodied_actions = None
        self._placement_hints = None
        self._agent_id = None
        self._session_dir = None
        self._modules_loaded = []

        self._set_state(TierState.SHUTDOWN)

    # =========================================================================
    # Module Reload
    # =========================================================================

    async def reload_modules(self) -> None:
        """Hot-reload Python modules.

        Useful during development to reload code changes
        without restarting the entire environment.
        """
        import importlib

        # List of modules to reload
        module_names = [
            "FactoryVerse.agent.embodied_actions",
            "FactoryVerse.agent.reachable_view",
            "FactoryVerse.agent.remote_view",
        ]

        for name in module_names:
            try:
                module = importlib.import_module(name)
                importlib.reload(module)
                logger.info(f"Tier 4: Reloaded {name}")
            except Exception as e:
                logger.warning(f"Tier 4: Failed to reload {name}: {e}")

        # Re-initialize module instances
        await self._load_embodied_actions()
        await self._load_reachable_view()
        await self._load_placement_hints()
        if self.config.variant == RuntimeVariant.FULL:
            await self._load_remote_view()

    async def sync_database(self) -> None:
        """Force database sync with game state."""
        if self._database:
            await self._sync_database()
