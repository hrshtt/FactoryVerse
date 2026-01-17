"""FactoryVerse Runtime Factory.

This module is the central factory for creating a complete agent runtime.
It wires up all infrastructure, actions, and DSL affordances with proper DI.

Usage in boilerplate:
    from FactoryVerse.runtime import create_runtime

    runtime = create_runtime(
        rcon_client=rcon_client,
        agent_id="agent_1",
        udp_port=None,  # Auto-allocates via dynamic port discovery
    )
    await runtime.start()

    # Now use the affordances
    await runtime.walking.to(MapPosition(10, 10))
    furnace = runtime.reachable_view.get_entity("stone-furnace")
    furnace.inspect()

Multi-agent: Each agent notebook creates its own runtime with dedicated UDP port.
Orchestration between agents is handled at a higher level.
"""

from typing import Optional, TYPE_CHECKING
from dataclasses import dataclass, field
from pathlib import Path

if TYPE_CHECKING:
    from factorio_rcon import RCONClient


@dataclass
class RuntimeConfig:
    """Configuration for creating an agent runtime.

    Separating config from factory allows:
    - Serialization/deserialization of config
    - Config validation before runtime creation
    - Multi-agent config management
    """

    agent_id: str
    udp_port: int
    snapshot_dir: Optional[Path] = None
    db_path: Optional[Path] = None

    # Advanced options
    async_action_timeout: float = 30.0  # seconds
    rcon_retry_count: int = 3


class AgentRuntime:
    """Complete agent runtime with all affordances.

    This is what the boilerplate gets - a single object with all capabilities.
    Each method/property is a properly DI-wired action or query object.

    **For Agents**: This object is created by the boilerplate. Access:
    - runtime.walking - Movement actions
    - runtime.crafting - Crafting actions
    - runtime.inventory - Inventory queries
    - runtime.reachable_view - Unified entity and resource queries
    - runtime.resources - Alias for reachable (backward compatibility)
    - runtime.research - Research actions
    - runtime.ghost_builder - Ghost building orchestration
    - runtime.remote_view - Map-wide entity queries (DuckDB)

    Note: Mining is done through resource objects, not a top-level action.
    Get a resource via runtime.reachable_view.get_resource(), then call resource.mine().
    """

    def __init__(
        self,
        rcon_client: "RCONClient",
        config: RuntimeConfig,
    ):
        """Initialize runtime with RCON client and config.

        Args:
            rcon_client: Connected RCON client
            config: Runtime configuration
        """
        self._rcon_client = rcon_client
        self._config = config
        self._started = False

        # Infrastructure - created immediately
        from FactoryVerse.agent.infra.rcon_handler import RconHandler
        from FactoryVerse.agent.infra.async_listener import AsyncActionListener

        self._rcon = RconHandler(rcon_client, config.agent_id)
        self._listener = AsyncActionListener(agent_port=config.udp_port)

        # Actions - created with proper DI
        from FactoryVerse.agent.embodied_actions.walking import MovementAction
        from FactoryVerse.agent.embodied_actions.mining import MiningAction
        from FactoryVerse.agent.embodied_actions.crafting import CraftingAction
        from FactoryVerse.agent.embodied_actions.research import ResearchAction
        from FactoryVerse.agent.embodied_actions.inventory import AgentInventory
        from FactoryVerse.agent.embodied_actions.entity_operations import EntityOperationsAction
        from FactoryVerse.agent.embodied_actions.place_entity import PlacementAction
        from FactoryVerse.agent.ghost_builder import GhostBuilderAction
        from FactoryVerse.agent.placement_hints import PlacementHints
        from FactoryVerse.agent.reachable_view import ReachableView

        # Wire up actions with their dependencies
        self._entity_ops = EntityOperationsAction(self._rcon)
        self._walking = MovementAction(self._rcon, self._listener)
        self._placement = PlacementAction(
            self._rcon, entity_ops=self._entity_ops, walking_action=self._walking
        )

        # Actions that need placement for item injection
        self._mining = MiningAction(self._rcon, self._listener, self._placement)
        self._crafting = CraftingAction(self._rcon, self._listener, self._placement)
        self._research = ResearchAction(self._rcon)
        self._inventory = AgentInventory(self._rcon, self._placement)

        # High-level orchestration actions
        self._ghost_builder = GhostBuilderAction(
            self._walking, self._placement, self._inventory
        )

        # Unified query object for both entities and resources
        # Single ReachableView instance handles all get_entity/get_entities/get_resource/get_resources calls
        self._reachable_view = ReachableView(
            self._rcon,
            self._entity_ops,
            self._placement,
            self._walking,
            self._mining,
        )

        # Placement hints - spatial reasoning for entity placement
        self._placement_hints = PlacementHints(self._rcon)

        # RemoteView - map-wide queries via DuckDB
        from FactoryVerse.agent.remote_view import RemoteView
        from FactoryVerse.infra.udp_dispatcher import get_udp_dispatcher

        # Detect snapshot dir if not provided
        snapshot_dir = config.snapshot_dir
        if snapshot_dir is None:
            snapshot_dir = self._detect_snapshot_dir()

        self._remote_view = RemoteView(
            snapshot_dir=snapshot_dir,
            entity_ops=self._entity_ops,
            place_ops=self._placement,
            walking_action=self._walking,
            mining_action=self._mining,
            db_path=config.db_path,
            udp_dispatcher=get_udp_dispatcher(),  # Shared dispatcher
            rcon_client=self._rcon_client,  # For bootstrap waiting
        )

    def _detect_snapshot_dir(self) -> Path:
        """Auto-detect snapshot directory from environment."""
        import os

        script_output = os.environ.get("FACTORIO_SCRIPT_OUTPUT_DIR")
        if script_output:
            return Path(script_output)
        # Default fallback
        return Path.home() / ".factorio" / "script-output"

    async def start(self) -> None:
        """Start the runtime (async listener, RemoteView sync, etc.).

        Must be called before using async actions like walking.
        Blocks until snapshot bootstrap is complete before loading data.
        """
        if self._started:
            return
        await self._listener.start()

        # Load and start RemoteView sync
        # This will wait for bootstrap to complete before loading
        await self._remote_view.load(wait_for_bootstrap=True)
        await self._remote_view.start()

        self._started = True

    async def stop(self) -> None:
        """Stop the runtime and cleanup resources."""
        if not self._started:
            return
        await self._remote_view.stop()
        await self._listener.stop()
        self._started = False

    async def get_notifications(self, timeout: float = 0.05) -> list:
        """Get pending game notifications from the UDP listener.

        Notifications are generated by the Lua mod for events like:
        - research_finished: A technology completed researching
        - research_started: A technology started researching
        - research_cancelled: Research was cancelled
        - research_queued: A technology was queued

        Args:
            timeout: Max time to wait for first notification (seconds).
                    Default is 0.05s for quick polling.

        Returns:
            List of notification payloads. Each notification has:
                - event_type: "notification"
                - notification_type: Type (e.g., "research_finished")
                - agent_id: Agent ID
                - tick: Game tick
                - data: Notification-specific data (e.g., technology name, unlocked recipes)

        Example:
            ```python
            notifications = await runtime.get_notifications()
            for notif in notifications:
                if notif['notification_type'] == 'research_finished':
                    tech = notif['data']['technology']
                    print(f"Research complete: {tech}")
            ```
        """
        return await self._listener.get_notifications(timeout=timeout)

    # =========================================================================
    # Agent Affordances - these are what the LLM uses
    # =========================================================================

    @property
    def walking(self):
        """Movement actions.

        **For Agents**: Use to move around the map.

        - await walking.walk_to(position) - Walk to a position
        - await walking.walk_to(position, timeout=30) - With custom timeout
        - walking.stop() - Stop current walking action

        Returns:
            MovementAction instance
        """
        return self._walking

    @property
    def crafting(self):
        """Crafting actions.

        **For Agents**: Use to craft items.

        - await crafting.craft(recipe, count) - Craft items
        - crafting.get_craftable() - Get what you can craft

        Returns:
            CraftingAction instance
        """
        return self._crafting

    @property
    def research(self):
        """Research actions.

        **For Agents**: Use to queue and manage research.

        - research.queue(technology) - Queue a technology
        - research.get_queue() - Get current research queue

        Returns:
            ResearchAction instance
        """
        return self._research

    @property
    def inventory(self):
        """Inventory queries and operations.

        **For Agents**: Use to check and manage inventory.

        - inventory.get_contents() - Get full inventory
        - inventory.get_item(name) - Get specific item stack
        - inventory.count(name) - Count of specific item

        Returns:
            AgentInventory instance
        """
        return self._inventory

    @property
    def reachable_view(self):
        """Unified reachable entity and resource queries.

        **For Agents**: Use to find entities and resources within interaction range.

        Entity queries:
        - reachable_view.get_entity(name) - Get first entity by name
        - reachable_view.get_entities(name) - Get all entities by name
        - reachable_view.get_entities() - Get all reachable entities
        - reachable_view.get_ghosts() - Get ghost entities

        Resource queries:
        - reachable_view.get_resource(name) - Get specific resource
        - reachable_view.get_resources() - Get all reachable resources

        Returns:
            ReachableView instance (unified interface for both entities and resources)
        """
        return self._reachable_view

    @property
    def resources(self):
        """Alias for reachable_view (backward compatibility).

        **For Agents**: This is the same object as 'reachable_view'.
        Use either reachable_view.get_resource() or resources.get_resource().

        Returns:
            ReachableView instance (same as reachable_view property)
        """
        return self._reachable_view

    @property
    def entity_ops(self):
        """Low-level entity operations.

        **For Agents**: Usually accessed through entity objects.
        Direct access for advanced use cases.

        Returns:
            EntityOperationsAction instance
        """
        return self._entity_ops

    @property
    def placement(self):
        """Entity placement operations.

        **For Agents**: Place and remove entities.

        - placement.place(name, position, direction)
        - placement.remove(entity)

        Returns:
            PlacementAction instance
        """
        return self._placement

    @property
    def ghost_builder(self):
        """Ghost building orchestration.

        **For Agents**: Build ghost entities by walking and placing.

        - await ghost_builder.build_ghosts(ghosts, count=10) - Build multiple ghosts
        - await ghost_builder.build_ghost(ghost) - Build a single ghost
        - Automatically walks to each ghost and places the entity

        Returns:
            GhostBuilderAction instance
        """
        return self._ghost_builder

    @property
    def remote_view(self):
        """Map-wide entity queries via DuckDB.

        **For Agents**: Use to find entities anywhere on the map,
        not just within interaction range.

        - remote_view.get_entities(sql) - Query entities by SQL
        - remote_view.get_ghosts(sql) - Query ghost entities
        - remote_view.query(sql) - Raw SQL queries

        Returns:
            RemoteView instance
        """
        return self._remote_view

    @property
    def placement_hints(self):
        """Spatial reasoning engine for entity placement.

        **For Agents**: Use to plan and validate entity placements before committing.

        Three-tier placement flow:
        1. DRY RUN: placement_hints.get_placement_line() -> GhostPlan (validated)
        2. PLACE: Use plan.positions to place ghosts or directly with ghost_builder.build_plan(plan)
        3. BUILD: ghost.build() converts ghosts to real entities

        - placement_hints.get_placement_line(entity, start, end) - Plan a line of entities
        - placement_hints.get_connection_positions(source, target, type) - Find valid connection points
        - plan.valid - Check if GhostPlan is valid
        - plan.validate(placement_hints.validator) - Re-validate after map changes

        Returns:
            PlacementHints instance
        """
        return self._placement_hints

    @property
    def agent_id(self) -> str:
        """The agent's ID."""
        return self._config.agent_id

    @property
    def rcon(self):
        """Access to RconHandler for advanced operations."""
        return self._rcon

    def __repr__(self) -> str:
        status = "running" if self._started else "stopped"
        return f"AgentRuntime(agent_id='{self._config.agent_id}', udp_port={self._config.udp_port}, status={status})"


def create_runtime(
    rcon_client: "RCONClient",
    agent_id: str,
    udp_port: Optional[int] = None,
    *,
    snapshot_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
    server_index: Optional[int] = None,
) -> AgentRuntime:
    """Create a complete agent runtime.

    This is the main entry point for boilerplate code.

    Args:
        rcon_client: Connected RCON client
        agent_id: Agent identifier (e.g., "agent_1")
        udp_port: UDP port for async action notifications (each agent needs unique port).
                  If None, uses deterministic allocation based on agent_id and server_index.
        snapshot_dir: Optional path to snapshot directory for map_db
        db_path: Optional path to DuckDB database file
        server_index: Optional server index for deterministic port allocation.
                      If None and udp_port is None, uses dynamic port discovery.

    Returns:
        Configured AgentRuntime ready to use (call .start() before async operations)

    Example:
        ```python
        from factorio_rcon import RCONClient
        from FactoryVerse.runtime import create_runtime

        rcon = RCONClient("localhost", 27015, "password")
        runtime = create_runtime(rcon, "agent_1")  # udp_port auto-allocated
        await runtime.start()

        # Now use the runtime
        await runtime.walking.walk_to(MapPosition(10, 10))
        ```
    """
    from FactoryVerse.config import get_config
    
    # Allocate UDP port if not provided
    if udp_port is None:
        config = get_config()
        
        # Try deterministic allocation if server_index is provided
        if server_index is not None:
            # Extract agent index from agent_id (e.g., "agent_1" -> 1)
            try:
                agent_index = int(agent_id.split("_")[1]) - 1  # Convert to 0-based
                udp_port = config.get_agent_port(agent_index, server_index=server_index)
            except (ValueError, IndexError):
                # Fall back to dynamic allocation if agent_id format is unexpected
                from FactoryVerse.utils.port_utils import find_free_udp_port
                udp_port = find_free_udp_port(
                    start_port=config.agent_port_base,
                    max_attempts=200,
                    host=config.rcon_host,
                )
        else:
            # Dynamic port discovery (may not match Docker port mappings)
            from FactoryVerse.utils.port_utils import find_free_udp_port
            udp_port = find_free_udp_port(
                start_port=config.agent_port_base,
                max_attempts=200,
                host=config.rcon_host,
            )
    
    config = RuntimeConfig(
        agent_id=agent_id,
        udp_port=udp_port,
        snapshot_dir=snapshot_dir,
        db_path=db_path,
    )
    return AgentRuntime(rcon_client, config)
