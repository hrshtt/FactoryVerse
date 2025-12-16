from __future__ import annotations
import json
import asyncio
import time
import logging
import socket
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Union, List, Literal, TYPE_CHECKING

logger = logging.getLogger(__name__)

from src.FactoryVerse.dsl.types import MapPosition
from src.FactoryVerse.dsl.item.base import ItemStack
from src.FactoryVerse.dsl.recipe.base import Recipes, BaseRecipe, BasicRecipeName
from factorio_rcon import RCONClient as RconClient
from contextvars import ContextVar
from contextlib import contextmanager
from src.FactoryVerse.dsl.types import Direction, MapPosition, BoundingBox
from src.FactoryVerse.infra.udp_dispatcher import UDPDispatcher, get_udp_dispatcher
from src.FactoryVerse.dsl.ghosts import GhostManager
from src.FactoryVerse.infra.game_data_sync import GameDataSyncService

if TYPE_CHECKING:
    import duckdb

if TYPE_CHECKING:
    from src.FactoryVerse.dsl.item.base import Item, PlaceableItem
    from src.FactoryVerse.dsl.entity.base import BaseEntity
    import duckdb


# Game context: agent is "playing" the factory game
_playing_factory: ContextVar[Optional["PlayingFactory"]] = ContextVar(
    "playing_factory", default=None
)


class AsyncActionListener:
    """UDP listener for async action completion events.
    
    Can operate in two modes:
    1. Direct UDP listening on agent-specific port (agent_port specified)
    2. Through UDPDispatcher for shared port (udp_dispatcher specified)
    """
    
    def __init__(self, udp_dispatcher: Optional[UDPDispatcher] = None, 
                 agent_port: Optional[int] = None, 
                 host: str = "127.0.0.1",
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
                    # Only process action events (agent-specific)
                    if payload.get('event_type') == 'action':
                        self._handle_udp_message(payload)
                except json.JSONDecodeError as e:
                    logger.warning(f"⚠️  Failed to decode UDP JSON from {addr}: {e}")
                except Exception as e:
                    logger.error(f"❌ Error processing UDP message from {addr}: {e}")
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"❌ Error in direct UDP listener: {e}")
    
    
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
            if not action_id:
                return
            
            # Require status field (no backwards compatibility)
            status = payload.get('status')
            if not status:
                logger.warning(f"UDP message missing required 'status' field: {payload}")
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
        result = self._factory.get_inventory_items()
        inventory_data = json.loads(result)
        
        items = []
        for stack_obj in inventory_data:
            # Default subgroup - could be enhanced to lookup from prototypes
            item_name = stack_obj.get("name")
            count = stack_obj.get("count")
            subgroup = stack_obj.get("subgroup", "raw-material")
            items.append(ItemStack(name=item_name, count=count, subgroup=subgroup))
        
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
        
        from src.FactoryVerse.dsl.item.base import get_item
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
    """
    
    def __init__(self, factory: "PlayingFactory"):
        self._factory = factory
        self._entities_data: Optional[List[Dict]] = None
        self._entities_instances: Optional[List[BaseEntity]] = None
    
    def _ensure_loaded(self):
        """Lazy-load entities data from factory."""
        if self._entities_data is None:
            data = self._factory.get_reachable(attach_ghosts=False)
            self._entities_data = data.get("entities", [])
            # Convert to entity instances
            from src.FactoryVerse.dsl.entity.base import create_entity_from_data
            self._entities_instances = [
                create_entity_from_data(entity_data)
                for entity_data in self._entities_data
            ]
    
    def get_entity(
        self,
        entity_name: str,
        position: Optional[MapPosition] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Optional[BaseEntity]:
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
            First matching BaseEntity instance, or None if not found
        """
        self._ensure_loaded()
        options = options or {}
        
        # Filter by name first
        matches = [
            (inst, data) for inst, data in zip(self._entities_instances, self._entities_data)
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
    ) -> List[BaseEntity]:
        """Get entities matching criteria.
        
        Args:
            entity_name: Optional entity prototype name filter
            options: Optional dict with filters (same as get_entity)
        
        Returns:
            List of matching BaseEntity instances (may be empty)
        """
        self._ensure_loaded()
        options = options or {}
        
        # Start with all entities
        matches = [
            (inst, data) for inst, data in zip(self._entities_instances, self._entities_data)
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
    """
    
    def __init__(self, factory: "PlayingFactory"):
        self._factory = factory
        self._resources_data: Optional[List[Dict]] = None
    
    def _ensure_loaded(self):
        """Lazy-load resources data from factory."""
        if self._resources_data is None:
            data = self._factory.get_reachable(attach_ghosts=False)
            self._resources_data = data.get("resources", [])
    
    def get_resource(
        self,
        resource_name: str,
        position: Optional[MapPosition] = None
    ) -> Optional[Dict[str, Any]]:
        """Get a single resource matching criteria.
        
        Args:
            resource_name: Resource name (e.g., "iron-ore", "tree")
            position: Optional exact position match
        
        Returns:
            Resource data dict, or None if not found
        """
        self._ensure_loaded()
        
        matches = [
            data for data in self._resources_data
            if data.get("name") == resource_name
        ]
        
        if position is not None:
            matches = [
                data for data in matches
                if data.get("position", {}).get("x") == position.x
                and data.get("position", {}).get("y") == position.y
            ]
        
        return matches[0] if matches else None


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
    ) -> Dict[str, Any]:
        """Walk to a position (async/await).
        
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
        """Mine a resource (async/await).
        
        Args:
            resource_name: Resource prototype name
            max_count: Max items to mine (None = deplete resource)
            timeout: Optional timeout in seconds
            
        Returns:
            List of ItemStack objects obtained from mining
        """
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
        """Craft a recipe (async/await).
        
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
        result = self._factory.inspect(attach_state=True)
        state = json.loads(result)
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
    
    def dequeue(self) -> str:
        """Cancel current research."""
        return self._factory.cancel_current_research()
    
    def status(self) -> Dict[str, Any]:
        """Get current research status.
        
        Returns:
            Research state dict
        """
        result = self._factory.get_technologies(only_available=False)
        techs_data = json.loads(result)
        # Find currently researching tech
        for tech in techs_data.get("technologies", []):
            if tech.get("researching", False):
                return tech
        return {}


class PlayingFactory:
    """Represents the agent's active gameplay session with RCON access."""

    _rcon: RconClient
    _agent_id: str
    agent_commands: AgentCommands
    recipes: Recipes
    _async_listener: AsyncActionListener
    _ghost_manager: GhostManager
    _duckdb_connection: Optional["duckdb.DuckDBPyConnection"]
    _game_data_sync: Optional["GameDataSyncService"]

    def __init__(self, rcon_client: "RconClient", agent_id: str, recipes: Recipes, 
                 udp_dispatcher: Optional[UDPDispatcher] = None,
                 agent_udp_port: Optional[int] = None):
        """
        Initialize PlayingFactory.
        
        Args:
            rcon_client: RCON client for remote interface calls
            agent_id: Agent ID (e.g., 'agent_1')
            recipes: Recipes instance
            udp_dispatcher: Optional UDPDispatcher for shared port mode (deprecated, use agent_udp_port instead)
            agent_udp_port: Optional UDP port for agent-specific async actions. If provided, agent owns this port completely.
        """
        self._rcon = rcon_client
        self._agent_id = agent_id
        self.agent_commands = AgentCommands(agent_id)
        self.recipes = recipes
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
    
    async def _await_action(self, response: Dict[str, Any], timeout: Optional[int] = None) -> Dict[str, Any]:
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
                # Add 0.5x buffer for safety
                base_seconds = (estimated_ticks / 60.0)
                calculated_timeout = base_seconds * 1.5
                logger.debug(f"Calculated timeout for {action_id}: {calculated_timeout:.2f}s (from {estimated_ticks} ticks)")
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
    ) -> Dict[str, Any]:
        """Walk the agent to a target position using pathfinding.

        Args:
            goal: Target position {x, y} or MapPosition object
            strict_goal: If true, fail if exact position unreachable
            options: Additional pathfinding options
            
        Returns:
            Response dict with queued status and action_id
        """
        if options is None:
            options = {}
        # Convert MapPosition to dict if needed
        if hasattr(goal, 'x') and hasattr(goal, 'y'):
            goal = {"x": goal.x, "y": goal.y}
        cmd = self._build_command("walk_to", goal, strict_goal, options)
        return self._execute_and_parse_json(cmd)

    def stop_walking(self) -> str:
        """Immediately stop the agent's current walking action."""
        cmd = self._build_command("stop_walking")
        return self.execute(cmd)

    # ========================================================================
    # ASYNC: Mining
    # ========================================================================

    def mine_resource(self, resource_name: str, max_count: Optional[int] = None) -> Dict[str, Any]:
        """Mine a resource within reach of the agent.

        Args:
            resource_name: Resource prototype name (e.g., 'iron-ore', 'coal', 'stone')
            max_count: Max items to mine (None = deplete resource)
            
        Returns:
            Response dict with queued status and action_id
        """
        cmd = self._build_command("mine_resource", resource_name, max_count)
        return self._execute_and_parse_json(cmd)

    def stop_mining(self) -> str:
        """Immediately stop the agent's current mining action."""
        cmd = self._build_command("stop_mining")
        return self.execute(cmd)

    # ========================================================================
    # ASYNC: Crafting
    # ========================================================================

    def craft_enqueue(self, recipe_name: str, count: int = 1) -> Dict[str, Any]:
        """Queue a recipe for hand-crafting.

        Args:
            recipe_name: Recipe name to craft
            count: Number of times to craft the recipe
            
        Returns:
            Response dict with queued status and action_id
        """
        if not self.recipes[recipe_name].is_hand_craftable():
            raise ValueError(f"Recipe {recipe_name} is not hand-craftable")
        if not self.recipes[recipe_name].enabled:
            raise ValueError(f"Recipe {recipe_name} is not enabled, try researching technology first")
        cmd = self._build_command("craft_enqueue", recipe_name, count)
        return self._execute_and_parse_json(cmd)

    def craft_dequeue(self, recipe_name: str, count: Optional[int] = None) -> str:
        """Cancel queued crafting for a recipe.

        Args:
            recipe_name: Recipe name to cancel
            count: Number to cancel (None = all)
        """
        if count is None:
            cmd = self._build_command("craft_dequeue", recipe_name, None)
            return self.execute(cmd)
        cmd = self._build_command("craft_dequeue", recipe_name, count)
        return self.execute(cmd)

    # ========================================================================
    # SYNC: Entity Operations
    # ========================================================================

    def set_entity_recipe(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
        recipe_name: Optional[str] = None,
    ) -> str:
        """Set the recipe for a machine (assembler, furnace, chemical plant).

        Args:
            entity_name: Entity prototype name
            position: Entity position (None = nearest)
            recipe_name: Recipe to set (None = clear)
        """
        cmd = self._build_command(
            "set_entity_recipe", entity_name, position, recipe_name
        )
        return self.execute(cmd)

    def set_entity_filter(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
        inventory_type: str = "input",
        filter_index: Optional[int] = None,
        filter_item: Optional[str] = None,
    ) -> str:
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
        return self.execute(cmd)

    def set_inventory_limit(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
        inventory_type: str = "chest",
        limit: Optional[int] = None,
    ) -> str:
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
        return self.execute(cmd)

    def take_inventory_item(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
        inventory_type: str = "chest",
        item_name: str = "",
        count: Optional[int] = None,
    ) -> str:
        """Take items from an entity's inventory into the agent's inventory.

        Args:
            entity_name: Entity prototype name
            position: Entity position (None = nearest)
            inventory_type: Inventory type to take from
            item_name: Item name to take
            count: Count to take (None = all available)
        """
        cmd = self._build_command(
            "take_inventory_item",
            entity_name,
            position,
            inventory_type,
            item_name,
            count,
        )
        return self.execute(cmd)

    def put_inventory_item(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
        inventory_type: str = "chest",
        item_name: str = "",
        count: int = 1,
    ) -> str:
        """Put items from the agent's inventory into an entity's inventory.

        Args:
            entity_name: Entity prototype name
            position: Entity position (None = nearest)
            inventory_type: Inventory type to put into
            item_name: Item name to put
            count: Count to put
        """
        cmd = self._build_command(
            "put_inventory_item",
            entity_name,
            position,
            inventory_type,
            item_name,
            count,
        )
        return self.execute(cmd)

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
    ) -> Dict[str, Any]:
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
        
        cmd = self._build_command(
            "place_entity", entity_name, position, direction, ghost
        )
        result_str = self.execute(cmd)
        result = json.loads(result_str)
        
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
        from src.FactoryVerse.dsl.item.base import ItemStack
        
        cmd = self._build_command("pickup_entity", entity_name, position)
        result = self._execute_and_parse_json(cmd)
        
        # Parse extracted_items into ItemStack objects
        extracted_items = result.get("extracted_items", {})
        item_stacks = []
        for item_name, count in extracted_items.items():
            item_stacks.append(ItemStack(name=item_name, count=count))
        
        return item_stacks

    def remove_ghost(self, entity_name: str, position: MapPosition) -> Dict[str, Any]:
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
        result_str = self.execute(cmd)
        result = json.loads(result_str)
        
        # Remove from tracking if successful
        if result.get("success"):
            self._ghost_manager.remove_ghost(position=pos_dict, entity_name=entity_name)
        
        return result

    # ========================================================================
    # SYNC: Movement
    # ========================================================================

    def teleport(self, position: Union[Dict[str, float], "MapPosition"]) -> str:
        """Instantly teleport the agent to a position.

        Args:
            position: Target position
        """
        cmd = self._build_command("teleport", position)
        return self.execute(cmd)

    # ========================================================================
    # QUERIES
    # ========================================================================

    def inspect(self, attach_state: bool = False) -> str:
        """Get current agent position.

        Args:
            attach_state: Include processed agent activity state (walking, mining, crafting)
        """
        cmd = self._build_command("inspect", attach_state)
        return self.execute(cmd)

    def get_inventory_items(self) -> str:
        """Get agent's main inventory contents.

        Returns:
            JSON string with inventory contents {item_name: count, ...}
        """
        cmd = self._build_command("get_inventory_items")
        return self.execute(cmd)

    def get_position(self) -> MapPosition:
        """Get current agent position.

        Returns:
            MapPosition of the agent
        """
        cmd = self._build_command("get_position")
        result_str = self.execute(cmd)
        result = json.loads(result_str)
        return MapPosition(x=result["x"], y=result["y"])

    def get_placement_cues(self, entity_name: str) -> str:
        """Get placement information for an entity type.

        Args:
            entity_name: Entity prototype name
        """
        cmd = self._build_command("get_placement_cues", entity_name)
        return self.execute(cmd)

    def get_chunks_in_view(self) -> str:
        """Get list of map chunks currently visible/charted by the agent."""
        cmd = self._build_command("get_chunks_in_view")
        return self.execute(cmd)

    def get_recipes(self, category: Optional[str] = None) -> str:
        """Get available recipes for the agent's force.

        Args:
            category: Filter by category (None = all)
        """
        cmd = self._build_command("get_recipes", category)
        return self.execute(cmd)

    def get_technologies(self, only_available: bool = False) -> str:
        """Get technologies for the agent's force.

        Args:
            only_available: Only show researchable techs
        """
        cmd = self._build_command("get_technologies", only_available)
        return self.execute(cmd)


    # ========================================================================
    # RESEARCH
    # ========================================================================

    def enqueue_research(self, technology_name: str) -> str:
        """Start researching a technology.

        Args:
            technology_name: Technology to research
        """
        cmd = self._build_command("enqueue_research", technology_name)
        return self.execute(cmd)

    def cancel_current_research(self) -> str:
        """Cancel the currently active research."""
        cmd = self._build_command("cancel_current_research")
        return self.execute(cmd)

    # ========================================================================
    # REACHABILITY
    # ========================================================================

    def get_reachable(self, attach_ghosts: bool = True) -> Dict[str, Any]:
        """Get full reachable snapshot with complete entity data.
        
        Args:
            attach_ghosts: Whether to include ghosts in response (default: True)
            
        Returns:
            Dict with entities, resources, ghosts (if attach_ghosts=True), agent_position, tick
        """
        cmd = self._build_command("get_reachable", attach_ghosts)
        result = self._execute_and_parse_json(cmd)
        
        return result
    
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
        dump_file: str = "factorio-data-dump.json",
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
            dump_file: Path to Factorio prototype data dump JSON file
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
            dump_file=dump_file,
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
            
            from src.FactoryVerse.infra.db.loader import load_all
            load_all(
                self._duckdb_connection,
                snapshot_dir,
                dump_file,
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
        dump_file: str = "factorio-data-dump.json",
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
                from src.FactoryVerse.infra.db.duckdb_schema import connect
                con = connect(db_path)
            self._duckdb_connection = con
        
        # Auto-detect snapshot directory if not provided
        # Uses Factorio client script-output directory as default
        if snapshot_dir is None:
            try:
                from src.FactoryVerse.infra.factorio_client_setup import get_client_script_output_dir
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
        from src.FactoryVerse.infra.db.loader import load_all
        load_all(
            self._duckdb_connection,
            snapshot_dir,
            dump_file,
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
    token = _playing_factory.set(factory)
    try:
        yield factory
    finally:
        _playing_factory.reset(token)
