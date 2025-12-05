import json
from typing import Any, Dict, Optional, Union, List
from src.FactoryVerse.dsl.types import MapPosition
from src.FactoryVerse.dsl.item.base import ItemStack
from src.FactoryVerse.dsl.recipe.base import Recipes, BaseRecipe, BasicRecipeName
from factorio_rcon import RconClient
from contextvars import ContextVar
from contextlib import contextmanager
from src.FactoryVerse.dsl.types import Direction


# Game context: agent is "playing" the factory game
_playing_factory: ContextVar[Optional["PlayingFactory"]] = ContextVar(
    "playing_factory", default=None
)


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


class PlayingFactory:
    """Represents the agent's active gameplay session with RCON access."""

    rcon: RconClient
    agent_id: str
    agent_commands: AgentCommands
    inventory: List[ItemStack]
    recipes: Recipes

    def __init__(self, rcon_client: "RconClient", agent_id: str, recipes: Recipes):
        self.rcon = rcon_client
        self._agent_id = agent_id
        self.agent_commands = AgentCommands(agent_id)
        self.recipes = recipes

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def inventory(self) -> List[ItemStack]:
        cmd = self._build_command("get_inventory")
        result = self.execute(cmd)
        return [ItemStack.from_json(item) for item in result]
    
    def update_recipes(self) -> None:
        cmd = self._build_command("get_recipes")
        result = self.execute(cmd)
        Recipes = Recipes(json.loads(result))
        self.recipes = Recipes

    def execute(self, command: str, silent: bool = True) -> str:
        if silent:
            command = f"/sc {command}"
        else:
            command = f"/c {command}"
        return self.rcon.send_command(command)

    def _build_command(self, method: str, **kwargs) -> str:
        """Build RCON command string for a method call with only named keyword arguments."""
        if not kwargs:
            # No arguments
            return f"rcon.print(helpers.table_to_json(remote.call('{self.agent_id}', '{method}')))"
        args = f"helpers.json_to_table('{json.dumps(kwargs)}')"
        return f"rcon.print(helpers.table_to_json(remote.call('{self.agent_id}', '{method}', {args})))"

    # ========================================================================
    # ASYNC: Walking
    # ========================================================================

    def walk_to(
        self,
        goal: Union[Dict[str, float], "MapPosition"],
        strict_goal: bool = False,
        options: Optional[Dict] = None,
    ) -> bool:
        """Walk the agent to a target position using pathfinding.

        Args:
            goal: Target position {x, y} or MapPosition objectxw
            strict_goal: If true, fail if exact position unreachable
            options: Additional pathfinding options
        """
        if options is None:
            options = {}
        cmd = self._build_command("walk_to", goal, strict_goal, options)
        return self.execute(cmd)

    def stop_walking(self) -> str:
        """Immediately stop the agent's current walking action."""
        cmd = self._build_command("stop_walking")
        return self.execute(cmd)

    # ========================================================================
    # ASYNC: Mining
    # ========================================================================

    def mine_resource(self, resource_name: str, max_count: Optional[int] = None) -> str:
        """Mine a resource within reach of the agent.

        Args:
            resource_name: Resource prototype name (e.g., 'iron-ore', 'coal', 'stone')
            max_count: Max items to mine (None = deplete resource)
        """
        if max_count is None:
            cmd = self._build_command("mine_resource", resource_name, None)
            return self.execute(cmd)
        cmd = self._build_command("mine_resource", resource_name, max_count)
        return self.execute(cmd)

    def stop_mining(self) -> str:
        """Immediately stop the agent's current mining action."""
        cmd = self._build_command("stop_mining")
        return self.execute(cmd)

    # ========================================================================
    # ASYNC: Crafting
    # ========================================================================

    def craft_enqueue(self, recipe_name: str, count: int = 1) -> str:
        """Queue a recipe for hand-crafting.

        Args:
            recipe_name: Recipe name to craft
            count: Number of times to craft the recipe
        """
        if not self.recipes[recipe_name].is_hand_craftable():
            raise ValueError(f"Recipe {recipe_name} is not hand-craftable")
        if not self.recipes[recipe_name].enabled:
            raise ValueError(f"Recipe {recipe_name} is not enabled, try researching technology first")
        cmd = self._build_command("craft_enqueue", recipe_name, count)
        return self.execute(cmd)

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
    ) -> str:
        """Place an entity from the agent's inventory onto the map.

        Args:
            entity_name: Entity prototype name to place
            position: MapPosition to place entity
            options: Placement options (direction, force_build, etc.)
        """
        return self._build_command(
            "place_entity", entity_name, position, direction, ghost
        )

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

    def remove_ghost(self, entity_name: str, position: MapPosition) -> str:
        """Remove a ghost entity from the map.

        Args:
            entity_name: Entity prototype name to remove
            position: Entity position (None = nearest)
        """
        cmd = self._build_command("remove_ghost", entity_name, position)
        return self.execute(cmd)

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

    def get_reachable(self) -> str:
        """Get cached reachable entities and resources (position keys only)."""
        cmd = self._build_command("get_reachable")
        return self.execute(cmd)

    def get_reachable_full(self) -> str:
        """Get full reachable snapshot with complete entity data."""
        cmd = self._build_command("get_reachable_full")
        return self.execute(cmd)

    # ========================================================================
    # DEBUG
    # ========================================================================

    def _inspect_state(self) -> str:
        """Get raw agent state object (for debugging)."""
        cmd = self._build_command("inspect_state")
        return self.execute(cmd)


@contextmanager
def playing_factorio(rcon_client: "RconClient", agent_id: str):
    """Context manager for agent gameplay operations.

    This context enables entities to perform remote operations via RCON.
    Entities can only be operated on when inside this context.

    Args:
        rcon_client: RCON client for remote interface calls
        agent_id: Agent ID (e.g., 'agent_1')

    Example:
        with playing_factory(rcon, 'agent_1'):
            assembler = entities[0]  # From reachable API
            assembler.set_recipe('iron-plate')
    """
    factory = PlayingFactory(rcon_client, agent_id)
    token = _playing_factory.set(factory)
    try:
        yield factory
    finally:
        _playing_factory.reset(token)
