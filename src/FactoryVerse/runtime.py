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
    furnace = runtime.reachable.get_entity("stone-furnace")
    furnace.inspect()

Multi-agent: Each agent notebook creates its own runtime with dedicated UDP port.
Orchestration between agents is handled at a higher level (experiment runner).
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
    - runtime.mining - Mining actions
    - runtime.inventory - Inventory queries
    - runtime.reachable - Reachable entity queries
    - runtime.resources - Reachable resource queries
    - runtime.research - Research actions
    - runtime.remote_view - Map-wide entity queries (DuckDB)
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
        from FactoryVerse.agent.actions.walking import MovementAction
        from FactoryVerse.agent.actions.mining import MiningAction
        from FactoryVerse.agent.actions.crafting import CraftingAction
        from FactoryVerse.agent.actions.research import ResearchAction
        from FactoryVerse.agent.actions.inventory import AgentInventory
        from FactoryVerse.agent.actions.entity_operations import EntityOperationsAction
        from FactoryVerse.agent.actions.place_entity import PlacementAction
        from FactoryVerse.agent.actions.reachable import (
            ReachableEntities,
            ReachableResources,
        )

        # Wire up actions with their dependencies
        self._walking = MovementAction(self._rcon, self._listener)
        self._mining = MiningAction(self._rcon, self._listener)
        self._crafting = CraftingAction(self._rcon, self._listener)
        self._research = ResearchAction(self._rcon)
        self._inventory = AgentInventory(self._rcon)
        self._entity_ops = EntityOperationsAction(self._rcon)
        self._placement = PlacementAction(self._rcon)

        # Query objects
        self._reachable = ReachableEntities(self._rcon)
        self._resources = ReachableResources(self._rcon)

        # RemoteView - map-wide queries via DuckDB
        from FactoryVerse.agent.snapshot import RemoteView
        from FactoryVerse.infra.udp_dispatcher import get_udp_dispatcher

        # Detect snapshot dir if not provided
        snapshot_dir = config.snapshot_dir
        if snapshot_dir is None:
            snapshot_dir = self._detect_snapshot_dir()

        self._remote_view = RemoteView(
            snapshot_dir=snapshot_dir,
            db_path=config.db_path,
            udp_dispatcher=get_udp_dispatcher(),  # Shared dispatcher
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
        """
        if self._started:
            return
        await self._listener.start()

        # Load and start RemoteView sync
        self._remote_view.load()
        await self._remote_view.start()

        self._started = True

    async def stop(self) -> None:
        """Stop the runtime and cleanup resources."""
        if not self._started:
            return
        await self._remote_view.stop()
        await self._listener.stop()
        self._started = False

    # =========================================================================
    # Agent Affordances - these are what the LLM uses
    # =========================================================================

    @property
    def walking(self):
        """Movement actions.

        **For Agents**: Use to move around the map.

        - await walking.walk_to(position) - Walk to a position
        - await walking.walk_to(position, timeout=30) - With custom timeout

        Returns:
            MovementAction instance
        """
        return self._walking

    @property
    def mining(self):
        """Mining actions.

        **For Agents**: Use to mine resources and entities.

        - await mining.mine(entity) - Mine a resource or entity
        - await mining.mine_resource(position) - Mine at position

        Returns:
            MiningAction instance
        """
        return self._mining

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
    def reachable(self):
        """Reachable entity queries.

        **For Agents**: Use to find entities within interaction range.

        - reachable.get_entity(name) - Get first entity by name
        - reachable.get_entities(name) - Get all entities by name
        - reachable.get_entities() - Get all reachable entities

        Returns:
            ReachableEntities instance
        """
        return self._reachable

    @property
    def resources(self):
        """Reachable resource queries.

        **For Agents**: Use to find resources (ore, trees, rocks) in range.

        - resources.get_resource(name) - Get specific resource
        - resources.get_resources() - Get all reachable resources

        Returns:
            ReachableResources instance
        """
        return self._resources

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
    udp_port: int,
    *,
    snapshot_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> AgentRuntime:
    """Create a complete agent runtime.

    This is the main entry point for boilerplate code.

    Args:
        rcon_client: Connected RCON client
        agent_id: Agent identifier (e.g., "agent_1")
        udp_port: UDP port for async action notifications (each agent needs unique port)
        snapshot_dir: Optional path to snapshot directory for map_db
        db_path: Optional path to DuckDB database file

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
    config = RuntimeConfig(
        agent_id=agent_id,
        udp_port=udp_port,
        snapshot_dir=snapshot_dir,
        db_path=db_path,
    )
    return AgentRuntime(rcon_client, config)
