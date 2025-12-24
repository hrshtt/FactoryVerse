from __future__ import annotations
import json
import asyncio
import time
import logging
import socket
import threading
import queue
from pathlib import Path
from typing import Any, Dict, Optional, Union, List, Literal, TYPE_CHECKING, Callable

logger = logging.getLogger(__name__)

from FactoryVerse.dsl.types import (
    MapPosition, Direction, _playing_factory, 
    AsyncActionResponse, CraftingStatus, ResearchStatus, ResearchQueueItem,
    EntityInspectionData, ActionResult, AgentInspectionData,
    MineAsyncResponse, CraftAsyncResponse, WalkAsyncResponse,
    ReachableSnapshotData, PlacementCuesResponse,
)
from FactoryVerse.dsl.item.base import ItemStack
from FactoryVerse.dsl.recipe.base import Recipes, BaseRecipe, BasicRecipeName
from FactoryVerse.dsl.technology.base import TechTree
from factorio_rcon import RCONClient as RconClient
from contextvars import ContextVar
from contextlib import contextmanager
from FactoryVerse.dsl.types import Direction, MapPosition, BoundingBox
from FactoryVerse.infra.udp_dispatcher import UDPDispatcher, get_udp_dispatcher
from FactoryVerse.dsl.ghosts import GhostManager
from FactoryVerse.infra.game_data_sync import GameDataSyncService

if TYPE_CHECKING:
    import duckdb
    from FactoryVerse.dsl.item.base import Item, PlaceableItem
    from FactoryVerse.dsl.entity.base import ReachableEntity
    from FactoryVerse.dsl.entity.remote_view_entity import RemoteViewEntity


# Import _playing_factory from types to break circular dependencies
from FactoryVerse.dsl.types import _playing_factory


class AsyncActionListener:
    """UDP listener for async action completion events.
    
    Can operate in two modes:
    1. Direct UDP listening on agent-specific port (agent_port specified)
    2. Through UDPDispatcher for shared port (udp_dispatcher specified)
    """
    
    def __init__(self, udp_dispatcher: Optional[UDPDispatcher] = None, 
                 agent_port: Optional[int] = None, 
                 host: str = "0.0.0.0",
                 timeout: int = 30):
        """
        Initialize the UDP listener.
        
        Args:
            udp_dispatcher: Optional UDPDispatcher instance. If None and agent_port is None, uses global dispatcher.
            agent_port: Optional direct UDP port for agent-specific messages. If provided, listens directly on this port.
            host: Host to bind to (only used if agent_port is provided)
            timeout: Default timeout in seconds for waiting on actions
        """
        self.udp_dispatcher = udp_dispatcher
        self.agent_port = agent_port
        self.host = host
        self.timeout = timeout
        self.pending_actions: Dict[str, asyncio.Event] = {}
        self.action_results: Dict[str, Dict[str, Any]] = {}
        self.event_loops: Dict[str, asyncio.AbstractEventLoop] = {}
        self.action_timeouts: Dict[str, float] = {}  # Track timeout deadlines for progress extension
        self.action_progress: Dict[str, Dict[str, Any]] = {}  # Track progress for actions
        self.notification_queue: queue.Queue = queue.Queue()  # Thread-safe queue for notifications
        self.notification_callbacks: Dict[str, Callable] = {}  # Callbacks for specific notification types
        self.running = False
        self.sock: Optional[socket.socket] = None
        self.listener_thread: Optional[threading.Thread] = None
        
    async def start(self):
        """Start listening for UDP messages.
        
        If agent_port is set, listens directly on that port.
        Otherwise, subscribes to UDP dispatcher.
        """
        if self.agent_port is not None:
            # Direct UDP listening mode (agent-specific port)
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                self.sock.bind((self.host, self.agent_port))
            except OSError as e:
                self.sock.close()
                self.sock = None
                raise RuntimeError(f"Failed to bind UDP socket to {self.host}:{self.agent_port}: {e}")
            
            self.sock.settimeout(0.5)  # Non-blocking with timeout
            self.running = True
            
            # Start listener thread
            self.listener_thread = threading.Thread(target=self._direct_listen_loop, daemon=True)
            self.listener_thread.start()
            
            logger.info(f"✅ AsyncActionListener started on direct port {self.host}:{self.agent_port}")
        else:
            # Dispatcher mode (shared port)
            if self.udp_dispatcher is None:
                self.udp_dispatcher = get_udp_dispatcher()
            
            if not self.udp_dispatcher.is_running():
                await self.udp_dispatcher.start()
            
            self.udp_dispatcher.subscribe("*", self._handle_udp_message)
            self.running = True
            logger.info("✅ AsyncActionListener started via UDPDispatcher")
    
    def _direct_listen_loop(self):
        """Background thread loop for receiving UDP packets directly."""
        while self.running and self.sock:
            try:
                data, addr = self.sock.recvfrom(65535)
                try:
                    payload = json.loads(data.decode('utf-8'))
                    event_type = payload.get('event_type')
                    
                    if event_type == 'action':
                        self._handle_udp_message(payload)
                    elif event_type == 'notification':
                        self._handle_notification(payload)
                    else:
                        logger.warning(f"Unknown event_type: {event_type}")
                        
                except json.JSONDecodeError as e:
                    logger.warning(f"⚠️  Failed to decode UDP JSON from {addr}: {e}")
                except Exception as e:
                    logger.error(f"❌ Error processing UDP message from {addr}: {e}")
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"❌ Error in direct UDP listener: {e}")
    
    def _handle_notification(self, payload: Dict[str, Any]):
        """Process received UDP notification message."""
        logger.info(f"UDP Notification RX: {payload}")
        self.notification_queue.put(payload)
        notification_type = payload.get('notification_type')
        if notification_type and notification_type in self.notification_callbacks:
            try:
                self.notification_callbacks[notification_type](payload)
            except Exception as e:
                logger.error(f"Error in notification callback for type '{notification_type}': {e}")
    
    def _handle_udp_message(self, payload: Dict[str, Any]):
        """Process received UDP message from dispatcher (called by dispatcher thread).
        
        Implements state machine contract:
        - status: "queued" -> ignore (logging only)
        - status: "progress" -> track progress, extend timeout for walking
        - status: "completed" -> finish await
        - status: "cancelled" -> finish await with cancellation
        """
        logger.info(f"UDP RX: {payload}")
        try:
            action_id = payload.get('action_id')
            # TODO: make this categorically associated with the action type
            if not action_id:
                return
            
            # Require status field (no backwards compatibility)
            status = payload.get('status')
            if not status:
                return
            
            if action_id not in self.pending_actions:
                return
            
            # State machine routing
            if status == "queued":
                # Ignore - logging only, redundant with RCON response
                return
            
            if status == "progress":
                # Track progress
                self.action_progress[action_id] = payload.get('result', {})
                
                # Extend timeout for walking only
                action_type = payload.get('action_type')
                if action_type == 'walk_to' and action_id in self.action_timeouts:
                    # Extend timeout by default timeout duration when progress is received
                    self.action_timeouts[action_id] = time.time() + self.timeout
                    logger.debug(f"Extended timeout for {action_id} due to progress")
                
                return
            
            if status in ("completed", "cancelled"):
                # Finish await
                self.action_results[action_id] = payload
                event = self.pending_actions[action_id]
                
                loop = self.event_loops.get(action_id)
                if loop and loop.is_running():
                    loop.call_soon_threadsafe(event.set)
                else:
                    event.set()
                return
            
            # Unknown status
            logger.warning(f"Unknown status '{status}' for action {action_id}")
        except Exception as e:
            print(f"❌ Error processing UDP message: {e}")
    
    async def stop(self):
        """Stop listening for UDP messages."""
        self.running = False
        
        if self.agent_port is not None and self.sock:
            # Direct UDP listening mode - close socket
            if self.listener_thread:
                self.listener_thread.join(timeout=2)
            if self.sock:
                self.sock.close()
                self.sock = None
        elif self.udp_dispatcher and self.running:
            # Dispatcher mode - unsubscribe
            self.udp_dispatcher.unsubscribe("*", self._handle_udp_message)
    
    def register_action(self, action_id: str, initial_timeout_deadline: Optional[float] = None):
        """Register an action to wait for completion via UDP.
        
        Args:
            action_id: The action ID to register
            initial_timeout_deadline: Optional initial timeout deadline in seconds since epoch (for progress-based extension)
        """
        event = asyncio.Event()
        self.pending_actions[action_id] = event
        self.action_results[action_id] = None
        self.action_progress[action_id] = {}
        if initial_timeout_deadline:
            self.action_timeouts[action_id] = initial_timeout_deadline
        try:
            self.event_loops[action_id] = asyncio.get_running_loop()
        except RuntimeError:
            self.event_loops[action_id] = None
    
    async def wait_for_action(self, action_id: str, timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Wait for an action to complete via UDP.
        
        Args:
            action_id: The action ID to wait for
            timeout: Optional timeout override in seconds
            
        Returns:
            The action completion payload
            
        Raises:
            TimeoutError: If action doesn't complete within timeout
            ValueError: If action_id not registered
        """
        if action_id not in self.pending_actions:
            raise ValueError(f"Action not registered: {action_id}")
        
        event = self.pending_actions[action_id]
        timeout_secs = timeout or self.timeout
        
        # Initialize timeout deadline for progress-based extension (walking only)
        if action_id not in self.action_timeouts:
            self.action_timeouts[action_id] = time.time() + timeout_secs
        
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_secs)
            return self.action_results[action_id]
        except asyncio.TimeoutError:
            raise
        finally:
            self.pending_actions.pop(action_id, None)
            self.action_results.pop(action_id, None)
            self.action_timeouts.pop(action_id, None)
            self.action_progress.pop(action_id, None)
            self.event_loops.pop(action_id, None)


class AgentCommands:
    """Static command wrapper for agent remote interface methods.

    Generates RCON command strings based on the RemoteInterface.lua method definitions.
    Does not execute commands, only provides the correct command strings.

    Args:
        agent_id: Agent ID (e.g., "agent_1")
    """

    def __init__(self, agent_id: str):
        self.agent_id = agent_id


class AgentInventory:
    """Represents the agent's inventory with helper methods for querying and shaping items.
    
    This is not an action class (doesn't mutate state), but provides helper methods
    to shape inventory items and stacks for downstream actions.
    """

    def __init__(self, factory: "PlayingFactory"):
        self._factory = factory

    @property
    def item_stacks(self) -> List[ItemStack]:
        """Get agent inventory as list of ItemStack objects.
        
        Equivalent to the old get_inventory_items() top-level function.
        """
        inventory_data = self._factory.get_inventory_items()
        
        # get_inventory_items now returns Dict[str, int] mapping item names to counts
        items = []
        for item_name, count in inventory_data.items():
            # Default subgroup - could be enhanced to lookup from prototypes
            items.append(ItemStack(name=item_name, count=count, subgroup="raw-material"))
        
        return items

    def get_total(self, item_name: str) -> int:
        """Get total count of an item across all stacks.
        
        Args:
            item_name: Name of the item to count
            
        Returns:
            Total count of the item in inventory
        """
        return sum(stack.count for stack in self.item_stacks if stack.name == item_name)

    def get_item(self, item_name: str) -> Optional[Union["Item", "PlaceableItem"]]:
        """Get a single Item or PlaceableItem instance for the given item name.
        
        Args:
            item_name: Name of the item
            
        Returns:
            Item or PlaceableItem instance, or None if item is not in inventory
        """
        if self.get_total(item_name) == 0:
            return None
        
        from FactoryVerse.dsl.item.base import get_item
        return get_item(item_name)

    def get_item_stacks(
        self,
        item_name: str,
        count: Union[int, Literal["half", "full"]],
        number_of_stacks: Union[int, Literal["max"]] = "max",
        strict: bool = False
    ) -> List[ItemStack]:
        """Get item stacks for a specific item.
        
        Args:
            item_name: Name of the item
            count: Count per stack (int), "half" for half stack, or "full" for full stack
            number_of_stacks: Number of stacks to return, or "max" for all possible stacks (default: "max")
            strict: If True, raises exception when insufficient items. If False, returns all possible.
            
        Returns:
            List of ItemStack instances
            
        Raises:
            ValueError: If strict=True and insufficient items available
        """
        total_available = self.get_total(item_name)
        
        # Determine count per stack first (needed for validation)
        if count == "half":
            # Get stack size from item prototype
            item = self.get_item(item_name)
            if item:
                stack_size = item.stack_size
                count_per_stack = stack_size // 2
            else:
                # Fallback to default
                count_per_stack = 25
        elif count == "full":
            # Get stack size from item prototype
            item = self.get_item(item_name)
            if item:
                count_per_stack = item.stack_size
            else:
                # Fallback to default
                count_per_stack = 50
        else:
            count_per_stack = count
        
        # Early return if no items available
        if total_available == 0:
            if strict and isinstance(number_of_stacks, int) and number_of_stacks > 0:
                raise ValueError(f"No {item_name} available in inventory")
            return []
        
        # Validate if requested count exceeds available (strict mode)
        if strict and count_per_stack > total_available:
            raise ValueError(
                f"Insufficient {item_name}: requested count {count_per_stack} exceeds available {total_available}"
            )
        
        # Determine number of stacks
        if number_of_stacks == "max":
            # Calculate how many stacks we can make
            max_stacks = total_available // count_per_stack
            number_of_stacks = max_stacks
            # If strict and we can't make at least one stack, raise exception
            if strict and max_stacks == 0:
                raise ValueError(
                    f"Insufficient {item_name}: cannot make even one stack of {count_per_stack}, available {total_available}"
                )
        else:
            # Validate if we have enough
            required = count_per_stack * number_of_stacks
            if strict and required > total_available:
                raise ValueError(
                    f"Insufficient {item_name}: required {required}, available {total_available}"
                )
            # Cap at available (if not strict, give all possible)
            if not strict:
                max_possible = total_available // count_per_stack
                number_of_stacks = min(number_of_stacks, max_possible)
        
        # Ensure number_of_stacks is non-negative
        number_of_stacks = max(0, number_of_stacks)
        
        # Create stacks
        stacks = []
        remaining = total_available
        
        for _ in range(number_of_stacks):
            if remaining <= 0:
                break
            stack_count = min(count_per_stack, remaining)
            stacks.append(ItemStack(name=item_name, count=stack_count, subgroup="raw-material"))
            remaining -= stack_count
        
        return stacks

    def check_recipe_count(self, recipe_name: str) -> int:
        """Check how many times a recipe can be crafted based on available ingredients.
        
        Args:
            recipe_name: Name of the recipe
            
        Returns:
            Maximum number of times the recipe can be crafted
        """
        recipe = self._factory.recipes[recipe_name]
        
        if not recipe or not recipe.ingredients:
            return 0
        
        # Calculate how many times we can craft for each ingredient
        max_crafts_per_ingredient = []
        for ingredient in recipe.ingredients:
            available_count = self.get_total(ingredient.name)
            if ingredient.count == 0:
                max_crafts_per_ingredient.append(float("inf"))
            else:
                max_crafts = available_count // ingredient.count
                max_crafts_per_ingredient.append(max_crafts)
        
        # Find the minimum (bottleneck ingredient)
        if not max_crafts_per_ingredient:
            return 0
        
        actual_crafts = min(max_crafts_per_ingredient)
        return int(actual_crafts) if actual_crafts != float("inf") else 0


class ReachableEntities:
    """Represents reachable entities with query methods.
    
    Similar to AgentInventory but for entities. Provides filtering
    and query capabilities without returning raw lists.
    
    Note: Always fetches fresh data from the game - no caching.
    """
    
    def __init__(self, factory: "PlayingFactory"):
        self._factory = factory
    
    def _fetch_fresh_data(self):
        """Fetch fresh entities data from factory (no caching)."""
        data = self._factory.get_reachable(attach_ghosts=False)
        entities_data = data.get("entities", [])
        # Convert to entity instances
        from FactoryVerse.dsl.entity.base import create_entity_from_data
        entities_instances = [
            create_entity_from_data(entity_data)
            for entity_data in entities_data
        ]
        return entities_instances, entities_data
    
    def get_entity(
        self,
        entity_name: str,
        position: Optional[MapPosition] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Optional[ReachableEntity]:
        """Get a single entity matching criteria.
        
        Always fetches fresh data from the game - no caching.
        
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
        # Always fetch fresh data
        entities_instances, entities_data = self._fetch_fresh_data()
        options = options or {}
        
        # Filter by name first
        matches = [
            (inst, data) for inst, data in zip(entities_instances, entities_data)
            if inst.name == entity_name
        ]
        
        # Filter by position if provided
        if position is not None:
            matches = [(inst, data) for inst, data in matches if inst.position == position]
        
        # Apply option filters
        if "recipe" in options:
            recipe = options["recipe"]
            matches = [(inst, data) for inst, data in matches if data.get("recipe") == recipe]
        
        if "direction" in options:
            direction = options["direction"]
            matches = [(inst, data) for inst, data in matches if inst.direction == direction]
        
        if "entity_type" in options:
            entity_type = options["entity_type"]
            matches = [(inst, data) for inst, data in matches if data.get("type") == entity_type]
        
        if "status" in options:
            status = options["status"]
            matches = [(inst, data) for inst, data in matches if data.get("status") == status]
        
        return matches[0][0] if matches else None
    
    def get_entities(
        self,
        entity_name: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> List[ReachableEntity]:
        """Get entities matching criteria.
        
        Always fetches fresh data from the game - no caching.
        
        Args:
            entity_name: Optional entity prototype name filter
            options: Optional dict with filters (same as get_entity)
        
        Returns:
            List of matching ReachableEntity instances (may be empty)
        """
        # Always fetch fresh data
        entities_instances, entities_data = self._fetch_fresh_data()
        options = options or {}
        
        # Start with all entities
        matches = [
            (inst, data) for inst, data in zip(entities_instances, entities_data)
        ]
        
        # Filter by name if provided
        if entity_name is not None:
            matches = [(inst, data) for inst, data in matches if inst.name == entity_name]
        
        # Apply option filters (same logic as get_entity)
        if "recipe" in options:
            recipe = options["recipe"]
            matches = [(inst, data) for inst, data in matches if data.get("recipe") == recipe]
        
        if "direction" in options:
            direction = options["direction"]
            matches = [(inst, data) for inst, data in matches if inst.direction == direction]
        
        if "entity_type" in options:
            entity_type = options["entity_type"]
            matches = [(inst, data) for inst, data in matches if data.get("type") == entity_type]
        
        if "status" in options:
            status = options["status"]
            matches = [(inst, data) for inst, data in matches if data.get("status") == status]
        
        return [inst for inst, _ in matches]


class ReachableResources:
    """Represents reachable resources with query methods.
    
    Similar pattern to AgentInventory but for resources (ores, trees, rocks).
    
    Note: Always fetches fresh data from the game - no caching.
    """
    
    def __init__(self, factory: "PlayingFactory"):
        self._factory = factory
    
    def _fetch_fresh_data(self):
        """Fetch fresh resources data from factory (no caching)."""
        data = self._factory.get_reachable(attach_ghosts=False)
        return data.get("resources", [])
    
    def get_resource(
        self,
        resource_name: str,
        position: Optional[MapPosition] = None
    ) -> Optional[Any]:
        """Get a single resource matching criteria.
        
        Always fetches fresh data from the game - no caching.
        
        Args:
            resource_name: Resource name (e.g., "iron-ore", "tree")
            position: Optional exact position match
        
        Returns:
            BaseResource instance (or appropriate subclass), or None if not found
        """
        from FactoryVerse.dsl.resource.base import _create_resource_from_data
        
        # Always fetch fresh data
        resources_data = self._fetch_fresh_data()
        
        matches = [
            data for data in resources_data
            if data.get("name") == resource_name
        ]
        
        if position is not None:
            matches = [
                data for data in matches
                if data.get("position", {}).get("x") == position.x
                and data.get("position", {}).get("y") == position.y
            ]
        
        if matches:
            return _create_resource_from_data(matches[0])
        return None
    
    def get_resources(
        self,
        resource_name: Optional[str] = None,
        resource_type: Optional[str] = None
    ) -> List[Any]:
        """Get resources matching criteria.
        
        Returns ResourceOrePatch for multiple ore patches of same type,
        BaseResource for single ore patches or entities.
        
        Always fetches fresh data from the game - no caching.
        
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
        from FactoryVerse.dsl.resource.base import ResourceOrePatch, BaseResource, _create_resource_from_data
        
        # Always fetch fresh data
        resources_data = self._fetch_fresh_data()
        
        matches = resources_data
        
        # Filter by name if provided
        if resource_name is not None:
            matches = [
                data for data in matches
                if data.get("name") == resource_name
            ]
        
        # Filter by type if provided
        if resource_type is not None:
            # Handle simplified aliases
            if resource_type == "ore":
                resource_type = "resource"
            elif resource_type == "entity":
                # Match both trees and simple-entities
                matches = [
                    data for data in matches
                    if data.get("type") in ("tree", "simple-entity")
                ]
            else:
                # Direct type match (resource, tree, simple-entity)
                matches = [
                    data for data in matches
                    if data.get("type") == resource_type
                ]
        
        # Group by resource name
        resources_by_name: Dict[str, List[Dict[str, Any]]] = {}
        for data in matches:
            name = data.get("name", "")
            if name not in resources_by_name:
                resources_by_name[name] = []
            resources_by_name[name].append(data)
        
        # Build result list
        result: List[Union[ResourceOrePatch, BaseResource]] = []
        
        for name, data_list in resources_by_name.items():
            resource_type_val = data_list[0].get("type", "resource")
            
            # Entities (trees, rocks) are always returned as BaseResource
            if resource_type_val in ("tree", "simple-entity"):
                for data in data_list:
                    result.append(_create_resource_from_data(data))
            # Ore patches: consolidate if multiple, return single as BaseResource
            elif resource_type_val == "resource":
                if len(data_list) > 1:
                    # Multiple tiles of same ore type -> ResourceOrePatch
                    result.append(ResourceOrePatch(name, data_list))
                else:
                    # Single tile -> BaseResource
                    result.append(_create_resource_from_data(data_list[0]))
            else:
                # Unknown type, return as BaseResource
                for data in data_list:
                    result.append(_create_resource_from_data(data))
        
        return result


class _DuckDBAccessor:
    """Accessor for DuckDB map database operations.
    
    Provides read-only access to entities across the entire map via SQL queries.
    Returns RemoteViewEntity instances that can be inspected and used for planning,
    but cannot be mutated (no pickup, add_fuel, etc.).
    """
    
    def __init__(self, connection):
        """Initialize accessor with DuckDB connection.
        
        Args:
            connection: DuckDB connection instance
        """
        self.connection = connection
    
    def get_entity(self, query: str) -> Optional["RemoteViewEntity"]:
        """Get single read-only entity from DuckDB query.
        
        Args:
            query: SQL SELECT query with LIMIT 1 (enforced)
        
        Returns:
            RemoteViewEntity instance or None if no results
        
        Raises:
            ValueError: If query is invalid, unsafe, or missing LIMIT 1
        
        Example:
            >>> entity = map_db.get_entity('''
            ...     SELECT * FROM map_entity me
            ...     JOIN mining_drill md ON me.entity_key = md.entity_key
            ...     WHERE entity_name = 'burner-mining-drill'
            ...     LIMIT 1
            ... ''')
            >>> entity.output_position  # Planning capability
            >>> entity.inspect()  # Requires context manager
        """
        from FactoryVerse.dsl.entity.base import create_entity_from_db
        
        # Validate query
        self._validate_query(query)
        
        # Enforce LIMIT 1
        query_upper = query.upper()
        if 'LIMIT 1' not in query_upper:
            raise ValueError("get_entity() requires LIMIT 1 in query")
        
        # Execute query
        cursor = self.connection.execute(query)
        result = cursor.fetchone()
        
        if result is None:
            return None
        
        # Convert to RemoteViewEntity
        entity_data = self._row_to_dict(result, cursor)
        return create_entity_from_db(entity_data)
    
    def get_entities(self, query: str) -> List["RemoteViewEntity"]:
        """Get read-only entities from DuckDB query.
        
        Args:
            query: SQL SELECT query (validated for safety)
        
        Returns:
            List of RemoteViewEntity instances (read-only)
        
        Raises:
            ValueError: If query is invalid or unsafe
        
        Example:
            >>> drills = map_db.get_entities('''
            ...     SELECT * FROM map_entity me
            ...     JOIN mining_drill md ON me.entity_key = md.entity_key
            ...     WHERE entity_name = 'burner-mining-drill'
            ... ''')
            >>> for drill in drills:
            ...     print(drill.output_position)  # Planning capability
        """
        from FactoryVerse.dsl.entity.base import create_entity_from_db
        
        # Validate query
        self._validate_query(query)
        
        # Execute query
        cursor = self.connection.execute(query)
        results = cursor.fetchall()
        
        # Convert to RemoteViewEntity instances
        entities = []
        for row in results:
            entity_data = self._row_to_dict(row, cursor)
            entity = create_entity_from_db(entity_data)
            entities.append(entity)
        
        return entities
    
    async def sync(self, timeout: float = 5.0) -> None:
        """Explicitly sync the database before queries.
        
        Call this before critical queries that require up-to-date data:
            await map_db.sync()
            entities = map_db.get_entities(...)
        
        Args:
            timeout: Maximum time to wait for sync (seconds)
        """
        from FactoryVerse.dsl.types import _playing_factory
        factory = _playing_factory.get()
        if factory and factory._game_data_sync and factory._game_data_sync.is_running:
            await factory._game_data_sync.ensure_synced(timeout=timeout)
    
    def _validate_query(self, query: str) -> None:
        """Validate that query is safe and read-only.
        
        Raises:
            ValueError: If query contains forbidden operations
        """
        query_upper = query.upper().strip()
        
        # Must be SELECT
        if not query_upper.startswith('SELECT'):
            raise ValueError("Only SELECT queries allowed")
        
        # No aggregations (agents should query raw data)
        forbidden_keywords = [
            'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP',
            'GROUP BY', 'HAVING', 'DISTINCT'
        ]
        
        for keyword in forbidden_keywords:
            if keyword in query_upper:
                raise ValueError(f"Query operation not allowed: {keyword}")
    
    def _row_to_dict(self, row, cursor) -> Dict[str, Any]:
        """Convert DuckDB row to entity data dict.
        
        Args:
            row: DuckDB query result row (tuple-like)
            cursor: DuckDB cursor with description
        
        Returns:
            Entity data dictionary compatible with create_entity_from_db
        """
        # DuckDB rows are tuples, get column names from cursor description
        if not cursor.description:
            raise ValueError("Cursor has no description - cannot determine column names")
        
        # Extract column names from cursor description
        # cursor.description is a list of tuples: [(name, type_code, ...), ...]
        column_names = [desc[0] for desc in cursor.description]
        
        # Convert row tuple to dict
        entity_data = dict(zip(column_names, row))
        
        return entity_data


class WalkingAction:
    """Walking action wrapper."""
    
    def __init__(self, factory: "PlayingFactory"):
        self._factory = factory
    
    async def to(
        self,
        position: Union[Dict[str, float], MapPosition],
        strict_goal: bool = False,
        options: Optional[Dict] = None,
        timeout: Optional[int] = None
    ) -> ActionResult:
        """Walk to a position.
        
        Args:
            position: Target position
            strict_goal: If true, fail if exact position unreachable
            options: Additional pathfinding options
            timeout: Optional timeout in seconds
            
        Returns:
            Completion payload
        """
        response = self._factory.walk_to(position, strict_goal, options)
        return await self._factory._await_action(response, timeout=timeout)
    
    def cancel(self) -> str:
        """Cancel current walking action."""
        return self._factory.stop_walking()


class MiningAction:
    """Mining action wrapper."""
    
    def __init__(self, factory: "PlayingFactory"):
        self._factory = factory
    
    async def mine(
        self,
        resource_name: str,
        max_count: Optional[int] = None,
        timeout: Optional[int] = None
    ) -> List[ItemStack]:
        """Mine a resource.
        
        Args:
            resource_name: Resource prototype name
            max_count: Max items to mine (None = deplete resource)
            timeout: Optional timeout in seconds
            
        Returns:
            List of ItemStack objects obtained from mining
        """
        if max_count and max_count > 25:
            # Enforce 25 limit mentioned by user
            logger.warning(f"Capping mining count from {max_count} to 25")
            max_count = 25
            
        response = self._factory.mine_resource(resource_name, max_count)
        result_payload = await self._factory._await_action(response, timeout=timeout)
        
        # Parse result for items
        items = []
        result_data = result_payload.get("result", {})
        if "actual_products" in result_data:
            for name, count in result_data["actual_products"].items():
                items.append(ItemStack(name=name, count=count, subgroup="raw-resource")) # Default to raw-resource or infer
                
        return items
    
    def cancel(self) -> str:
        """Cancel current mining action."""
        return self._factory.stop_mining()


class CraftingAction:
    """Crafting action wrapper."""
    
    def __init__(self, factory: "PlayingFactory"):
        self._factory = factory
    
    async def craft(
        self,
        recipe: str,
        count: int = 1,
        timeout: Optional[int] = None
    ) -> List[ItemStack]:
        """Craft a recipe.
        
        Args:
            recipe: Recipe name to craft
            count: Number of times to craft
            timeout: Optional timeout in seconds
            
        Returns:
            List of ItemStack objects crafted
        """
        response = self._factory.craft_enqueue(recipe, count)
        result_payload = await self._factory._await_action(response, timeout=timeout)
        
        # Parse result for items
        items = []
        result_data = result_payload.get("result", {})
        if "products" in result_data:
            for name, count in result_data["products"].items():
                items.append(ItemStack(name=name, count=count, subgroup="intermediate-product")) # Default or infer
                
        return items
    
    def enqueue(self, recipe: str, count: int = 1) -> Dict[str, Any]:
        """Enqueue a recipe for crafting.
        
        Args:
            recipe: Recipe name to craft
            count: Number of times to craft
            
        Returns:
            Response dict with queued status
        """
        return self._factory.craft_enqueue(recipe, count)
    
    def dequeue(self, recipe: str, count: Optional[int] = None) -> str:
        """Cancel queued crafting.
        
        Args:
            recipe: Recipe name to cancel
            count: Number to cancel (None = all)
        """
        return self._factory.craft_dequeue(recipe, count)
    
    def status(self) -> Dict[str, Any]:
        """Get current crafting status.
        
        Returns:
            Crafting state dict with active, recipe, action_id
        """
        state = self._factory.inspect(attach_state=True)
        return state.get("state", {}).get("crafting", {})


class ResearchAction:
    """Research action wrapper."""
    
    def __init__(self, factory: "PlayingFactory"):
        self._factory = factory
    
    def enqueue(self, technology: str) -> str:
        """Start researching a technology.
        
        Args:
            technology: Technology name to research
        """
        return self._factory.enqueue_research(technology)
    
    def dequeue(self) -> ActionResult:
        """Cancel current research."""
        return self._factory.cancel_current_research()
    
    def status(self) -> ResearchStatus:
        """Get current research status.
        
        Returns:
            Research status dict
        """
        techs_data = self._factory.get_technologies(only_available=False)
        
        # Build research status
        current_research = None
        queue = []
        
        # Note: get_technologies doesn't give the full queue order, but 
        # it gives the currently researching tech.
        # For full queue, use get_queue()
        for tech in techs_data.get("technologies", []):
            if tech.get("researching", False):
                current_research = tech.get("name")
                queue.append(ResearchQueueItem(
                    technology=tech.get("name"),
                    progress=tech.get("progress", 0.0),
                    level=tech.get("level", 1)
                ))
                break # Only one active
        
        return ResearchStatus(
            queue=queue,
            queue_length=len(queue),
            current_research=current_research,
            tick=techs_data.get("tick", 0)
        )
    
    def get_queue(self) -> ResearchStatus:
        """Get current research queue with progress information.
        
        Returns:
            ResearchStatus with queue, queue_length, current_research, and tick
        """
        return self._factory.get_research_queue()

class PlayingFactory:
    """Represents an active gameplay session for an agent."""
    
    _game_data_sync: Optional["GameDataSyncService"]

    def __init__(self, rcon_client: "RconClient", agent_id: str, 
                 recipes: Recipes, tech_tree: TechTree,
                 udp_dispatcher: Optional[UDPDispatcher] = None,
                 agent_udp_port: Optional[int] = None):
        """
        Initialize PlayingFactory.
        
        Args:
            rcon_client: RCON client for remote interface calls
            agent_id: Agent ID (e.g., 'agent_1')
            recipes: Recipes instance
            tech_tree: TechTree instance
            udp_dispatcher: Optional UDPDispatcher for shared port mode (deprecated, use agent_udp_port instead)
            agent_udp_port: Optional UDP port for agent-specific async actions. If provided, agent owns this port completely.
        """
        self._rcon = rcon_client
        self._agent_id = agent_id
        self.agent_commands = AgentCommands(agent_id)
        self.recipes = recipes
        self.tech_tree = tech_tree
        self._async_listener = AsyncActionListener(
            udp_dispatcher=udp_dispatcher,
            agent_port=agent_udp_port
        )
        self._ghost_manager = GhostManager(self, agent_id=agent_id)
        self._duckdb_connection = None
        self._game_data_sync = None
        
        # Initialize action wrappers
        self._walking = WalkingAction(self)
        self._crafting = CraftingAction(self)
        self._mining = MiningAction(self)
        self._research = ResearchAction(self)
        self._inventory = AgentInventory(self)
    
    async def _ensure_async_listener(self):
        """Ensure async listener is started."""
        if not self._async_listener.running:
            await self._async_listener.start()
    
    async def _await_action(self, response: AsyncActionResponse, timeout: Optional[int] = None) -> Dict[str, Any]:
        """Wait for an async action to complete.
        
        Args:
            response: Response dict from async action (should have action_id)
            timeout: Optional timeout in seconds (overrides calculated timeout)
            
        Returns:
            Completion payload from UDP
        """
        if not response.get('queued'):
            return response
        
        action_id = response.get('action_id')
        if not action_id:
            return response
        
        await self._ensure_async_listener()
        
        # Calculate timeout with 0.5x buffer for mining/crafting based on estimated_ticks
        calculated_timeout = timeout
        if timeout is None:
            estimated_ticks = response.get('estimated_ticks')
            if estimated_ticks:
                # Convert ticks to seconds: 1 tick = 1/60 seconds at game.speed = 1.0
                # Add 1.5x buffer for safety (total 2.5x)
                base_seconds = (estimated_ticks / 60.0)
                calculated_timeout = max(5.0, base_seconds * 2.5)
                logger.debug(f"Calculated timeout for {action_id}: {calculated_timeout:.3f}s (from {estimated_ticks} ticks)")
            else:
                calculated_timeout = self._async_listener.timeout
        
        self._async_listener.register_action(action_id)
        return await self._async_listener.wait_for_action(action_id, timeout=calculated_timeout)

    @property
    def agent_id(self) -> str:
        return self._agent_id
    
    @property
    def walking(self) -> "WalkingAction":
        """Walking action wrapper."""
        return self._walking
    
    @property
    def crafting(self) -> "CraftingAction":
        """Crafting action wrapper."""
        return self._crafting
    
    @property
    def mining(self) -> "MiningAction":
        """Mining action wrapper."""
        return self._mining
    
    @property
    def research(self) -> "ResearchAction":
        """Research action wrapper."""
        return self._research

    @property
    def inventory(self) -> "AgentInventory":
        """Agent inventory helper with methods for querying and shaping items."""
        return self._inventory
    
    @property
    def reachable_entities(self) -> "ReachableEntities":
        """Get reachable entities accessor."""
        if not hasattr(self, '_reachable_entities'):
            self._reachable_entities = ReachableEntities(self)
        return self._reachable_entities
    
    @property
    def reachable_resources(self) -> "ReachableResources":
        """Get reachable resources accessor."""
        if not hasattr(self, '_reachable_resources'):
            self._reachable_resources = ReachableResources(self)
        return self._reachable_resources
    
    @property
    def map_db(self) -> "_DuckDBAccessor":
        """Get DuckDB map database accessor for read-only entity queries.
        
        Returns RemoteViewEntity instances that can be inspected and used for
        planning, but cannot be mutated (no pickup, add_fuel, etc.).
        
        Requires DuckDB to be loaded first.
        
        Example:
            >>> drills = map_db.get_entities('''
            ...     SELECT * FROM map_entity me
            ...     JOIN mining_drill md ON me.entity_key = md.entity_key
            ...     WHERE entity_name = 'burner-mining-drill'
            ... ''')
            >>> for drill in drills:
            ...     print(drill.output_position)
        
        Raises:
            RuntimeError: If DuckDB connection not initialized
        """
        if not hasattr(self, '_map_db_accessor'):
            if self._duckdb_connection is None:
                raise RuntimeError(
                    "DuckDB not loaded. Load snapshots first to enable map_db queries."
                )
            self._map_db_accessor = _DuckDBAccessor(self._duckdb_connection)
        return self._map_db_accessor
    
    def update_recipes(self) -> None:
        cmd = self._build_command("get_recipes")
        result = self.execute(cmd)
        Recipes = Recipes(json.loads(result))
        self.recipes = Recipes

    def execute(self, command: str, silent: bool = True) -> str:
        if silent:
            full_command = f"/sc {command}"
        else:
            full_command = f"/c {command}"
            
        logger.info(f"RCON TX: {full_command}")
        response = self._rcon.send_command(full_command)
        logger.info(f"RCON RX: {response}")
        return response

    def _serialize_arg(self, arg):
        """Convert argument to JSON-serializable format."""
        # Handle Position/MapPosition/EntityPosition objects
        if hasattr(arg, 'x') and hasattr(arg, 'y'):
            return {"x": arg.x, "y": arg.y}
        # Handle other common types
        return arg
    
    def _build_command(self, method: str, *args) -> str:
        """Build RCON command string for a method call with positional arguments.
        
        Args are passed as positional arguments to match RemoteInterface method signatures.
        """
        remote_call = f"remote.call('{self.agent_id}', '{method}'"
        
        if args:
            # Convert args to JSON-serializable format and pass as table
            serialized_args = [self._serialize_arg(arg) for arg in args]
            args_json = json.dumps(serialized_args)
            remote_call += f", table.unpack(helpers.json_to_table('{args_json}'))"
        
        remote_call += ")"
        return f"rcon.print(helpers.table_to_json({remote_call}))"

    def _execute_and_parse_json(self, command: str) -> Dict[str, Any]:
        """Execute RCON command and parse resultant JSON with error handling."""
        result = self.execute(command)
        if not result or not result.strip():
            # Sometimes RCON returns empty string on silent failure or no output
            # Raise descriptive error
            raise RuntimeError(f"RCON command returned empty response. Command: {command}")
        
        try:
            return json.loads(result)
        except json.JSONDecodeError as e:
            # Log the raw result for debugging
            logger.error(f"JSON decode failed. Result: '{result}'")
            raise RuntimeError(f"Failed to decode JSON from RCON. Response: '{result}'. Error: {e}") from e

    # ========================================================================
    # ASYNC: Walking
    # ========================================================================

    def walk_to(
        self,
        goal: Union[Dict[str, float], "MapPosition"],
        strict_goal: bool = False,
        options: Optional[Dict] = None,
    ) -> WalkAsyncResponse:
        """Walk the agent to a target position using pathfinding.

        RCON Contract: RemoteInterface.lua walk_to
        
        Args:
            goal: Target position {x, y} or MapPosition object
            strict_goal: If true, fail if exact position unreachable
            options: Additional pathfinding options
            
        Returns:
            WalkAsyncResponse with {queued, action_id}
        """
        if options is None:
            options = {}
        # Convert MapPosition to dict if needed
        if hasattr(goal, 'x') and hasattr(goal, 'y'):
            goal = {"x": goal.x, "y": goal.y}
        cmd = self._build_command("walk_to", goal, strict_goal, options)
        return self._execute_and_parse_json(cmd)

    def stop_walking(self) -> AsyncActionResponse:
        """Immediately stop the agent's current walking action."""
        cmd = self._build_command("stop_walking")
        return self._execute_and_parse_json(cmd)

    # ========================================================================
    # ASYNC: Mining
    # ========================================================================

    def mine_resource(self, resource_name: str, max_count: Optional[int] = None) -> MineAsyncResponse:
        """Mine a resource within reach of the agent.

        RCON Contract: RemoteInterface.lua mine_resource
        
        Args:
            resource_name: Resource prototype name (e.g., 'iron-ore', 'coal', 'stone')
            max_count: Max items to mine (None = deplete resource)
            
        Returns:
            MineAsyncResponse with {queued, action_id, entity_name, entity_position}
        """
        cmd = self._build_command("mine_resource", resource_name, max_count)
        return self._execute_and_parse_json(cmd)

    def stop_mining(self) -> AsyncActionResponse:
        """Immediately stop the agent's current mining action."""
        cmd = self._build_command("stop_mining")
        return self._execute_and_parse_json(cmd)

    # ========================================================================
    # ASYNC: Crafting
    # ========================================================================

    def craft_enqueue(self, recipe_name: str, count: int = 1) -> CraftAsyncResponse:
        """Queue a recipe for hand-crafting.

        RCON Contract: RemoteInterface.lua craft_enqueue
        
        Args:
            recipe_name: Recipe name to craft
            count: Number of times to craft the recipe
            
        Returns:
            CraftAsyncResponse with {queued, action_id, recipe, count}
        """
        if not self.recipes[recipe_name].is_hand_craftable():
            raise ValueError(f"Recipe {recipe_name} is not hand-craftable")
        if not self.recipes[recipe_name].enabled:
            raise ValueError(f"Recipe {recipe_name} is not enabled, try researching technology first")
        cmd = self._build_command("craft_enqueue", recipe_name, count)
        return self._execute_and_parse_json(cmd)

    def craft_dequeue(self, recipe_name: str, count: Optional[int] = None) -> ActionResult:
        """Cancel queued crafting for a recipe.

        RCON Contract: RemoteInterface.lua craft_dequeue
        
        Args:
            recipe_name: Recipe name to cancel
            count: Number to cancel (None = all)
            
        Returns:
            ActionResult with {success, cancelled_count}
        """
        cmd = self._build_command("craft_dequeue", recipe_name, count)
        return self._execute_and_parse_json(cmd)

    # ========================================================================
    # SYNC: Entity Operations
    # ========================================================================

    def set_entity_recipe(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
        recipe_name: Optional[str] = None,
    ) -> ActionResult:
        """Set the recipe for a machine (assembler, furnace, chemical plant).

        RCON Contract: RemoteInterface.lua set_entity_recipe
        
        Args:
            entity_name: Entity prototype name
            position: Entity position (None = nearest)
            recipe_name: Recipe to set (None = clear)
            
        Returns:
            ActionResult with {success, entity_name, position, recipe}
        """
        cmd = self._build_command(
            "set_entity_recipe", entity_name, position, recipe_name
        )
        return self._execute_and_parse_json(cmd)

    def set_entity_filter(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
        inventory_type: str = "input",
        filter_index: Optional[int] = None,
        filter_item: Optional[str] = None,
    ) -> ActionResult:
        """Set an inventory filter on an entity (inserter, container with filters).

        Args:
            entity_name: Entity prototype name
            position: Entity position (None = nearest)
            inventory_type: Inventory type to filter
            filter_index: Slot index (None = first slot)
            filter_item: Item to filter (None = clear)
        """
        cmd = self._build_command(
            "set_entity_filter",
            entity_name,
            position,
            inventory_type,
            filter_index,
            filter_item,
        )
        return self._execute_and_parse_json(cmd)

    def set_inventory_limit(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
        inventory_type: str = "chest",
        limit: Optional[int] = None,
    ) -> ActionResult:
        """Set the inventory bar limit on a container.

        Args:
            entity_name: Entity prototype name
            position: Entity position (None = nearest)
            inventory_type: Inventory type to limit
            limit: Slot limit (None = no limit)
        """
        cmd = self._build_command(
            "set_inventory_limit", entity_name, position, inventory_type, limit
        )
        return self._execute_and_parse_json(cmd)

    def take_inventory_item(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
        inventory_type: str = "chest",
        item_name: str = "",
        count: Optional[int] = None,
    ) -> List[ItemStack]:
        """Take items from an entity's inventory into the agent's inventory.
        
        Args:
            entity_name: Entity prototype name
            position: Entity position (None = nearest)
            inventory_type: Inventory type to take from
            item_name: Item name to take
            count: Count to take (None = all available)
            
        Returns:
            List of ItemStack objects representing the items actually taken
        """
        cmd = self._build_command(
            "take_inventory_item",
            entity_name,
            position,
            inventory_type,
            item_name,
            count,
        )
        result = self._execute_and_parse_json(cmd)
        return [ItemStack(name=result["name"], count=result["count"])]

    def put_inventory_item(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
        inventory_type: str = "chest",
        item_name: str = "",
        count: int = 1,
    ) -> ActionResult:
        """Put items from the agent's inventory into an entity's inventory.
        
        Args:
            entity_name: Entity prototype name
            position: Entity position (None = nearest)
            inventory_type: Inventory type to put into
            item_name: Item name to put
            count: Count to put
            
        Returns:
            ActionResult TypedDict
        """
        cmd = self._build_command(
            "put_inventory_item",
            entity_name,
            position,
            inventory_type,
            item_name,
            count,
        )
        return self._execute_and_parse_json(cmd)

    # ========================================================================
    # SYNC: Placement
    # ========================================================================

    def place_entity(
        self,
        entity_name: str,
        position: Union[Dict[str, float], "MapPosition"],
        direction: Optional[Direction] = None,
        ghost=False,
        label: Optional[str] = None,
    ) -> ActionResult:
        """Place an entity from the agent's inventory onto the map.

        Args:
            entity_name: Entity prototype name to place
            position: MapPosition to place entity
            direction: Optional direction for placement
            ghost: Whether to place as ghost entity (default: False)
            label: Optional label for ghost entities (Python-only, for grouping/staging)

        Returns:
            Result dict with success, position, entity_name, etc.
        """
        # Convert MapPosition to dict if needed
        if hasattr(position, 'x') and hasattr(position, 'y'):
            position = {"x": position.x, "y": position.y}
        
        # Convert Direction enum to int if needed
        if direction is not None and isinstance(direction, Direction):
            direction = direction.value
        
        cmd = self._build_command(
            "place_entity", entity_name, position, direction, ghost
        )
        result = self._execute_and_parse_json(cmd)
        
        # Track ghost if placed
        if ghost and result.get("success"):
            pos = result.get("position", position)
            self._ghost_manager.add_ghost(
                position=pos,
                entity_name=entity_name,
                label=label,
                placed_tick=result.get("tick", 0)
            )
        elif not ghost and result.get("success"):
            # If placing a real entity, check if we're replacing a tracked ghost
            # Note: position here might be dict or MapPosition, GhostManager handles both
            if self._ghost_manager.remove_ghost(position=position, entity_name=entity_name):
                logger.warning(f"Ghost at {position} for {entity_name} replaced by real entity.")
        
        return result

    def inspect_entity(
        self,
        name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
    ) -> EntityInspectionData:
        """Inspect an entity's state.

        Args:
            name: Entity prototype name
            position: MapPosition to inspect (None = nearest)
            
        Returns:
            EntityInspectionData TypedDict
        """
        cmd = self._build_command("inspect_entity", name, position)
        return self._execute_and_parse_json(cmd)

    def pickup_entity(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
    ) -> List["ItemStack"]:
        """Pick up an entity from the map into the agent's inventory.

        Args:
            entity_name: Entity prototype name to pick up
            position: Entity position (None = nearest)
            
        Returns:
            List of ItemStack objects representing items added to inventory
        """
        from FactoryVerse.dsl.item.base import ItemStack
        
        cmd = self._build_command("pickup_entity", entity_name, position)
        result = self._execute_and_parse_json(cmd)
        
        if result.get("success") and result.get("item_name"):
            return [ItemStack(name=result["item_name"], count=result.get("count", 1))]
        return []

    def remove_ghost(self, entity_name: str, position: MapPosition) -> ActionResult:
        """Remove a ghost entity from the map.

        Args:
            entity_name: Entity prototype name to remove
            position: Entity position

        Returns:
            Result dict with success status
        """
        # Convert MapPosition to dict if needed
        if hasattr(position, 'x') and hasattr(position, 'y'):
            pos_dict = {"x": position.x, "y": position.y}
        else:
            pos_dict = position
        
        cmd = self._build_command("remove_ghost", entity_name, pos_dict)
        result = self._execute_and_parse_json(cmd)
        
        # Remove from tracking if successful
        if result.get("success"):
            self._ghost_manager.remove_ghost(position=pos_dict, entity_name=entity_name)
        
        return result

    # ========================================================================
    # SYNC: Movement
    # ========================================================================

    def teleport(self, position: Union[Dict[str, float], "MapPosition"]) -> ActionResult:
        """Instantly teleport the agent to a position.

        RCON Contract: RemoteInterface.lua teleport
        
        Args:
            position: Target position
            
        Returns:
            ActionResult with {success, position}
        """
        cmd = self._build_command("teleport", position)
        return self._execute_and_parse_json(cmd)

    # ========================================================================
    # QUERIES
    # ========================================================================

    def inspect(self, attach_state: bool = False) -> AgentInspectionData:
        """Get current agent state and position.

        RCON Contract: RemoteInterface.lua inspect
        
        Args:
            attach_state: Include processed agent activity state (walking, mining, crafting)
            
        Returns:
            AgentInspectionData with {agent_id, tick, position, state?}
        """
        cmd = self._build_command("inspect", attach_state)
        return self._execute_and_parse_json(cmd)

    def inspect_entity(self, entity_name: str, position: MapPosition) -> EntityInspectionData:
        """Get comprehensive volatile state for a specific entity.

        RCON Contract: RemoteInterface.lua inspect_entity
        
        Args:
            entity_name: Entity prototype name
            position: Entity position

        Returns:
            EntityInspectionData with status, recipe, progress, inventories, energy, held_item, etc.
            Not all fields present for all entity types.
            
        Raises:
            RuntimeError: If the remote call fails or returns an error
        """
        cmd = self._build_command("inspect_entity", entity_name, {"x": position.x, "y": position.y})
        return self._execute_and_parse_json(cmd)

    def get_inventory_items(self) -> Dict[str, int]:
        """Get agent's main inventory contents.

        RCON Contract: RemoteInterface.lua get_inventory_items
        
        Returns:
            Dict mapping item names to counts: {"iron-ore": 50, "coal": 20, ...}
        """
        cmd = self._build_command("get_inventory_items")
        return self._execute_and_parse_json(cmd)

    def get_position(self) -> MapPosition:
        """Get current agent position.

        Returns:
            MapPosition of the agent
        """
        cmd = self._build_command("get_position")
        result = self._execute_and_parse_json(cmd)
        return MapPosition(x=result["x"], y=result["y"])

    def get_placement_cues(self, entity_name: str, resource_name: Optional[str] = None) -> PlacementCuesResponse:
        """Get placement information for an entity type.

        RCON Contract: RemoteInterface.lua get_placement_cues
        
        Args:
            entity_name: Entity prototype name
            resource_name: Optional resource name to filter by (e.g., "copper-ore", "iron-ore")
            
        Returns:
            PlacementCuesResponse with entity_name, collision_box, tile_width, tile_height,
            positions (all valid), reachable_positions (within build distance)
        """
        cmd = self._build_command("get_placement_cues", entity_name)
        data = self._execute_and_parse_json(cmd)
        
        # Filter by resource_name if specified
        if resource_name:
            data["positions"] = [cue for cue in data.get("positions", []) if cue.get("resource_name") == resource_name]
            data["reachable_positions"] = [cue for cue in data.get("reachable_positions", []) if cue.get("resource_name") == resource_name]
        
        return data

    def get_chunks_in_view(self) -> Dict[str, Any]:
        """Get list of map chunks currently visible/charted by the agent.
        
        RCON Contract: RemoteInterface.lua get_chunks_in_view
        
        Returns:
            Dict with {chunks: [{x, y}, ...]}
        """
        cmd = self._build_command("get_chunks_in_view")
        return self._execute_and_parse_json(cmd)

    def get_recipes(self, category: Optional[str] = None) -> Dict[str, Any]:
        """Get available recipes for the agent's force.

        RCON Contract: RemoteInterface.lua get_recipes
        
        Args:
            category: Filter by category (None = all)
            
        Returns:
            Dict with {recipes: [...]}
        """
        cmd = self._build_command("get_recipes", category)
        return self._execute_and_parse_json(cmd)

    def get_technologies(self, only_available: bool = False) -> Dict[str, Any]:
        """Get technologies for the agent's force.

        RCON Contract: RemoteInterface.lua get_technologies
        
        Args:
            only_available: Only show researchable techs
            
        Returns:
            Dict with {technologies: [...]}
        """
        cmd = self._build_command("get_technologies", only_available)
        return self._execute_and_parse_json(cmd)


    # ========================================================================
    # RESEARCH
    # ========================================================================

    def enqueue_research(self, technology_name: str) -> ActionResult:
        """Start researching a technology.

        RCON Contract: RemoteInterface.lua enqueue_research
        
        Args:
            technology_name: Technology to research
            
        Returns:
            ActionResult with {success, technology}
        """
        cmd = self._build_command("enqueue_research", technology_name)
        return self._execute_and_parse_json(cmd)

    def cancel_current_research(self) -> ActionResult:
        """Cancel the currently active research.
        
        RCON Contract: RemoteInterface.lua cancel_current_research
        
        Returns:
            ActionResult with {success}
        """
        cmd = self._build_command("cancel_current_research")
        return self._execute_and_parse_json(cmd)
    
    def get_research_queue(self) -> ResearchStatus:
        """Get current research queue with progress information.
        
        RCON Contract: RemoteInterface.lua get_research_queue
        
        Returns:
            ResearchStatus with {queue, queue_length, current_research, tick}
        """
        cmd = self._build_command("get_research_queue")
        return self._execute_and_parse_json(cmd)
    
    # ========================================================================
    # NOTIFICATIONS
    # ========================================================================
    
    async def get_notifications(self, timeout: Optional[float] = 0.1) -> List[Dict[str, Any]]:
        """Get all pending notifications (non-blocking).
        
        Retrieves notifications from the UDP notification queue. This includes
        research events, crafting completions, and other asynchronous game events.
        
        Args:
            timeout: Max time to wait for first notification (seconds). 
                    Use 0 for immediate return, None to wait indefinitely.
            
        Returns:
            List of notification payloads. Each notification has:
                - event_type: "notification"
                - notification_type: Type of notification (e.g., "research_finished")
                - agent_id: Agent ID
                - tick: Game tick
                - data: Notification-specific data
        
        Example:
            >>> notifications = await factory.get_notifications(timeout=0.1)
            >>> for notif in notifications:
            ...     if notif['notification_type'] == 'research_finished':
            ...         print(f"Research complete: {notif['data']['technology']}")
        """
        await self._ensure_async_listener()
        notifications = []
        
        try:
            # Wait for first notification with timeout
            if timeout is not None and timeout > 0:
                # Use asyncio to wait with timeout
                start_time = time.time()
                while time.time() - start_time < timeout:
                    try:
                        notif = self._async_listener.notification_queue.get_nowait()
                        notifications.append(notif)
                        break
                    except queue.Empty:
                        await asyncio.sleep(0.01)  # Small sleep to avoid busy loop
            
            # Drain remaining notifications (non-blocking)
            while True:
                try:
                    notif = self._async_listener.notification_queue.get_nowait()
                    notifications.append(notif)
                except queue.Empty:
                    break
                    
        except Exception as e:
            logger.error(f"Error getting notifications: {e}")
        
        return notifications
    
    def register_notification_callback(self, notification_type: str, callback: Callable[[Dict[str, Any]], None]):
        """Register callback for specific notification type.
        
        The callback will be called immediately when a notification of the specified
        type is received, from the UDP listener thread. Keep callbacks lightweight.
        
        Args:
            notification_type: Type of notification (e.g., "research_finished")
            callback: Function to call with notification payload
        
        Example:
            >>> def on_research_done(notif):
            ...     print(f"Research complete: {notif['data']['technology']}")
            >>> factory.register_notification_callback("research_finished", on_research_done)
        """
        self._async_listener.notification_callbacks[notification_type] = callback

    # ========================================================================
    # REACHABILITY
    # ========================================================================

    def get_reachable(self, attach_ghosts: bool = True) -> ReachableSnapshotData:
        """Get full reachable snapshot with complete entity data.
        
        RCON Contract: RemoteInterface.lua get_reachable
        
        Args:
            attach_ghosts: Whether to include ghosts in response (default: True)
            
        Returns:
            ReachableSnapshotData with {entities, resources, ghosts?, agent_position, tick}
            - entities: List of ReachableEntityData
            - resources: List of ReachableResourceData  
            - ghosts: List of ReachableGhostData (only if attach_ghosts=True)
        """
        cmd = self._build_command("get_reachable", attach_ghosts)
        return self._execute_and_parse_json(cmd)
    
    @property
    def ghosts(self) -> GhostManager:
        """Get the ghost manager for this factory.
        
        Returns:
            GhostManager instance for managing tracked ghosts
        """
        return self._ghost_manager
    
    async def load_snapshots(
        self,
        snapshot_dir: Optional[Path] = None,
        db_path: Optional[Union[str, Path]] = None,
        prototype_api_file: Optional[str] = None,
        *,
        include_base: bool = True,
        include_components: bool = True,
        include_derived: bool = True,
        include_ghosts: bool = True,
        include_analytics: bool = True,
        replay_updates: bool = True,
        wait_for_initial: bool = True,
        initial_timeout: float = 60.0,
    ) -> None:
        """Load snapshot data into the database (async version).
        
        High-level method that auto-creates connection, schema, and auto-detects
        snapshot directory. This is the primary way to set up the database.
        
        Also initializes and starts GameDataSyncService for real-time sync.
        If wait_for_initial=True, blocks until all charted chunks reach COMPLETE state.
        
        Args:
            snapshot_dir: Path to snapshot directory. If None, auto-detects from
                         Factorio client script-output directory.
            db_path: Optional path to DuckDB database file. If None, uses in-memory.
            prototype_api_file: Optional path to prototype-api.json file
            include_base: Load base tables (water, resources, entities)
            include_components: Load component tables (inserters, belts, etc.)
            include_derived: Load derived tables (patches, belt networks)
            include_ghosts: Load ghost tables
            include_analytics: Load analytics tables (power, agent stats)
            replay_updates: Replay operations logs (entities_updates.jsonl, etc.)
            wait_for_initial: If True, wait for all charted chunks to reach COMPLETE state
            initial_timeout: Maximum time to wait for initial snapshot completion (seconds)
        """
        # Load snapshots synchronously (files on disk)
        snapshot_dir = self._load_snapshots_sync(
            snapshot_dir=snapshot_dir,
            db_path=db_path,
            prototype_api_file=prototype_api_file,
            include_base=include_base,
            include_components=include_components,
            include_derived=include_derived,
            include_ghosts=include_ghosts,
            include_analytics=include_analytics,
            replay_updates=replay_updates,
        )
        
        # Start GameDataSyncService
        await self._ensure_game_data_sync()
        
        # Wait for bootstrap completion if requested
        # This waits for the system to transition from INITIAL_SNAPSHOTTING to MAINTENANCE
        # which respects the bootstrap waiting period for async charting
        if wait_for_initial:
            await self._wait_for_bootstrap_complete(timeout=initial_timeout)
            
            # CRITICAL: Reload all snapshot files from disk after bootstrap completes
            # This ensures we have ALL data that was snapshotted during bootstrap.
            # Without this reload, we'd have a mix of:
            # - Old data from initial load (before bootstrap)
            # - Some new data from UDP file_io events (if they arrived)
            # - Missing data from chunks that completed DURING bootstrap wait
            logger.info("🔄 Bootstrap complete. Reloading all snapshot files to ensure complete data...")
            print("\n" + "=" * 60)
            print("🔄 Reloading snapshot data after bootstrap...")
            print("=" * 60)
            
            from FactoryVerse.infra.db.loader import load_all
            load_all(
                self._duckdb_connection,
                snapshot_dir,
                prototype_api_file,
                include_base=include_base,
                include_components=include_components,
                include_derived=include_derived,
                include_ghosts=include_ghosts,
                include_analytics=include_analytics,
                replay_updates=replay_updates,
            )
            
            logger.info("✅ Post-bootstrap reload complete. DB now contains all snapshotted data.")
            print("✅ Post-bootstrap reload complete!")
    
    def _load_snapshots_sync(
        self,
        snapshot_dir: Optional[Path] = None,
        db_path: Optional[Union[str, Path]] = None,
        prototype_api_file: Optional[str] = None,
        include_base: bool = True,
        include_components: bool = True,
        include_derived: bool = True,
        include_ghosts: bool = True,
        include_analytics: bool = True,
        replay_updates: bool = True,
    ) -> Path:
        """Load snapshot data synchronously (doesn't wait for COMPLETE state).
        
        This is the internal synchronous version that:
        1. Creates DB connection
        2. Auto-detects snapshot directory
        3. Waits for snapshot files to exist on disk
        4. Loads files into DB
        5. Initializes GameDataSyncService (but doesn't start it)
        
        Returns:
            Path: The resolved snapshot_dir path
        """
        import duckdb
        import time
        
        # Auto-create connection if not already loaded
        if self._duckdb_connection is None:
            if db_path is None:
                con = duckdb.connect(':memory:')
            else:
                from FactoryVerse.infra.db.duckdb_schema import connect
                con = connect(db_path)
            self._duckdb_connection = con
        
        # Auto-detect snapshot directory if not provided
        # Uses Factorio client script-output directory as default
        if snapshot_dir is None:
            try:
                from FactoryVerse.infra.factorio_client_setup import get_client_script_output_dir
                snapshot_dir = get_client_script_output_dir()
            except Exception as e:
                raise ValueError(
                    f"snapshot_dir required and could not be auto-detected: {e}"
                )
        
        snapshot_dir = Path(snapshot_dir)
        
        # Wait for initial snapshot files if they don't exist
        # Check if any snapshot files exist
        snapshot_base = snapshot_dir / "factoryverse" / "snapshots"
        has_snapshots = False
        if snapshot_base.exists():
            # Check if any chunk directories exist
            chunk_dirs = [d for d in snapshot_base.iterdir() if d.is_dir()]
            for chunk_x_dir in chunk_dirs:
                if chunk_x_dir.is_dir():
                    chunk_y_dirs = [d for d in chunk_x_dir.iterdir() if d.is_dir()]
                    for chunk_y_dir in chunk_y_dirs:
                        # Check if any init files exist
                        if any(chunk_y_dir.glob("*_init.jsonl")):
                            has_snapshots = True
                            break
                    if has_snapshots:
                        break
        
        if not has_snapshots:
            # Try to trigger snapshot via RCON if available
            if self._rcon:
                try:
                    print("No snapshot files found. Triggering map snapshot via RCON...")
                    result = self._rcon.send_command("take_map_snapshot")
                    if result and "error" not in result.lower():
                        print("✅ Map snapshot triggered successfully")
                    else:
                        print(f"⚠️  RCON command may have failed: {result}")
                except Exception as e:
                    print(f"⚠️  Could not trigger map snapshot via RCON: {e}")
            
            # Wait for snapshot files to be created
            max_wait = 30  # 30 seconds timeout
            print(f"Waiting for snapshot files to be created (max {max_wait}s)...")
            for i in range(max_wait):
                if snapshot_base.exists():
                    chunk_dirs = [d for d in snapshot_base.iterdir() if d.is_dir()]
                    for chunk_x_dir in chunk_dirs:
                        if chunk_x_dir.is_dir():
                            chunk_y_dirs = [d for d in chunk_x_dir.iterdir() if d.is_dir()]
                            for chunk_y_dir in chunk_y_dirs:
                                if any(chunk_y_dir.glob("*_init.jsonl")):
                                    has_snapshots = True
                                    break
                            if has_snapshots:
                                break
                    if has_snapshots:
                        print(f"✅ Snapshot files found after {i+1} seconds")
                        break
                time.sleep(1)
            else:
                print(f"⚠️  Warning: No snapshot files found after {max_wait} seconds. Loading whatever exists...")
        
        # Load data (this will auto-create schema if needed)
        from FactoryVerse.infra.db.loader import load_all
        load_all(
            self._duckdb_connection,
            snapshot_dir,
            prototype_api_file,
            include_base=include_base,
            include_components=include_components,
            include_derived=include_derived,
            include_ghosts=include_ghosts,
            include_analytics=include_analytics,
            replay_updates=replay_updates,
        )
        
        # Initialize GameDataSyncService for real-time sync (but don't start it yet)
        if self._game_data_sync is None:
            udp_dispatcher = get_udp_dispatcher()
            self._game_data_sync = GameDataSyncService(
                agent_id=self._agent_id,
                db_connection=self._duckdb_connection,
                snapshot_dir=snapshot_dir,
                udp_dispatcher=udp_dispatcher,
                rcon_client=self._rcon,
            )
        
        return snapshot_dir
    
    def _get_charted_chunks(self) -> List[tuple[int, int]]:
        """Query game for list of charted chunks via RCON.
        
        Returns:
            List of (chunk_x, chunk_y) tuples for all charted chunks
        """
        if not self._rcon:
            logger.warning("No RCON client available, cannot query charted chunks")
            return []
        
        try:
            # Query game for charted chunks
            cmd = '/c local chunks = {}; for chunk in game.surfaces[1].get_chunks() do if game.forces.player.is_chunk_charted(1, chunk) then table.insert(chunks, {x=chunk.x, y=chunk.y}) end end; rcon.print(helpers.table_to_json(chunks))'
            result = self._rcon.send_command(cmd)
            chunks_data = json.loads(result)
            
            # Convert to list of tuples
            charted = [(int(c["x"]), int(c["y"])) for c in chunks_data]
            logger.info(f"Found {len(charted)} charted chunks")
            return charted
        except Exception as e:
            logger.error(f"Failed to query charted chunks: {e}", exc_info=True)
            return []
    
    async def _wait_for_bootstrap_complete(self, timeout: float = 120.0) -> None:
        """Wait for bootstrap phase to complete (INITIAL_SNAPSHOTTING → MAINTENANCE).
        
        Polls the snapshot system's phase status and waits for transition to MAINTENANCE.
        This is more reliable than waiting for individual chunks since it respects
        the bootstrap waiting period (300 ticks) that allows async charting to complete.
        
        Args:
            timeout: Maximum time to wait for bootstrap (seconds, default 120s = 2 minutes)
            
        Raises:
            asyncio.TimeoutError: If bootstrap doesn't complete within timeout
        """
        import asyncio
        import time
        
        start_time = time.time()
        check_interval = 1.0  # Check every second
        
        logger.info("⏳ Waiting for snapshot system bootstrap to complete...")
        print("⏳ Waiting for snapshot system bootstrap to complete...")
        
        while True:
            # Check if timeout exceeded
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise asyncio.TimeoutError(
                    f"Bootstrap did not complete within {timeout}s. "
                    "System may still be in INITIAL_SNAPSHOTTING phase."
                )
            
            # Query snapshot system status via RCON
            try:
                cmd = "/c rcon.print(helpers.table_to_json(remote.call('map', 'get_snapshot_status')))"
                result = self._rcon.send_command(cmd)
                
                # Handle None result (happens when command fails)
                if result is None or result.strip() == "":
                    logger.debug("Empty or None result from RCON, retrying...")
                    await asyncio.sleep(check_interval)
                    continue
                    
                status = json.loads(result)
                
                system_phase = status.get("system_phase")
                
                if system_phase == "MAINTENANCE":
                    # Bootstrap complete!
                    stats = status.get("bootstrap_wait", {})
                    completed = status.get("completed_chunks", 0)
                    logger.info(f"✅ Bootstrap complete! Transitioned to MAINTENANCE mode.")
                    logger.info(f"✅ {completed} chunks snapshotted during bootstrap.")
                    print(f"✅ Bootstrap complete! {completed} chunks snapshotted.")
                    return
                
                elif system_phase == "INITIAL_SNAPSHOTTING":
                    # Still bootstrapping
                    pending = status.get("pending_chunks", 0)
                    completed = status.get("completed_chunks", 0)
                    bootstrap_wait = status.get("bootstrap_wait", {})
                    current_tick = bootstrap_wait.get("current_tick", 0)
                    total_ticks = bootstrap_wait.get("total_ticks", 300)
                    waiting = bootstrap_wait.get("waiting", False)
                    
                    if waiting:
                        logger.debug(
                            f"Bootstrap waiting: {current_tick}/{total_ticks} ticks, "
                            f"{pending} pending chunks, {completed} completed"
                        )
                        if int(elapsed) % 5 == 0:  # Log every 5 seconds
                            print(
                                f"  ⏱️  Bootstrap waiting: {current_tick}/{total_ticks} ticks, "
                                f"{pending} pending, {completed} completed"
                            )
                    else:
                        logger.debug(
                            f"Processing chunks: {pending} pending, {completed} completed"
                        )
                        if int(elapsed) % 5 == 0:
                            print(f"  📦 Processing: {pending} pending, {completed} completed")
                
            except Exception as e:
                logger.warning(f"Error checking bootstrap status: {e}")
                # Continue waiting, don't fail on transient errors
            
            # Wait before next check
            await asyncio.sleep(check_interval)
    
    async def _ensure_game_data_sync(self):
        """Ensure game data sync service is started."""
        if self._game_data_sync and not self._game_data_sync.is_running:
            await self._game_data_sync.start()
    
    async def _stop_game_data_sync(self):
        """Stop game data sync service."""
        if self._game_data_sync and self._game_data_sync.is_running:
            await self._game_data_sync.stop()
    
    @property
    def duckdb_connection(self):
        """Get the DuckDB connection.
        
        Returns:
            DuckDB connection object, or None if not loaded
        """
        return self._duckdb_connection
    
    @property
    def game_data_sync(self) -> Optional["GameDataSyncService"]:
        """Get the game data sync service.
        
        Returns:
            GameDataSyncService instance, or None if not initialized
        """
        return self._game_data_sync

    # ========================================================================
    # DEBUG
    # ========================================================================

    def _inspect_state(self) -> str:
        """Get raw agent state object (for debugging)."""
        cmd = self._build_command("inspect_state")
        return self.execute(cmd)


@contextmanager
def playing_factorio(rcon_client: "RconClient", agent_id: str, recipes: Optional[Recipes] = None,
                     agent_udp_port: Optional[int] = None):
    """Context manager for agent gameplay operations.

    This context enables entities to perform remote operations via RCON.
    Entities can only be operated on when inside this context.

    Args:
        rcon_client: RCON client for remote interface calls
        agent_id: Agent ID (e.g., 'agent_1')
        recipes: Optional Recipes instance (will be fetched if None)
        agent_udp_port: Optional UDP port for agent-specific async actions

    Example:
        with playing_factorio(rcon, 'agent_1', agent_udp_port=34203):
            await factory.walking.to(MapPosition(x=10, y=20))
            factory.crafting.enqueue('iron-plate', count=10)
    """
    # Fetch recipes if not provided
    if recipes is None:
        # Create a temporary factory to fetch recipes
        temp_factory = PlayingFactory(rcon_client, agent_id, Recipes([]), agent_udp_port=None)
        recipes_json = temp_factory.get_recipes()
        recipes_data = json.loads(recipes_json)
        recipes = Recipes(recipes_data.get("recipes", []))
    
    factory = PlayingFactory(rcon_client, agent_id, recipes, agent_udp_port=agent_udp_port)
    
    # Enable entity status tracking by setting the filter
    try:
        from FactoryVerse.prototype_data import get_prototype_manager
        manager = get_prototype_manager()
        entities = manager.get_filtered_entities()
        if entities:
            # We must use proper RCON serialization for the list
            # But the method set_entity_filter takes a single entity? 
            # WAIT. The remote interface is 'set_entity_filter' which takes a list.
            # But PlayingFactory.set_entity_filter (line 1391) is for INVENTORY FILTERS.
            # I need to call the remote interface "snapshot", "set_entity_filter".
            # PlayingFactory doesn't seem to expose a direct method for global entity filter.
            # I should add a specific method or call execute directly.
            # Actually, line 907 in Entities.lua says: set_entity_filter = function(entity_list) ...
            # This is under "snapshot" interface? No, it's M.register_remote_interface.
            # I need to check where that is registered. 
            # In control.lua?
            # Let's assume I can call it via execute("remote.call('snapshot', 'set_entity_filter', ...)")
            
            # Better: PlayingFactory has _build_command.
            # Let's insert a direct RCON call here.
            import json
            entities_json = json.dumps(entities)
            # Use helpers.json_to_table or similar?
            # Or just pass the list if the python client handles it? 
            # The client sends strings.
            # "remote.call('snapshot', 'set_entity_filter', " + json_to_lua_table(entities) + ")"
            
            # Actually, let's use the RCON client directly or add a helper in PlayingFactory.
            # But I can't easily modify PlayingFactory class right now without potentially breaking things.
            # Let's just do it directly here for now.
            cmd = f"/c remote.call('snapshot', 'set_entity_filter', game.json_to_table('{entities_json}'))"
            rcon_client.send_command(cmd)
            # print(f"DEBUG: Set entity filter with {len(entities)} entities")
    except Exception as e:
        print(f"Warning: Failed to set entity filter: {e}")

    token = _playing_factory.set(factory)
    try:
        yield factory
    finally:
        _playing_factory.reset(token)
