"""DSL Mixins for reducing duplication and improving cohesion.

These mixins provide common functionality across Items, Entities, and other DSL objects.
They are designed with agent interaction in mind - docstrings explain WHEN and WHY
agents should use each method, not just WHAT it does.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional, List, Tuple, Dict, Any, Union, Literal
from FactoryVerse.dsl.types import MapPosition, Direction
from FactoryVerse.dsl.prototypes import BasePrototype

if TYPE_CHECKING:
    from FactoryVerse.dsl.agent import PlayingFactory
    from FactoryVerse.dsl.item.base import Item, ItemStack


class FactoryContextMixin:
    """Provides access to the active PlayingFactory gameplay context.
    
    The factory context is required for all DSL operations that interact with the game.
    Without an active context, operations will fail with a clear error message.
    
    **For Agents**: You don't call this directly. It's used internally by DSL methods
    like place(), mine(), inspect(), etc. The context is automatically available when
    you use `with playing_factorio():`.
    """
    
    @property
    def _factory(self) -> "PlayingFactory":
        """Get the current playing factory context.
        
        Raises:
            RuntimeError: If no active gameplay session exists
        """
        from FactoryVerse.dsl.agent import _playing_factory
        factory = _playing_factory.get()
        if factory is None:
            raise RuntimeError(
                f"No active gameplay session for {self.__class__.__name__}. "
                "Use 'with playing_factorio(rcon, agent_id):' to enable operations."
            )
        return factory
    
    @property
    def agent_id(self) -> str:
        """Get the current agent ID from the gameplay context.
        
        **For Agents**: Useful for debugging or multi-agent scenarios.
        """
        return self._factory.agent_id


class SpatialPropertiesMixin:
    """Provides tile-based spatial properties from prototype data.
    
    **For Agents**: Use these properties for spatial planning and layout calculations.
    - tile_width/tile_height: How much space this entity occupies
    - footprint: Convenient (width, height) tuple
    - area: Total tiles occupied (useful for comparing entity sizes)
    
    **Example Agent Usage**:
    ```python
    # Check if entity fits in available space
    drill = inventory.get_item("burner-mining-drill")
    if drill.tile_width <= available_width and drill.tile_height <= available_height:
        drill.place(position)
    
    # Calculate spacing between entities
    gap = 1  # 1 tile gap
    next_pos = furnace.position.offset_by_entity(direction=Direction.NORTH, gap=gap)
    ```
    """
    
    # This mixin requires the class to have a 'prototype' property
    prototype: BasePrototype
    
    @property
    def tile_width(self) -> int:
        """Get tile width from prototype.
        
        **For Agents**: Use for spatial planning. A 2x2 entity has tile_width=2.
        """
        return self.prototype.tile_width
    
    @property
    def tile_height(self) -> int:
        """Get tile height from prototype.
        
        **For Agents**: Use for spatial planning. A 2x2 entity has tile_height=2.
        """
        return self.prototype.tile_height
    
    @property
    def footprint(self) -> Tuple[int, int]:
        """Get (width, height) tuple for convenient spatial calculations.
        
        **For Agents**: Useful when you need both dimensions at once.
        
        Example:
            width, height = entity.footprint
        """
        return (self.tile_width, self.tile_height)
    
    @property
    def area(self) -> int:
        """Get total tile area occupied by this entity.
        
        **For Agents**: Useful for comparing entity sizes or calculating
        total space requirements for a build plan.
        
        Example:
            # Check if we have enough space
            required_area = sum(item.area for item in items_to_place)
        """
        return self.tile_width * self.tile_height


class PrototypeMixin(ABC):
    """Provides lazy-loaded prototype caching with type-specific loading logic.
    
    **For Agents**: You don't call this directly. It provides the `prototype` property
    that gives you access to entity properties like tile dimensions, crafting speed, etc.
    
    **Design Note**: Items and Entities load prototypes differently:
    - Items: Load item prototype, then resolve place_result to entity prototype
    - Entities: Direct entity prototype lookup by name
    This is why _load_prototype() is abstract - subclasses implement their specific logic.
    """
    
    _prototype_cache: Optional[BasePrototype]
    name: str  # Required by subclasses
    
    @property
    def prototype(self) -> BasePrototype:
        """Get cached prototype with lazy loading.
        
        **For Agents**: Access entity properties through this:
        - prototype.tile_width, prototype.tile_height
        - prototype.crafting_speed (for assemblers)
        - prototype.mining_speed (for drills)
        
        The prototype is loaded once and cached for performance.
        """
        if not hasattr(self, '_prototype_cache') or self._prototype_cache is None:
            self._prototype_cache = self._load_prototype()
        return self._prototype_cache
    
    @abstractmethod
    def _load_prototype(self) -> BasePrototype:
        """Load prototype based on type-specific logic.
        
        Subclasses implement this to handle their specific prototype loading:
        - PlaceableItem: item prototype → place_result → entity prototype
        - ReachableEntity: direct entity prototype lookup
        """
        pass


class DirectionMixin:
    """Provides direction-aware spatial operations and semantics.
    
    **For Agents**: This is CRITICAL for placement planning. Some entities care about
    direction (drills, inserters, belts), others don't (chests, furnaces, solar panels).
    
    **Direction-Dependent Entities** (rotation changes behavior):
    - Mining drills: Output position changes with direction
    - Inserters: Pickup/drop positions change with direction
    - Belts: Items flow in the direction the belt faces
    - Assemblers with fluids: Fluid connections are directional
    
    **Direction-Invariant Entities** (rotation is cosmetic):
    - Chests: Access from all sides
    - Furnaces: Accept input/output from all sides
    - Solar panels: Generate power regardless of rotation
    - Electric poles: Connect in all directions
    
    **Example Agent Usage**:
    ```python
    # Check if direction matters before placing
    if not entity.is_direction_invariant():
        # Plan direction carefully for output alignment
        drill.place(position, direction=Direction.NORTH)
    else:
        # Direction doesn't matter, use default
        chest.place(position)
    
    # Calculate output position for directional entities
    if not drill.is_direction_invariant():
        output_pos = drill.get_facing_position(distance=1.0)
        # Place chest at output position
        chest.place(output_pos)
    ```
    """
    
    direction: Optional[Direction]  # Required by subclasses
    position: MapPosition  # Required by subclasses
    name: str  # Required by subclasses
    
    @abstractmethod
    def is_direction_invariant(self) -> bool:
        """Return True if rotation has no functional effect.
        
        **For Agents**: Query this before placing to know if you need to plan direction.
        
        Returns:
            True: Rotation is cosmetic (chests, furnaces, solar panels)
            False: Rotation changes behavior (drills, inserters, belts)
        """
        pass
    
    def get_facing_position(self, distance: float = 1.0) -> MapPosition:
        """Get position in the direction this entity is facing.
        
        **For Agents**: Use this to calculate where output will be or where to place
        the next entity in a line.
        
        Args:
            distance: How many tiles away (default 1.0)
        
        Returns:
            MapPosition offset in the facing direction
        
        Raises:
            ValueError: If entity is direction-invariant (has no facing direction)
        
        Example:
            # Place chest at drill's output position
            output_pos = drill.get_facing_position(distance=1.0)
            chest.place(output_pos)
        """
        if self.is_direction_invariant():
            raise ValueError(
                f"{self.name} is direction-invariant; it has no facing direction. "
                "Use is_direction_invariant() to check before calling this method."
            )
        
        if self.direction is None:
            raise ValueError(f"{self.name} has no direction set")
        
        return self._calculate_directional_offset(self.direction, distance)
    
    def get_opposite_position(self, distance: float = 1.0) -> MapPosition:
        """Get position opposite to the facing direction.
        
        **For Agents**: Use for inserters (pickup is opposite to drop) or
        for placing entities that feed into this one.
        
        Args:
            distance: How many tiles away (default 1.0)
        
        Returns:
            MapPosition offset opposite to facing direction
        
        Raises:
            ValueError: If entity is direction-invariant
        
        Example:
            # Place furnace opposite to inserter's drop position
            input_pos = inserter.get_opposite_position(distance=1.0)
            furnace.place(input_pos)
        """
        if self.is_direction_invariant():
            raise ValueError(f"{self.name} is direction-invariant; no facing direction")
        
        if self.direction is None:
            raise ValueError(f"{self.name} has no direction set")
        
        opposite = self._get_opposite_direction(self.direction)
        return self._calculate_directional_offset(opposite, distance)
    
    def rotate(self, clockwise: bool = True) -> Direction:
        """Rotate entity and return new direction.
        
        **For Agents**: Use to adjust entity orientation. Even direction-invariant
        entities can be rotated (for visual consistency).
        
        Args:
            clockwise: If True, rotate clockwise; if False, counter-clockwise
        
        Returns:
            New direction after rotation
        
        Example:
            # Rotate drill to face north
            while drill.direction != Direction.NORTH:
                drill.rotate(clockwise=True)
        """
        if self.direction is None:
            raise ValueError(f"{self.name} has no direction to rotate")
        
        if clockwise:
            self.direction = self.direction.turn_right()
        else:
            self.direction = self.direction.turn_left()
        
        return self.direction
    
    def _calculate_directional_offset(self, direction: Direction, distance: float) -> MapPosition:
        """Calculate position offset in given direction.
        
        Internal helper for directional position calculations.
        """
        offsets = {
            Direction.NORTH: (0, -distance),
            Direction.EAST: (distance, 0),
            Direction.SOUTH: (0, distance),
            Direction.WEST: (-distance, 0),
        }
        
        if direction not in offsets:
            raise ValueError(f"Direction must be cardinal, got {direction}")
        
        dx, dy = offsets[direction]
        return MapPosition(self.position.x + dx, self.position.y + dy)
    
    def _get_opposite_direction(self, direction: Direction) -> Direction:
        """Get opposite direction.
        
        Internal helper for directional calculations.
        """
        opposites = {
            Direction.NORTH: Direction.SOUTH,
            Direction.SOUTH: Direction.NORTH,
            Direction.EAST: Direction.WEST,
            Direction.WEST: Direction.EAST,
        }
        return opposites[direction]


class InspectableMixin:
    """Provides inspection capabilities for game objects.
    
    **For Agents**: Use inspect() to get formatted status information for decision-making.
    This is your primary way to understand what's happening with entities.
    
    **Two Modes**:
    1. `inspect()` - Returns formatted string for reading (default)
    2. `inspect(raw_data=True)` - Returns dict for programmatic access
    
    **Example Agent Usage**:
    ```python
    # Read entity status
    print(furnace.inspect())
    # Output:
    # Furnace(stone-furnace) at (10.5, 20.5)
    #   Status: working
    #   Currently Burning: coal
    #   Fuel: coal: 5
    #   Input: iron-ore: 10
    #   Output: iron-plate: 8
    
    # Programmatic access
    data = furnace.inspect(raw_data=True)
    if data['status'] == 'no-fuel':
        # Add more fuel
        furnace.add_fuel(coal_stack)
    ```
    """
    
    _factory: "PlayingFactory"  # Provided by FactoryContextMixin
    name: str  # Required by subclasses
    position: MapPosition  # Required by subclasses
    
    def inspect(self, raw_data: bool = False) -> Union[str, Dict[str, Any]]:
        """Inspect current state of the object.
        
        **For Agents**: This is your primary diagnostic tool. Use it to:
        - Check if machines are working or idle
        - See inventory contents (fuel, input, output)
        - Monitor progress (crafting, mining, research)
        - Diagnose problems (no-power, no-fuel, no-ingredients)
        
        Args:
            raw_data: If False (default), returns formatted string for reading.
                     If True, returns raw dictionary for programmatic access.
        
        Returns:
            Formatted string or raw dictionary of object state
        
        **Formatted Output Includes**:
        - Entity name and position
        - Status (working, no-power, no-fuel, etc.)
        - Progress (crafting, mining, burning)
        - Inventories (fuel, input, output, chest)
        - Energy state (for electric entities)
        
        **Raw Data Schema** (when raw_data=True):
        - entity_name (str): Entity prototype name
        - entity_type (str): Entity type
        - position (dict): {x, y}
        - tick (int): Game tick when inspected
        - status (str): Entity status
        - recipe (str, optional): Current recipe
        - crafting_progress (float, optional): 0.0-1.0
        - mining_progress (float, optional): 0.0-1.0
        - burner (dict, optional): Burner state
        - energy (dict, optional): {current, capacity}
        - inventories (dict, optional): {fuel, input, output, chest}
        - held_item (dict, optional): {name, count} (inserters)
        """
        result = self._get_inspection_data()
        if raw_data:
            return result
        return self._format_inspection(result)
    
    def _get_inspection_data(self) -> Dict[str, Any]:
        """Get raw inspection data from the game.
        
        Default implementation calls factory.inspect_entity().
        Subclasses can override for custom inspection logic.
        """
        return self._factory.inspect_entity(self.name, self.position)
    
    def _format_inspection(self, data: Dict[str, Any]) -> str:
        """Format inspection data for agent readability.
        
        Default implementation provides basic formatting.
        Subclasses SHOULD override this to provide entity-specific formatting
        (e.g., Furnace shows burner state, AssemblingMachine shows recipe progress).
        """
        lines = [
            f"{self.__class__.__name__}({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        return "\n".join(lines)


class FuelableMixin:
    """Provides fuel management with validation for burner entities.
    
    **For Agents**: Use add_fuel() to add fuel to burner entities (furnaces, burner drills).
    The method validates fuel type and provides helpful error messages if you try to
    add invalid items.
    
    **Fuel Categories**:
    - Chemical: wood, coal, solid-fuel, rocket-fuel, nuclear-fuel
    - Nuclear: uranium-fuel-cell (for nuclear reactors)
    
    **Example Agent Usage**:
    ```python
    # Add fuel to furnace (accepts any fuel)
    furnace.add_fuel(coal_stack)
    
    # Add fuel to burner mining drill (only chemical fuel)
    burner_drill.add_fuel(coal_stack)  # ✓ Works
    burner_drill.add_fuel(uranium_fuel_cell)  # ✗ Error: only accepts chemical fuel
    
    # Add multiple stacks at once
    coal_stacks = inventory.get_item_stacks("coal", count=50, number_of_stacks=5)
    burner_drill.add_fuel(coal_stacks)  # Adds all stacks
    ```
    """
    
    _factory: "PlayingFactory"  # Provided by FactoryContextMixin
    name: str  # Required by subclasses
    position: MapPosition  # Required by subclasses
    
    @abstractmethod
    def _get_accepted_fuel_categories(self) -> List[str]:
        """Return accepted fuel categories for this entity.
        
        Returns:
            List of fuel categories: ['chemical'], ['nuclear'], or ['chemical', 'nuclear']
        """
        pass
    
    def add_fuel(
        self, 
        item: Union["Item", "ItemStack", List["Item"], List["ItemStack"]], 
        count: Optional[int] = None
    ):
        """Add fuel to the entity with validation.
        
        **For Agents**: This handles multiple input formats and validates fuel type.
        If you try to add invalid fuel, you'll get a clear error message with valid options.
        
        Args:
            item: Item, ItemStack, or list of Items/ItemStacks to add as fuel
            count: Count to add (required if Item, optional if ItemStack)
                  Ignored if item is a list (uses each stack's count)
        
        Returns:
            Result from factory.put_inventory_item() or list of results
        
        Raises:
            ValueError: If item is not a valid fuel or wrong fuel category
        
        **Input Formats**:
        1. Single Item: add_fuel(Item("coal"), count=10)
        2. Single ItemStack: add_fuel(ItemStack("coal", 10))
        3. List of ItemStacks: add_fuel([stack1, stack2, stack3])
        
        Example:
            # Single stack
            coal = inventory.get_item_stacks("coal", count=10)[0]
            furnace.add_fuel(coal)
            
            # Multiple stacks
            coal_stacks = inventory.get_item_stacks("coal", count=50, number_of_stacks=5)
            burner_drill.add_fuel(coal_stacks)
        """
        # Handle lists (from inventory.get_item_stacks())
        if isinstance(item, list):
            results = []
            for stack in item:
                results.append(self.add_fuel(stack))
            return results
        
        # Normalize to (item_name, fuel_count)
        if hasattr(item, 'name') and hasattr(item, 'count'):  # ItemStack
            item_name = item.name
            fuel_count = count if count is not None else item.count
        elif hasattr(item, 'name'):  # Item
            item_name = item.name
            if count is None:
                raise ValueError("count is required when using Item (not ItemStack)")
            fuel_count = count
        else:
            raise ValueError(f"item must be Item or ItemStack, got {type(item)}")
        
        # Validate fuel type
        self._validate_fuel(item_name)
        
        return self._factory.put_inventory_item(
            self.name, self.position, "fuel", item_name, fuel_count
        )
    
    def _validate_fuel(self, item_name: str):
        """Validate that item is valid fuel for this entity.
        
        Raises helpful error messages if validation fails.
        """
        from FactoryVerse.dsl.prototypes import get_item_prototypes
        item_protos = get_item_prototypes()
        
        # Check if item is fuel at all
        if not item_protos.is_fuel(item_name):
            valid_fuels = item_protos.get_fuel_items()
            raise ValueError(
                f"Cannot add '{item_name}' as fuel to {self.name}. "
                f"Valid fuel items: {', '.join(sorted(valid_fuels))}"
            )
        
        # Check fuel category
        fuel_category = item_protos.get_fuel_category(item_name)
        accepted_categories = self._get_accepted_fuel_categories()
        
        if fuel_category not in accepted_categories:
            raise ValueError(
                f"Cannot add '{item_name}' (fuel_category={fuel_category}) to {self.name}. "
                f"Accepted fuel categories: {', '.join(accepted_categories)}"
            )


class InventoryMixin:
    """Provides inventory management for container entities.
    
    **For Agents**: Use store_items() and take_items() to move items in/out of chests.
    
    **Example Agent Usage**:
    ```python
    # Store items in chest
    iron_stacks = inventory.get_item_stacks("iron-plate", count=100)
    chest.store_items(iron_stacks)
    
    # Take items from chest
    chest_data = chest.inspect(raw_data=True)
    if 'iron-plate' in chest_data['inventories']['chest']:
        take_stacks = [ItemStack("iron-plate", 50)]
        chest.take_items(take_stacks)
    ```
    """
    
    _factory: "PlayingFactory"  # Provided by FactoryContextMixin
    name: str  # Required by subclasses
    position: MapPosition  # Required by subclasses
    
    @abstractmethod
    def _get_inventory_type(self) -> str:
        """Return inventory type for this entity.
        
        Returns:
            Inventory type: 'chest', 'input', 'output', 'fuel', etc.
        """
        pass
    
    def store_items(self, items: List["ItemStack"]) -> List[Any]:
        """Store items in the entity's inventory.
        
        **For Agents**: Use to move items from your inventory into a chest or machine.
        
        Args:
            items: List of ItemStack objects to store
        
        Returns:
            List of results from factory.put_inventory_item()
        
        Example:
            iron_stacks = inventory.get_item_stacks("iron-plate", count=100)
            chest.store_items(iron_stacks)
        """
        return [
            self._factory.put_inventory_item(
                self.name, self.position, 
                self._get_inventory_type(), 
                item.name, item.count
            )
            for item in items
        ]
    
    def take_items(self, items: List["ItemStack"]) -> List[Any]:
        """Take items from the entity's inventory.
        
        **For Agents**: Use to move items from a chest or machine into your inventory.
        
        Args:
            items: List of ItemStack objects to take
        
        Returns:
            List of results from factory.take_inventory_item()
        
        Example:
            take_stacks = [ItemStack("iron-plate", 50)]
            chest.take_items(take_stacks)
        """
        return [
            self._factory.take_inventory_item(
                self.name, self.position, 
                self._get_inventory_type(), 
                item.name, item.count
            )
            for item in items
        ]


class CrafterMixin:
    """Provides crafting input/output management for production entities.
    
    Crafters are entities that:
    - Have input buffers (add_ingredients)
    - Have output buffers (take_products)
    - Process materials over time
    
    **Crafters**: Furnace, BurnerMiningDrill, AssemblingMachine
    **NOT Crafters**: ElectricMiningDrill (tiny buffer, direct output only)
    
    **For Agents**: Use these methods to manage entity buffers:
    - add_ingredients(): Add items to input buffer
    - take_products(): Take items from output buffer
    
    **Example Agent Usage**:
    ```python
    # Add ore to furnace
    ore_stacks = inventory.get_item_stacks("iron-ore", count=10)
    furnace.add_ingredients(ore_stacks)
    
    # Check if furnace has produced plates
    furnace_data = furnace.inspect(raw_data=True)
    if 'iron-plate' in furnace_data['inventories']['output']:
        # Take plates from furnace
        plates = [ItemStack("iron-plate", 10)]
        furnace.take_products(plates)
    
    # Burner mining drill also uses this
    drill_data = drill.inspect(raw_data=True)
    if drill_data['inventories']['output']:
        # Take ore from drill's buffer
        ore = [ItemStack("iron-ore", 50)]
        drill.take_products(ore)
    ```
    """
    
    _factory: "PlayingFactory"  # Provided by FactoryContextMixin
    name: str  # Required by subclasses
    position: MapPosition  # Required by subclasses
    
    def add_ingredients(self, items: List["ItemStack"]) -> List[Any]:
        """Add ingredients to the entity's input buffer.
        
        **For Agents**: Use to feed materials into crafters.
        - Furnaces: Add ore to smelt
        - Assemblers: Add ingredients for recipe
        - Burner drills: Not typically used (drills mine their own input)
        
        Args:
            items: List of ItemStack objects to add as ingredients
        
        Returns:
            List of results from factory.put_inventory_item()
        
        Example:
            # Add ore to furnace
            ore = inventory.get_item_stacks("iron-ore", count=10)
            furnace.add_ingredients(ore)
            
            # Add ingredients to assembler
            ingredients = [
                ItemStack("iron-plate", 2),
                ItemStack("copper-cable", 3)
            ]
            assembler.add_ingredients(ingredients)
        """
        return [
            self._factory.put_inventory_item(
                self.name, self.position,
                "input",
                item.name, item.count
            )
            for item in items
        ]
    
    def take_products(self, items: Optional[List["ItemStack"]] = None) -> List[Any]:
        """Take products from the entity's output buffer.
        
        **For Agents**: Use to collect results from crafters.
        - Furnaces: Take smelted plates
        - Assemblers: Take crafted products
        - Burner drills: Take mined ore from buffer
        
        Args:
            items: List of ItemStack objects to take. If None, takes all available.
        
        Returns:
            List of results from factory.take_inventory_item()
        
        Example:
            # Take plates from furnace
            plates = [ItemStack("iron-plate", 10)]
            furnace.take_products(plates)
            
            # Take ore from burner drill's buffer
            ore = [ItemStack("iron-ore", 50)]
            drill.take_products(ore)
            
            # Check what's available first
            data = furnace.inspect(raw_data=True)
            output_inv = data['inventories']['output']
            # Take specific items based on what's available
        """
        if items is None:
            # If no items specified, inspect and take everything
            data = self._factory.inspect_entity(self.name, self.position)
            output_inv = data.get('inventories', {}).get('output', {})
            items = [
                ItemStack(item_name, count)
                for item_name, count in output_inv.items()
            ]
        
        return [
            self._factory.take_inventory_item(
                self.name, self.position,
                "output",
                item.name, item.count
            )
            for item in items
        ]


class OutputPositionMixin:

    """Provides output position calculation for production entities.
    
    **For Agents**: Use output_position to know where this entity outputs items/fluids.
    This is critical for placing chests, belts, or pipes to receive output.
    
    **Example Agent Usage**:
    ```python
    # Place chest at drill's output position
    drill = reachable.get_entity("burner-mining-drill")
    output_pos = drill.output_position
    chest_item.place(output_pos)
    
    # Get all valid positions for placing a chest to receive output
    chest_item = inventory.get_item("wooden-chest")
    valid_positions = drill.get_valid_output_positions(chest_item)
    # Place at best position (e.g., closest to drill)
    chest_item.place(valid_positions[0])
    ```
    """
    
    direction: Optional[Direction]  # Required by subclasses
    position: MapPosition  # Required by subclasses
    
    @abstractmethod
    def _get_output_type(self) -> Literal["item", "fluid"]:
        """Return output type for this entity.
        
        Returns:
            'item' for mining drills, assemblers
            'fluid' for pumpjacks, refineries
        """
        pass
    
    @property
    @abstractmethod
    def output_position(self) -> MapPosition:
        """Get primary output position based on direction.
        
        **For Agents**: This is where items/fluids come out of the entity.
        Place chests, belts, or pipes here to receive output.
        
        Returns:
            MapPosition where output appears
        
        Example:
            output_pos = drill.output_position
            chest.place(output_pos)
        """
        pass
