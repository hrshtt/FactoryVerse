from FactoryVerse.dsl.entity.base import ReachableEntity, GhostEntity
from FactoryVerse.dsl.item.base import ItemStack
from FactoryVerse.dsl.types import MapPosition, BoundingBox, Position, Direction
from FactoryVerse.dsl.agent import PlayingFactory, _playing_factory
from FactoryVerse.dsl.recipe.base import Recipes

from typing import List, Optional, Dict, Any, Union, Literal, TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    from FactoryVerse.dsl.entity.remote_view_entity import RemoteViewEntity
import json
import logging
import sys
import asyncio
from contextlib import contextmanager
from factorio_rcon import RCONClient as RconClient


def _get_factory() -> PlayingFactory:
    """Get the current playing factory context."""
    factory = _playing_factory.get()
    if factory is None:
        raise RuntimeError(
            "No active gameplay session. "
            "Use 'with playing_factorio(rcon, agent_id):' to enable operations."
        )
    return factory


# Top-level action accessors - available in DSL context
class _WalkingAccessor:
    """Top-level walking action accessor."""
    
    def __repr__(self) -> str:
        return """WalkingAffordance
  Methods:
    - to(position, strict_goal?, options?, timeout?) - Move agent to a position (async)
    - cancel() - Cancel current walking action
  Usage: await walking.to(MapPosition(x, y))"""
    
    async def to(self, position: MapPosition, strict_goal: bool = False, options: Optional[dict] = None, timeout: Optional[int] = None):
        """Walk to a position (async/await)."""
        return await _get_factory().walking.to(position, strict_goal, options, timeout)
    
    def cancel(self):
        """Cancel current walking action."""
        return _get_factory().walking.cancel()


class _CraftingAccessor:
    """Top-level crafting action accessor."""
    
    def __repr__(self) -> str:
        return """CraftingAffordance
  Methods:
    - craft(recipe, count?, timeout?) - Craft items (async)
    - enqueue(recipe, count?) - Enqueue recipe for crafting
    - dequeue(recipe, count?) - Cancel queued crafting
    - status() - Get current crafting status
    - get_recipes(enabled_only?, category?) - Get available recipes
  Usage: await crafting.craft('iron-plate', count=10)"""
    
    async def craft(self, recipe: str, count: int = 1, timeout: Optional[int] = None):
        """Craft a recipe (async/await)."""
        return await _get_factory().crafting.craft(recipe, count, timeout)
    
    def enqueue(self, recipe: str, count: int = 1):
        """Enqueue a recipe for crafting."""
        return _get_factory().crafting.enqueue(recipe, count)
    
    def dequeue(self, recipe: str, count: Optional[int] = None):
        """Cancel queued crafting."""
        return _get_factory().crafting.dequeue(recipe, count)
    
    def status(self):
        """Get current crafting status."""
        return _get_factory().crafting.status()
    
    def get_recipes(self, enabled_only: bool = True, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get available recipes for the agent's force.
        
        Args:
            enabled_only: If True, only return enabled recipes (default: True)
            category: Optional filter by recipe category (e.g., "crafting", "smelting")
        
        Returns:
            List of recipe dictionaries with name, category, energy, and ingredients
        """
        # The Lua implementation already filters to enabled recipes only
        # So enabled_only=True is the default behavior, enabled_only=False is not supported
        if not enabled_only:
            # For now, we only support enabled recipes (Lua limitation)
            # Could be extended in the future if needed
            pass
        
        result = _get_factory().get_recipes(category=category)
        return json.loads(result)


class _ResearchAccessor:
    """Top-level research action accessor."""
    
    def __repr__(self) -> str:
        return """ResearchAffordance
  Methods:
    - enqueue(technology) - Start researching a technology
    - dequeue() - Cancel current research
    - status() - Get current research status
    - get_technologies(researched_only?, only_available?) - Get technologies
  Usage: research.enqueue('automation')"""
    
    def enqueue(self, technology: str):
        """Start researching a technology."""
        return _get_factory().research.enqueue(technology)
    
    def dequeue(self):
        """Cancel current research."""
        return _get_factory().research.dequeue()
    
    def status(self):
        """Get current research status."""
        return _get_factory().research.status()
    
    def get_technologies(self, researched_only: bool = False, only_available: bool = False) -> List[Dict[str, Any]]:
        """Get technologies for the agent's force.
        
        Args:
            researched_only: If True, only return already researched technologies
            only_available: If True, only return technologies that can be researched now (prerequisites met)
        
        Returns:
            List of technology dictionaries with name, researched, enabled, prerequisites, etc.
        """
        # Get all or available technologies from Lua
        result = _get_factory().get_technologies(only_available=only_available)
        technologies = json.loads(result)
        
        # Apply client-side filtering for researched_only if needed
        if researched_only:
            technologies = [tech for tech in technologies if tech.get('researched', False)]
        
        return technologies


class _InventoryAccessor:
    """Top-level inventory helper accessor.
    
    Provides access to AgentInventory methods for querying and shaping items.
    """
    
    def __repr__(self) -> str:
        return """InventoryAffordance
  Properties:
    - item_stacks - Get agent inventory as list of ItemStack objects
  Methods:
    - get_total(item_name) - Get total count of an item across all stacks
    - get_item(item_name) - Get a single Item or PlaceableItem instance
    - get_item_stacks(item_name, count, number_of_stacks?, strict?) - Get item stacks for a specific item
    - check_recipe_count(recipe_name) - Check how many times a recipe can be crafted
  Usage: inventory.get_total('iron-plate')"""
    
    @property
    def item_stacks(self):
        """Get agent inventory as list of ItemStack objects."""
        return _get_factory().inventory.item_stacks
    
    def get_total(self, item_name: str) -> int:
        """Get total count of an item across all stacks."""
        return _get_factory().inventory.get_total(item_name)
    
    def get_item(self, item_name: str):
        """Get a single Item or PlaceableItem instance."""
        return _get_factory().inventory.get_item(item_name)
    
    def get_item_stacks(
        self,
        item_name: str,
        count: Union[int, Literal["half", "full"]],
        number_of_stacks: Union[int, Literal["max"]] = "max",
        strict: bool = False
    ) -> List[ItemStack]:
        """Get item stacks for a specific item."""
        return _get_factory().inventory.get_item_stacks(item_name, count, number_of_stacks, strict)
    
    def check_recipe_count(self, recipe_name: str) -> int:
        """Check how many times a recipe can be crafted.
        
        Raises:
            ValueError: If the recipe is not handcraftable
        """
        # Check if recipe is handcraftable
        from FactoryVerse.dsl.prototypes import get_recipe_prototypes
        recipe_protos = get_recipe_prototypes()
        
        if not recipe_protos.is_handcraftable(recipe_name):
            category = recipe_protos.get_recipe_category(recipe_name)
            if category == 'smelting':
                raise ValueError(
                    f"Cannot handcraft '{recipe_name}' - it requires smelting in a furnace. "
                    f"Smelting recipes (iron-plate, copper-plate, steel-plate, stone-brick) must be produced in stone-furnace, steel-furnace, or electric-furnace."
                )
            else:
                raise ValueError(
                    f"Cannot handcraft '{recipe_name}' - it requires category='{category}' machine. "
                    f"Only recipes with category='crafting' can be handcrafted."
                )
        
        return _get_factory().inventory.check_recipe_count(recipe_name)


class _ReachableAccessor:
    """Top-level reachable entities/resources helper accessor.
    
    Provides access to ReachableEntities and ReachableResources methods.
    """
    
    def __repr__(self) -> str:
        return """ReachableAffordance
  Methods:
    - get_current_position() - Get current agent position
    - get_entity(entity_name, position?, options?) - Get a single entity matching criteria
    - get_entities(entity_name?, options?) - Get all entities matching criteria
    - get_resource(resource_name, position?) - Get a single resource matching criteria
    - get_resources(resource_name?, resource_type?) - Get all resources matching criteria
  Usage: reachable.get_entity('stone-furnace')"""
    
    def get_current_position(self) -> MapPosition:
        """Get current agent position from Lua.
        
        Returns:
            MapPosition of the agent's current location
        """
        return _get_factory().get_position()
    
    def get_entity(
        self,
        entity_name: str,
        position: Optional[MapPosition] = None,
        options: Optional[Dict[str, Any]] = None
    ):
        """Get a single entity matching criteria.
        
        Args:
            entity_name: Entity prototype name (e.g., "electric-mining-drill")
            position: Optional exact position match
            options: Optional dict with filters:
                - recipe: str - filter by recipe name
                - direction: Direction - filter by direction
                - entity_type: str - filter by Factorio entity type
                - status: str - filter by status (e.g., "working", "no-power")
        
        Returns:
            First matching ReachableEntity instance, or None if not found
        """
        return _get_factory().reachable_entities.get_entity(entity_name, position, options)
    
    def get_entities(
        self,
        entity_name: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ):
        """Get entities matching criteria.
        
        Args:
            entity_name: Optional entity prototype name filter
            options: Optional dict with filters (same as get_entity)
        
        Returns:
            List of matching ReachableEntity instances (may be empty)
        """
        return _get_factory().reachable_entities.get_entities(entity_name, options)
    
    def get_resource(
        self,
        resource_name: str,
        position: Optional[MapPosition] = None
    ):
        """Get a single resource matching criteria.
        
        Args:
            resource_name: Resource name (e.g., "iron-ore", "tree")
            position: Optional exact position match
        
        Returns:
            BaseResource instance (or appropriate subclass), or None if not found
        """
        return _get_factory().reachable_resources.get_resource(resource_name, position)
    
    def get_resources(
        self,
        resource_name: Optional[str] = None,
        resource_type: Optional[str] = None
    ):
        """Get resources matching criteria.
        
        Returns ResourceOrePatch for multiple ore patches of same type,
        BaseResource for single ore patches or entities.
        
        Args:
            resource_name: Optional resource name filter (e.g., "iron-ore", "tree")
            resource_type: Optional resource type filter. Can be:
                - "ore" or "resource" - filters to ore patches (type="resource")
                - "entity" - filters to trees and rocks (type="tree" or "simple-entity")
                - "tree" - filters to trees only
                - "simple-entity" - filters to rocks only
                - "resource" - filters to ore patches only (Factorio type)
        
        Returns:
            List[Union[ResourceOrePatch, BaseResource]]:
            - ResourceOrePatch: Multiple ore patches of same type (consolidated)
            - BaseResource: Single ore patch or entity (trees/rocks)
        """
        return _get_factory().reachable_resources.get_resources(resource_name, resource_type)


# Top-level action instances - use these in DSL context
walking = _WalkingAccessor()
crafting = _CraftingAccessor()
research = _ResearchAccessor()
inventory = _InventoryAccessor()
reachable = _ReachableAccessor()

# Ghost manager - direct access (not wrapped, accessed as property-like)
class _GhostManagerProxy:
    """Proxy to access ghost_manager methods directly."""
    
    def __getattr__(self, name):
        """Delegate all attribute access to the factory's ghost manager."""
        return getattr(_get_factory().ghosts, name)

ghost_manager = _GhostManagerProxy()


class _DuckDBAccessor:
    """Top-level DuckDB database accessor.
    
    Provides high-level method to load snapshot data into the database.
    """
    
    async def load_snapshots(
        self,
        snapshot_dir: Optional[Path] = None,
        db_path: Optional[Union[str, Path]] = None,
        **kwargs
    ):
        """Load snapshot data into the database (async, waits for completion).
        
        High-level method that auto-creates connection, schema, and
        auto-detects snapshot directory if not provided.
        
        By default, this method will block until all charted chunks reach
        COMPLETE state. Use wait_for_initial=False to skip waiting.
        
        Args:
            snapshot_dir: Path to snapshot directory (auto-detects if None)
            db_path: Optional path to DuckDB database file (uses in-memory if None)
            **kwargs: Additional arguments passed to factory.load_snapshots()
                     Including: wait_for_initial (bool, default=True), initial_timeout (float)
        
        Returns:
            None
        """
        return await _get_factory().load_snapshots(
            snapshot_dir=snapshot_dir,
            db_path=db_path,
            **kwargs
        )
    
    def load_snapshots_sync(
        self,
        snapshot_dir: Optional[Path] = None,
        db_path: Optional[Union[str, Path]] = None,
        **kwargs
    ):
        """Load snapshot data into the database (sync, doesn't wait for completion).
        
        This is the synchronous version that loads existing files but doesn't
        wait for chunks to reach COMPLETE state. Use this if you want to load
        data and handle completion waiting manually.
        
        Args:
            snapshot_dir: Path to snapshot directory (auto-detects if None)
            db_path: Optional path to DuckDB database file (uses in-memory if None)
            **kwargs: Additional arguments passed to factory._load_snapshots_sync()
        
        Returns:
            None
        """
        _get_factory()._load_snapshots_sync(
            snapshot_dir=snapshot_dir,
            db_path=db_path,
            **kwargs
        )
    
    @property
    def connection(self):
        """Get the DuckDB connection (automatically synced).
        
        This property automatically ensures the DB is synced before returning.
        The sync happens asynchronously if needed, but the connection is returned
        immediately for synchronous queries.
        
        Returns:
            DuckDB connection object
        
        Raises:
            RuntimeError: If database has not been loaded yet
        """
        factory = _get_factory()
        con = factory.duckdb_connection
        if con is None:
            raise RuntimeError(
                "DuckDB database not loaded. Call map_db.load_snapshots() first."
            )
        
        # Ensure sync if service is running (non-blocking)
        if factory._game_data_sync and factory._game_data_sync.is_running:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Schedule sync in background (non-blocking)
                    asyncio.create_task(factory._game_data_sync.ensure_synced())
                else:
                    # Run sync synchronously if no loop
                    loop.run_until_complete(factory._game_data_sync.ensure_synced())
            except RuntimeError:
                # No event loop, skip sync (will happen on next async operation)
                pass
        
        return con
    
    async def ensure_synced(self, timeout: float = 5.0):
        """
        Explicitly ensure DB is synced before query.
        
        Use this before critical queries that require up-to-date data.
        
        Args:
            timeout: Maximum time to wait for sync (seconds)
        """
        factory = _get_factory()
        if factory._game_data_sync and factory._game_data_sync.is_running:
            await factory._game_data_sync.ensure_synced(timeout=timeout)

    
    def get_entity(self, query: str) -> Optional["RemoteViewEntity"]:
        """Get single read-only entity from DuckDB query.
        
        Args:
            query: SQL SELECT query with LIMIT 1 (enforced)
        
        Returns:
            RemoteViewEntity instance or None if no results
        """
        factory = _get_factory()
        return factory.map_db.get_entity(query)
    
    def get_entities(self, query: str) -> List["RemoteViewEntity"]:
        """Get read-only entities from DuckDB query.
        
        Args:
            query: SQL SELECT query (validated for safety)
        
        Returns:
            List of RemoteViewEntity instances (read-only)
        """
        factory = _get_factory()
        return factory.map_db.get_entities(query)

map_db = _DuckDBAccessor()




def get_reachable_entities() -> List[ReachableEntity]:
    """Get the reachable entities.
    
    Returns:
        List of ReachableEntity objects within reach
    """
    factory = _get_factory()
    data = factory.get_reachable(attach_ghosts=False)  # Don't need ghosts for this function
    
    entities = []
    entities_data = data.get("entities", [])
    
    for entity_data in entities_data:
        # Parse entity data and create ReachableEntity
        name = entity_data.get("name", "")
        position_data = entity_data.get("position", {})
        position = MapPosition(x=position_data.get("x", 0), y=position_data.get("y", 0))
        
        # Parse bounding box if available
        bbox_data = entity_data.get("bounding_box")
        if bbox_data:
            left_top = Position(x=bbox_data["left_top"]["x"], y=bbox_data["left_top"]["y"])
            right_bottom = Position(x=bbox_data["right_bottom"]["x"], y=bbox_data["right_bottom"]["y"])
            bounding_box = BoundingBox(left_top=left_top, right_bottom=right_bottom)
        else:
            # Create minimal bounding box
            
            bounding_box = BoundingBox(
                left_top=Position(x=position.x, y=position.y),
                right_bottom=Position(x=position.x + 1, y=position.y + 1)
            )
        
        # Parse direction if available
        direction = None
        if "direction" in entity_data:
            try:
                direction = Direction(entity_data["direction"])
            except (ValueError, KeyError):
                pass
        
        entity = ReachableEntity(
            name=name,
            position=position,
            bounding_box=bounding_box,
            direction=direction
        )
        entities.append(entity)
    
    return entities


# Internal storage for the configured factory instance
_configured_factory: Optional[PlayingFactory] = None

def enable_logging(level: int = logging.INFO):
    """
    Enable logging for the DSL to see RCON/UDP traffic.
    Useful in notebooks where default logging might be suppressed.
    
    Args:
        level: Logging level (default INFO)
    """
    # Get the library logger
    logger = logging.getLogger("src.FactoryVerse")
    logger.setLevel(level)
    
    # Check if handler already exists to avoid duplicates
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            '%(name)s - %(levelname)s - %(message)s'
        ))
        logger.addHandler(handler)


def configure(
    rcon_client: RconClient, 
    agent_id: str,
    snapshot_dir: Optional[Path] = None,
    db_path: Optional[Union[str, Path]] = None,
    agent_udp_port: Optional[int] = None
):
    """
    Configure the DSL environment with RCON connection and agent ID.
    This should be called ONCE by the system/notebook initialization.
    
    Args:
        rcon_client: RCON client for remote interface calls
        agent_id: Agent ID (e.g., 'agent_1')
        snapshot_dir: Optional path to snapshot directory (auto-detected if None)
        db_path: Optional path to DuckDB database file (uses in-memory if None)
        agent_udp_port: Optional UDP port for agent-specific async actions. 
                       If provided, agent owns this port completely (decoupled from snapshot port).
    """
    global _configured_factory
    
    # 1. Fetch recipes
    cmd = f"/c rcon.print(helpers.table_to_json(remote.call('{agent_id}', 'get_recipes')))"
    try:
        res = rcon_client.send_command(cmd)
        res = rcon_client.send_command(cmd)
        recipes_data = json.loads(res)
        if isinstance(recipes_data, dict):
            # If it's a dict (keyed by name), convert to list of values
            recipes_data = list(recipes_data.values())
        recipes = Recipes(recipes_data)
        print(f"DEBUG: Loaded {len(recipes.recipes)} recipes into registry.")
    except Exception as e:
        print(f"Warning: Could not pre-fetch recipes: {e}")
        try:
             # Only print partial response if possible to avoid massive logs, or just type
            print(f"Recieved data type: {type(json.loads(res))}")
        except:
            pass
        recipes = Recipes({})

    # 2. Create and store factory instance
    # Note: RCON client is stored inside the factory but marked private
    # If agent_udp_port is provided, agent will listen directly on that port (decoupled from snapshot port)
    _configured_factory = PlayingFactory(rcon_client, agent_id, recipes, agent_udp_port=agent_udp_port)
    
    # 3. Auto-load snapshots if snapshot_dir or db_path provided
    # Note: Uses sync version here since configure() is not async
    # User should call await map_db.load_snapshots() in playing_factorio() context
    # to wait for initial snapshot completion
    if snapshot_dir is not None or db_path is not None:
        _configured_factory._load_snapshots_sync(
            snapshot_dir=snapshot_dir,
            db_path=db_path
        )


@contextmanager
def playing_factorio():
    """
    Context manager to activate the configured DSL runtime.
    
    Automatically starts GameDataSyncService if DB is loaded.
    The sync service runs in the background and keeps DB in sync.
    
    Usage:
        with playing_factorio():
            await walking.to(...)
            # DB is automatically synced before queries
            entities = map_db.connection.execute("SELECT * FROM map_entity").fetchall()
    """
    global _configured_factory
    
    if _configured_factory is None:
        raise RuntimeError(
            "DSL not configured. System must call dsl.configure(rcon, agent_id) first."
        )

    # Set context var to the pre-configured instance
    token = _playing_factory.set(_configured_factory)
    
    # Start game data sync service if DB is loaded (non-blocking)
    sync_started = False
    try:
        if _configured_factory._game_data_sync:
            # Start sync service in background if not already running
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Schedule start in background (non-blocking)
                    asyncio.create_task(_configured_factory._ensure_game_data_sync())
                    sync_started = True
                else:
                    # No loop running, start sync service
                    loop.run_until_complete(_configured_factory._ensure_game_data_sync())
                    sync_started = True
            except RuntimeError:
                # No event loop, create one and start sync
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(_configured_factory._ensure_game_data_sync())
                    sync_started = True
                except Exception as e:
                    logging.warning(f"Could not start game data sync service: {e}")
        
        yield _configured_factory
    finally:
        # Stop sync service if we started it
        if sync_started and _configured_factory._game_data_sync:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Schedule stop in background
                    asyncio.create_task(_configured_factory._stop_game_data_sync())
                else:
                    loop.run_until_complete(_configured_factory._stop_game_data_sync())
            except RuntimeError:
                pass
        
        _playing_factory.reset(token)

"""
with playing_factorio():
    # Async/await actions
    await walking.to(MapPosition(x=10, y=20))
    await crafting.craft('iron-plate', count=10)
    
    # Sync actions
    walking.cancel()
    crafting.enqueue('iron-plate', count=10)
    crafting.dequeue('iron-plate')
    crafting.status()
    
    research.enqueue('automation')
    research.dequeue()
    research.status()
    
    # Top-level utilities
    inventory.item_stacks  # Get inventory
    stone_furnace = inventory.get_item("stone-furnace")
    stone_furnace.place(MapPosition(x=10, y=20))
    mining_drill = inventory.get_item("electric-mining-drill")
    mining_drill.get_placement_cues()
    inventory.get_total("iron-plate")
    inventory.get_item_stacks("iron-plate", "full", 3)  # 3 full stacks
    inventory.get_item_stacks("iron-plate", "full")  # max full stacks (default)
    inventory.check_recipe_count("iron-plate")
    
    # Resources - mine directly from reachable resources
    copper_patches = reachable.get_resources("copper-ore")
    if copper_patches:
        copper_patch = copper_patches[0]
        await copper_patch[0].mine(max_count=50)  # Mine first tile in patch
    
    get_reachable_entities()
"""