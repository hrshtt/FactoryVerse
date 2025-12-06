import json
import asyncio
import time
import logging
from typing import Any, Dict, Optional, Union, List

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


# Game context: agent is "playing" the factory game
_playing_factory: ContextVar[Optional["PlayingFactory"]] = ContextVar(
    "playing_factory", default=None
)


class AsyncActionListener:
    """UDP listener for async action completion events."""
    
    def __init__(self, udp_dispatcher: Optional[UDPDispatcher] = None, timeout: int = 30):
        """
        Initialize the UDP listener.
        
        Args:
            udp_dispatcher: Optional UDPDispatcher instance. If None, uses global dispatcher.
            timeout: Default timeout in seconds for waiting on actions
        """
        self.udp_dispatcher = udp_dispatcher
        self.timeout = timeout
        self.pending_actions: Dict[str, asyncio.Event] = {}
        self.action_results: Dict[str, Dict[str, Any]] = {}
        self.event_loops: Dict[str, asyncio.AbstractEventLoop] = {}
        self.running = False
        
    async def start(self):
        """Subscribe to UDP dispatcher for action completion events."""
        if self.udp_dispatcher is None:
            self.udp_dispatcher = get_udp_dispatcher()
        
        if not self.udp_dispatcher.is_running():
            await self.udp_dispatcher.start()
        
        self.udp_dispatcher.subscribe("*", self._handle_udp_message)
        self.running = True
    
    
    def _handle_udp_message(self, payload: Dict[str, Any]):
        """Process received UDP message from dispatcher (called by dispatcher thread)."""
        logger.info(f"UDP RX: {payload}")
        try:
            action_id = payload.get('action_id')
            if not action_id:
                return
            
            if action_id not in self.pending_actions:
                return
            
            self.action_results[action_id] = payload
            event = self.pending_actions[action_id]
            
            loop = self.event_loops.get(action_id)
            if loop and loop.is_running():
                loop.call_soon_threadsafe(event.set)
            else:
                event.set()
        except Exception as e:
            print(f"❌ Error processing UDP message: {e}")
    
    async def stop(self):
        """Unsubscribe from UDP dispatcher."""
        if self.udp_dispatcher and self.running:
            self.udp_dispatcher.unsubscribe("*", self._handle_udp_message)
        self.running = False
    
    def register_action(self, action_id: str):
        """Register an action to wait for completion via UDP."""
        event = asyncio.Event()
        self.pending_actions[action_id] = event
        self.action_results[action_id] = None
        try:
            self.event_loops[action_id] = asyncio.get_running_loop()
        except RuntimeError:
            self.event_loops[action_id] = None
    
    async def wait_for_action(self, action_id: str, timeout: Optional[int] = None) -> Dict[str, Any]:
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
        
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_secs)
            return self.action_results[action_id]
        except asyncio.TimeoutError:
            raise
        finally:
            self.pending_actions.pop(action_id, None)
            self.action_results.pop(action_id, None)
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
    """Represents the agent's inventory."""

    inventory: List[ItemStack]

    def __init__(self, inventory: List[ItemStack]):
        self.inventory = inventory

    def __getitem__(self, item_name: str) -> int:
        for item in self.inventory:
            if item.name == item_name:
                return item.count
        return 0

    def coal_stacks(self) -> int:
        return [item for item in self.inventory if item.name == "coal"]

    def total(self, item_name: str) -> int:
        return sum(item.count for item in self.inventory if item.name == item_name)

    def get_recipe_stacks(
        self, recipe_name: BasicRecipeName, stack_count: int = 1, strict: bool = False
    ) -> List[ItemStack]:
        recipe = Recipes[recipe_name]

        # Calculate how many stacks can be made for each ingredient
        max_stacks_per_ingredient = []
        for ingredient in recipe.ingredients:
            available_count = self.total(ingredient.name)
            if ingredient.count == 0:
                max_stacks_per_ingredient.append(float("inf"))
            else:
                max_stacks = available_count // ingredient.count
                max_stacks_per_ingredient.append(max_stacks)

        # Find the minimum stack count across all ingredients
        actual_stack_count = (
            min(max_stacks_per_ingredient) if max_stacks_per_ingredient else 0
        )

        if strict:
            if actual_stack_count < stack_count:
                # Find which ingredients are insufficient
                insufficient = []
                for ingredient, max_stacks in zip(
                    recipe.ingredients, max_stacks_per_ingredient
                ):
                    if max_stacks < stack_count:
                        required = ingredient.count * stack_count
                        available = self.total(ingredient.name)
                        insufficient.append(
                            f"{ingredient.name}: required {required}, available {available}"
                        )
                raise ValueError(
                    f"Insufficient ingredients for {stack_count} stacks. "
                    f"Maximum possible: {actual_stack_count} stacks. "
                    f"Insufficient: {', '.join(insufficient)}"
                )
            actual_stack_count = stack_count

        # Use the same stack_count for all ingredients
        required_inputs = []
        for ingredient in recipe.ingredients:
            count = ingredient.count * actual_stack_count
            if count > 0:
                required_inputs.append(ItemStack(name=ingredient.name, count=count))

        return required_inputs


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
    ) -> Dict[str, Any]:
        """Mine a resource (async/await).
        
        Args:
            resource_name: Resource prototype name
            max_count: Max items to mine (None = deplete resource)
            timeout: Optional timeout in seconds
            
        Returns:
            Completion payload
        """
        response = self._factory.mine_resource(resource_name, max_count)
        return await self._factory._await_action(response, timeout=timeout)
    
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
    ) -> Dict[str, Any]:
        """Craft a recipe (async/await).
        
        Args:
            recipe: Recipe name to craft
            count: Number of times to craft
            timeout: Optional timeout in seconds
            
        Returns:
            Completion payload
        """
        response = self._factory.craft_enqueue(recipe, count)
        return await self._factory._await_action(response, timeout=timeout)
    
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
        result = self._factory.get_activity_state()
        state = json.loads(result)
        return state.get("crafting", {})


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
    inventory: List[ItemStack]
    recipes: Recipes
    _async_listener: AsyncActionListener
    _ghost_manager: GhostManager

    def __init__(self, rcon_client: "RconClient", agent_id: str, recipes: Recipes, 
                 udp_dispatcher: Optional[UDPDispatcher] = None):
        self._rcon = rcon_client
        self._agent_id = agent_id
        self.agent_commands = AgentCommands(agent_id)
        self.recipes = recipes
        self._async_listener = AsyncActionListener(udp_dispatcher=udp_dispatcher)
        self._ghost_manager = GhostManager(self)
        
        # Initialize action wrappers
        self._walking = WalkingAction(self)
        self._crafting = CraftingAction(self)
        self._mining = MiningAction(self)
        self._research = ResearchAction(self)
    
    async def _ensure_async_listener(self):
        """Ensure async listener is started."""
        if not self._async_listener.running:
            await self._async_listener.start()
    
    async def _await_action(self, response: Dict[str, Any], timeout: Optional[int] = None) -> Dict[str, Any]:
        """Wait for an async action to complete.
        
        Args:
            response: Response dict from async action (should have action_id)
            timeout: Optional timeout in seconds
            
        Returns:
            Completion payload from UDP
        """
        if not response.get('queued'):
            return response
        
        action_id = response.get('action_id')
        if not action_id:
            return response
        
        await self._ensure_async_listener()
        self._async_listener.register_action(action_id)
        return await self._async_listener.wait_for_action(action_id, timeout=timeout)

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
    def inventory(self) -> List[ItemStack]:
        """Get agent inventory as list of ItemStack objects."""
        cmd = self._build_command("inspect", True, False)  # attach_inventory=True, attach_entities=False
        result = self.execute(cmd)
        state = json.loads(result)
        inventory_data = state.get("inventory", {})
        
        items = []
        for item_name, count in inventory_data.items():
            # Default subgroup - could be enhanced to lookup from prototypes
            subgroup = "raw-material"
            items.append(ItemStack(name=item_name, count=count, subgroup=subgroup))
        
        return items
    
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

    def _build_command(self, method: str, *args) -> str:
        """Build RCON command string for a method call with positional arguments.
        
        Args are passed as positional arguments to match RemoteInterface method signatures.
        """
        remote_call = f"remote.call('{self.agent_id}', '{method}'"
        
        if args:
            # Convert args to JSON and pass as table
            args_json = json.dumps(list(args))
            remote_call += f", table.unpack(helpers.json_to_table('{args_json}'))"
        
        remote_call += ")"
        return f"rcon.print(helpers.table_to_json({remote_call}))"

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
        result = self.execute(cmd)
        return json.loads(result)

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
        result = self.execute(cmd)
        return json.loads(result)

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
        result = self.execute(cmd)
        return json.loads(result)

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
        
        return result

    def pickup_entity(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
    ) -> str:
        """Pick up an entity from the map into the agent's inventory.

        Args:
            entity_name: Entity prototype name to pick up
            position: Entity position (None = nearest)
        """
        cmd = self._build_command("pickup_entity", entity_name, position)
        return self.execute(cmd)

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

    def inspect(
        self, attach_inventory: bool = False, attach_entities: bool = False
    ) -> str:
        """Get current agent state including position, inventory, and nearby entities.

        Args:
            attach_inventory: Include inventory contents
            attach_entities: Include nearby entities
        """
        cmd = self._build_command("inspect", attach_inventory, attach_entities)
        return self.execute(cmd)

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

    def get_activity_state(self) -> str:
        """Get current state of all async activities (walking, mining, crafting)."""
        cmd = self._build_command("get_activity_state")
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
        result_str = self.execute(cmd)
        result = json.loads(result_str)
        
        return result
    
    @property
    def ghosts(self) -> GhostManager:
        """Get the ghost manager for this factory.
        
        Returns:
            GhostManager instance for managing tracked ghosts
        """
        return self._ghost_manager

    # ========================================================================
    # DEBUG
    # ========================================================================

    def _inspect_state(self) -> str:
        """Get raw agent state object (for debugging)."""
        cmd = self._build_command("inspect_state")
        return self.execute(cmd)


@contextmanager
def playing_factorio(rcon_client: "RconClient", agent_id: str, recipes: Optional[Recipes] = None,
                     udp_dispatcher: Optional[UDPDispatcher] = None):
    """Context manager for agent gameplay operations.

    This context enables entities to perform remote operations via RCON.
    Entities can only be operated on when inside this context.

    Args:
        rcon_client: RCON client for remote interface calls
        agent_id: Agent ID (e.g., 'agent_1')
        recipes: Optional Recipes instance (will be fetched if None)
        udp_dispatcher: Optional UDP dispatcher for async actions

    Example:
        with playing_factorio(rcon, 'agent_1'):
            await factory.walking.to(MapPosition(x=10, y=20))
            factory.crafting.enqueue('iron-plate', count=10)
    """
    # Fetch recipes if not provided
    if recipes is None:
        # Create a temporary factory to fetch recipes
        temp_factory = PlayingFactory(rcon_client, agent_id, Recipes([]), udp_dispatcher)
        recipes_json = temp_factory.get_recipes()
        recipes_data = json.loads(recipes_json)
        recipes = Recipes(recipes_data.get("recipes", []))
    
    factory = PlayingFactory(rcon_client, agent_id, recipes, udp_dispatcher)
    token = _playing_factory.set(factory)
    try:
        yield factory
    finally:
        _playing_factory.reset(token)
