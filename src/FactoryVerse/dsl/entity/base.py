# from __future__ import annotations
import math
from abc import ABC, abstractmethod
from typing import List, Optional, Union, Literal, Dict, Any, TYPE_CHECKING
from FactoryVerse.dsl.types import MapPosition, BoundingBox, Direction, Position
from FactoryVerse.dsl.item.base import PlaceableItemName, ItemName, Item, ItemStack, PlaceableItem
from FactoryVerse.dsl.prototypes import (
    get_entity_prototypes,
    ElectricMiningDrillPrototype,
    BurnerMiningDrillPrototype,
    PumpjackPrototype,
    InserterPrototype,
    LongHandedInserterPrototype,
    FastInserterPrototype,
    TransportBeltPrototype,
    BasePrototype,
)

if TYPE_CHECKING:
    from FactoryVerse.dsl.agent import PlayingFactory

# Import _playing_factory safely
from FactoryVerse.dsl.agent import _playing_factory


class EntityPosition(MapPosition):
    """Position with entity-aware spatial operations.
    
    High-level position type that knows about entities, items, and prototypes.
    Provides spatial reasoning for placement and layout calculations.
    MapPosition remains pure - this handles the DSL-aware logic.
    
    Can be bound to a parent entity, making offset calculations more ergonomic:
        furnace.position.offset_by_entity(direction=Direction.NORTH)
    """
    
    def __init__(self, x: float, y: float, entity: Optional[Union["BaseEntity", PlaceableItem]] = None):
        """Initialize EntityPosition, optionally bound to an entity.
        
        Args:
            x: X coordinate
            y: Y coordinate
            entity: Optional parent entity for default dimension calculations
        """
        super().__init__(x, y)
        self._entity = entity
    
    def offset_by_entity(
        self, 
        entity: Optional[Union["BaseEntity", PlaceableItem, BasePrototype]] = None,
        direction: Direction = None,
        gap: int = 0
    ) -> "EntityPosition":
        """Calculate position offset by entity dimensions in a cardinal direction.
        
        Uses parent entity dimensions if no entity is provided.
        
        Args:
            entity: Entity, item, or prototype to get dimensions from (uses parent if None)
            direction: Cardinal direction to offset (NORTH/SOUTH/EAST/WEST)
            gap: Additional tiles of spacing (default 0 for touching)
        
        Returns:
            New EntityPosition offset by entity dimensions + gap
        
        Examples:
            >>> # Offset using bound entity (most ergonomic)
            >>> furnace = reachable_entities.get_entity("stone-furnace")
            >>> next_pos = furnace.position.offset_by_entity(direction=Direction.NORTH)
            >>> 
            >>> # Offset using different entity's dimensions
            >>> next_pos = furnace.position.offset_by_entity(drill_item, Direction.EAST)
            >>>
            >>> # Standalone usage
            >>> entity_pos = EntityPosition(x=10, y=20)
            >>> next_pos = entity_pos.offset_by_entity(furnace, Direction.NORTH, gap=1)
        """
        if direction is None:
            raise ValueError("direction is required")
            
        ref = entity or self._entity
        if ref is None:
            raise ValueError(
                "No entity provided and no parent entity bound to this position. "
                "Either pass an entity or use EntityPosition from an entity's .position property."
            )
        
        if not direction.is_cardinal():
            raise ValueError(f"Cannot offset in non-cardinal direction: {direction.name}")
        
        # Extract tile dimensions (all three types have these properties)
        tile_w = ref.tile_width
        tile_h = ref.tile_height
        
        # Calculate distance based on direction
        # NORTH/SOUTH: use height, EAST/WEST: use width
        if direction in (Direction.NORTH, Direction.SOUTH):
            distance = tile_h + gap
        else:  # EAST or WEST
            distance = tile_w + gap
        
        # Calculate new position based on cardinal direction
        # Positive x = east, positive y = south
        if direction == Direction.NORTH:
            new_x, new_y = self.x, self.y - distance
        elif direction == Direction.EAST:
            new_x, new_y = self.x + distance, self.y
        elif direction == Direction.SOUTH:
            new_x, new_y = self.x, self.y + distance
        else:  # WEST
            new_x, new_y = self.x - distance, self.y
        
        # Return new EntityPosition, not bound to any entity (it's just a calculated position)
        return EntityPosition(x=new_x, y=new_y)


class BaseEntity(ABC):
    """Base class for all entities.
    
    Entities are things placed in the world with position and direction.
    They have prototypes that define their properties and behavior.
    """

    def __init__(
        self,
        name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        **kwargs  # For backward compatibility with subclasses
    ):
        self.name = name
        self._raw_position = position  # Store raw position internally
        self.direction = direction
        self._prototype_cache: Optional[BasePrototype] = None
        
        # Handle any additional kwargs for subclasses
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    @property
    def position(self) -> EntityPosition:
        """Get the entity's position as an EntityPosition bound to this entity.
        
        This allows ergonomic spatial operations like:
            next_pos = entity.position.offset_by_entity(direction=Direction.NORTH)
        """
        return EntityPosition(x=self._raw_position.x, y=self._raw_position.y, entity=self)

    @property
    def _factory(self) -> "PlayingFactory":
        """Get the current playing factory context."""
        factory = _playing_factory.get()
        if factory is None:
            raise RuntimeError(
                "No active gameplay session. "
                "Use 'with playing_factory(rcon, agent_id):' to enable entity operations."
            )
        return factory

    @property
    def agent_id(self) -> str:
        """Get agent ID from gameplay context."""
        return self._factory.agent_id

    @property
    def prototype(self) -> BasePrototype:
        """Get the cached prototype for this entity.
        
        Lazily loads and caches the prototype on first access.
        """
        if self._prototype_cache is None:
            protos = get_entity_prototypes()
            entity_type = protos.get_entity_type(self.name)
            if entity_type and entity_type in protos.data:
                entity_data = protos.data[entity_type].get(self.name, {})
                self._prototype_cache = BasePrototype(_data=entity_data)
            else:
                # Fallback to empty prototype
                self._prototype_cache = BasePrototype(_data={})
        return self._prototype_cache

    @property
    def tile_width(self) -> int:
        """Get the tile width of this entity from its prototype."""
        return self.prototype.tile_width

    @property
    def tile_height(self) -> int:
        """Get the tile height of this entity from its prototype."""
        return self.prototype.tile_height

    def __repr__(self) -> str:
        """Simple, explicit representation of the entity."""
        pos = self.position
        if self.direction is not None:
            return f"{self.__class__.__name__}(name='{self.name}', position=({pos.x}, {pos.y}), direction={self.direction.name})"
        else:
            return f"{self.__class__.__name__}(name='{self.name}', position=({pos.x}, {pos.y}))"

    def inspect(self, raw_data: bool = False) -> Union[str, Dict[str, Any]]:
        """Return a representation of entity state.
        
        This is a read-only inspection that provides comprehensive information
        about the entity's current volatile state (inventories, progress, status, etc.).
        
        Args:
            raw_data: If False (default), returns a formatted string representation.
                      If True, returns the raw dictionary data.
        
        Returns:
            If raw_data=False: Formatted string representation of entity state
            If raw_data=True: Dictionary with entity inspection data including:
                - entity_name (str): Entity prototype name
                - entity_type (str): Entity type
                - position (dict): Entity position {x, y}
                - tick (int): Game tick when inspection was taken
                - status (str, optional): Entity status (working, no-power, etc.)
                - recipe (str, optional): Current recipe name (if applicable)
                - crafting_progress (float, optional): Crafting progress 0.0-1.0
                - mining_progress (float, optional): Mining progress 0.0-1.0
                - burner (dict, optional): Burner state with heat, fuel, etc.
                - productivity_bonus (float, optional): Productivity bonus
                - energy (dict, optional): Energy state {current, capacity}
                - inventories (dict, optional): Inventories by type {fuel, input, output, chest, burnt_result}
                - held_item (dict, optional): Held item {name, count} (inserters only)
        
        Note: Subclasses should override this method to provide entity-specific
        inspection details. This default implementation provides basic information.
        """
        data = self._factory.inspect_entity(self.name, self.position)
        
        if raw_data:
            return data
        
        lines = [
            f"{self.__class__.__name__}({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        return "\n".join(lines)

    def pickup(self) -> List[ItemStack]:
        """Pick up the entity and return items added to inventory.
        
        Returns:
            List of ItemStack objects representing items extracted from the entity
        """
        return self._factory.pickup_entity(self.name, self.position)

class GhostEntity(BaseEntity):
    """A ghost entity."""

    def remove(self) -> bool:
        """Remove the ghost entity."""
        return self._factory.remove_ghost(self.name, self.position)
    
    def build(self) -> bool:
        """Build the ghost entity."""
        return self._factory.place_entity(self.name, self.position)

    def inspect(self, raw_data: bool = False) -> Union[str, Dict[str, Any]]:
        """Return a representation of ghost entity state.
        
        Args:
            raw_data: If False (default), returns a formatted string representation.
                      If True, returns the raw dictionary data.
        
        Returns:
            If raw_data=False: Formatted string representation
            If raw_data=True: Dictionary with entity inspection data (see BaseEntity.inspect for schema)
        """
        if raw_data:
            return self._factory.inspect_entity(self.name, self.position)
        return f"GhostEntity(name='{self.name}', position=({self.position.x:.1f}, {self.position.y:.1f}))"

class Container(BaseEntity):
    """A container entity with inventory."""

    def __init__(
        self,
        name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        inventory_size: int = 0,
        **kwargs
    ):
        super().__init__(name, position, direction, **kwargs)
        self.inventory_size = inventory_size

    def store_items(self, items: List[ItemStack]):
        """Store items in the container."""
        results = []
        for item_stack in items:
            result = self._factory.put_inventory_item(
                self.name, self.position, "chest", item_stack.name, item_stack.count
            )
            results.append(result)
        return results

    def take_items(self, items: List[ItemStack]):
        """Take items from the container."""
        results = []
        for item_stack in items:
            result = self._factory.take_inventory_item(
                self.name, self.position, "chest", item_stack.name, item_stack.count
            )
            results.append(result)
        return results

    def inspect(self, raw_data: bool = False) -> Union[str, Dict[str, Any]]:
        """Return a representation of container state.
        
        Args:
            raw_data: If False (default), returns a formatted string representation.
                      If True, returns the raw dictionary data.
        
        Returns:
            If raw_data=False: Formatted string representation
            If raw_data=True: Dictionary with entity inspection data (see BaseEntity.inspect for schema)
        """
        data = self._factory.inspect_entity(self.name, self.position)
        
        if raw_data:
            return data
        
        lines = [
            f"Container({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        # Status
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        # Contents
        inventories = data.get("inventories", {})
        contents = inventories.get("chest", {})
        if contents:
            contents_str = ", ".join([f"{name}: {count}" for name, count in contents.items()])
            lines.append(f"  Contents: {contents_str}")
        else:
            lines.append("  Contents: (empty)")
        
        return "\n".join(lines)

class WoodenChest(Container): ...

class IronChest(Container): ...


class ShipWreck(Container):
    """A ship wreck entity (crash-site entities)."""
    ...


class Furnace(BaseEntity):
    """A furnace entity."""

    # CANDO: Consider accepting List[Item] and List[ItemStack] for add_fuel and add_ingredients
    # to work seamlessly with inventory.get_item_stacks() which returns List[ItemStack].
    # Would loop in Python and make multiple remote calls (one per item/stack), similar to
    # Container.store_items() pattern. Only implement if agents frequently fail on this use case.

    def add_fuel(self, item: Union[Item, ItemStack], count: Optional[int] = None):
        """Add fuel to the furnace.
        
        Args:
            item: Item or ItemStack to add as fuel
            count: Count to add (required if Item, optional if ItemStack - uses stack count)
        """
        if isinstance(item, ItemStack):
            item_name = item.name
            fuel_count = count if count is not None else item.count
        else:
            item_name = item.name
            if count is None:
                raise ValueError("count is required when using Item (not ItemStack)")
            fuel_count = count

        return self._factory.put_inventory_item(
            self.name, self.position, "fuel", item_name, fuel_count
        )

    def add_ingredients(self, item: Union[Item, ItemStack], count: Optional[int] = None):
        """Add ingredients to the furnace's input inventory.
        
        Args:
            item: Item or ItemStack to add
            count: Count to add (required if Item, optional if ItemStack - uses stack count)
        
        Note: Currently accepts single Item or ItemStack. If agents frequently need to pass
        lists from inventory.get_item_stacks(), consider adding List[Item] and List[ItemStack]
        support (see CANDO comment above).
        """
        if isinstance(item, ItemStack):
            item_name = item.name
            input_count = count if count is not None else item.count
        else:
            item_name = item.name
            if count is None:
                raise ValueError("count is required when using Item (not ItemStack)")
            input_count = count

        return self._factory.put_inventory_item(
            self.name, self.position, "input", item_name, input_count
        )

    def take_products(
        self, item: Optional[Union[Item, ItemStack]] = None, count: Optional[int] = None
    ):
        """Get the products from the furnace's output inventory.
        
        Args:
            item: Optional Item or ItemStack to take (if None, takes any item)
            count: Count to take (required if Item, optional if ItemStack - uses stack count)
        """
        if item is None:
            item_name = ""
            take_count = count
        elif isinstance(item, ItemStack):
            item_name = item.name
            take_count = count if count is not None else item.count
        else:
            item_name = item.name
            take_count = count

        return self._factory.take_inventory_item(
            self.name, self.position, "output", item_name, take_count
        )

    def inspect(self, raw_data: bool = False) -> Union[str, Dict[str, Any]]:
        """Return a representation of furnace state.
        
        Args:
            raw_data: If False (default), returns a formatted string representation.
                      If True, returns the raw dictionary data.
        
        Returns:
            If raw_data=False: Formatted string representation
            If raw_data=True: Dictionary with entity inspection data (see BaseEntity.inspect for schema)
        """
        data = self._factory.inspect_entity(self.name, self.position)
        
        if raw_data:
            return data
        
        lines = [
            f"Furnace({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        # Status
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        # Recipe (if applicable)
        recipe = data.get("recipe")
        if recipe:
            lines.append(f"  Recipe: {recipe}")
        
        # Burner information (furnaces use burners)
        burner = data.get("burner")
        if burner:
            currently_burning = burner.get("currently_burning")
            remaining_fuel = burner.get("remaining_burning_fuel", 0)
            heat = burner.get("heat", 0)
            
            # Show currently burning if explicitly set, or if there's remaining fuel/heat
            # (indicates active burning even if currently_burning property is nil)
            if currently_burning:
                lines.append(f"  Currently Burning: {currently_burning}")
                burning_progress = burner.get("burning_progress")
                if burning_progress is not None:
                    lines.append(f"  Burning Progress: {burning_progress * 100:.1f}%")
                if remaining_fuel > 0:
                    lines.append(f"  Remaining Fuel Energy: {remaining_fuel:.0f} J")
            elif remaining_fuel > 0 or (heat > 0 and status == "working"):
                # Infer burning from remaining fuel or working status with heat
                # Try to get fuel name from fuel inventory
                inventories = data.get("inventories", {})
                fuel_inv = inventories.get("fuel", {})
                if fuel_inv:
                    # Use the first fuel item found
                    fuel_name = next(iter(fuel_inv.keys()), None)
                    if fuel_name:
                        lines.append(f"  Currently Burning: {fuel_name}")
                        if remaining_fuel > 0:
                            lines.append(f"  Remaining Fuel Energy: {remaining_fuel:.0f} J")
                    else:
                        lines.append("  Currently Burning: (active)")
                else:
                    lines.append("  Currently Burning: (active)")
            else:
                lines.append("  Currently Burning: (none)")
            
            heat_capacity = burner.get("heat_capacity", 0)
            if heat_capacity > 0:
                heat_pct = (heat / heat_capacity) * 100
                lines.append(f"  Heat: {heat:.0f}/{heat_capacity:.0f} ({heat_pct:.1f}%)")
        
        # Inventories
        inventories = data.get("inventories", {})
        
        # Fuel
        fuel = inventories.get("fuel", {})
        if fuel:
            fuel_str = ", ".join([f"{name}: {count}" for name, count in fuel.items()])
            lines.append(f"  Fuel: {fuel_str}")
        else:
            lines.append("  Fuel: (empty)")
        
        # Input
        input_inv = inventories.get("input", {})
        if input_inv:
            input_str = ", ".join([f"{name}: {count}" for name, count in input_inv.items()])
            lines.append(f"  Input: {input_str}")
        else:
            lines.append("  Input: (empty)")
        
        # Output
        output_inv = inventories.get("output", {})
        if output_inv:
            output_str = ", ".join([f"{name}: {count}" for name, count in output_inv.items()])
            lines.append(f"  Output: {output_str}")
        else:
            lines.append("  Output: (empty)")
        
        return "\n".join(lines)


class ElectricPole(BaseEntity):
    """An electric pole entity."""

    def extend(self, direction: Direction, distance: Optional[float] = None):
        """Extend the electric pole to the given direction and distance.
        No distance = MAX possible for the entity"""
        raise NotImplementedError(
            "ElectricPole.extend() is not yet implemented. "
            "This method requires implementation in the Lua mod's RemoteInterface."
        )

    def inspect(self, raw_data: bool = False) -> Union[str, Dict[str, Any]]:
        """Return a representation of electric pole state.
        
        Args:
            raw_data: If False (default), returns a formatted string representation.
                      If True, returns the raw dictionary data.
        
        Returns:
            If raw_data=False: Formatted string representation
            If raw_data=True: Dictionary with entity inspection data (see BaseEntity.inspect for schema)
        """
        data = self._factory.inspect_entity(self.name, self.position)
        
        if raw_data:
            return data
        
        lines = [
            f"ElectricPole({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        # Status
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        # Energy (if applicable)
        energy = data.get("energy")
        if energy:
            current = energy.get("current", 0)
            capacity = energy.get("capacity", 0)
            if capacity > 0:
                energy_pct = (current / capacity) * 100
                lines.append(f"  Energy: {current:.0f}/{capacity:.0f} ({energy_pct:.1f}%)")
        
        return "\n".join(lines)


class Inserter(BaseEntity):
    """Base inserter entity."""

    @property
    def prototype(self) -> InserterPrototype:
        """Get the prototype for this inserter type."""
        return get_entity_prototypes().inserter

    def get_drop_position(self) -> MapPosition:
        """Get the output position of the inserter."""
        if self.direction is None:
            raise ValueError("Inserter direction must be set to calculate drop position")
        return self.prototype.drop_position(self.position, self.direction)

    def get_pickup_position(self) -> MapPosition:
        """Get the input position of the inserter."""
        if self.direction is None:
            raise ValueError("Inserter direction must be set to calculate pickup position")
        return self.prototype.pickup_position(self.position, self.direction)

    def inspect(self, raw_data: bool = False) -> Union[str, Dict[str, Any]]:
        """Return a representation of inserter state.
        
        Args:
            raw_data: If False (default), returns a formatted string representation.
                      If True, returns the raw dictionary data.
        
        Returns:
            If raw_data=False: Formatted string representation
            If raw_data=True: Dictionary with entity inspection data (see BaseEntity.inspect for schema)
        """
        data = self._factory.inspect_entity(self.name, self.position)
        
        if raw_data:
            return data
        
        lines = [
            f"Inserter({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        # Status
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        # Held item
        held_item = data.get("held_item")
        if held_item:
            lines.append(f"  Held Item: {held_item['name']} x{held_item['count']}")
        else:
            lines.append("  Held Item: (none)")
        
        return "\n".join(lines)


class FastInserter(Inserter):
    """Fast inserter entity."""

    @property
    def prototype(self) -> FastInserterPrototype:
        """Get the prototype for this long-handed inserter type."""
        return get_entity_prototypes().fast_inserter


class LongHandInserter(Inserter):
    """Long-handed inserter entity."""

    @property
    def prototype(self) -> LongHandedInserterPrototype:
        """Get the prototype for this long-handed inserter type."""
        return get_entity_prototypes().long_handed_inserter

class AssemblingMachine(BaseEntity):
    """An assembling machine entity."""

    def set_recipe(self, recipe: Union[str, "Recipe"]) -> str:
        """Set the recipe of the assembling machine.
        
        Args:
            recipe: Recipe name (string) or Recipe object with .name attribute
        """
        # Handle both string and Recipe object
        if isinstance(recipe, str):
            recipe_name = recipe
        elif hasattr(recipe, 'name'):
            recipe_name = recipe.name
        else:
            raise ValueError(f"recipe must be a string or Recipe object, got {type(recipe)}")
        
        return self._factory.set_entity_recipe(self.name, self.position, recipe_name)

    def get_recipe(self) -> Optional[str]:
        """Get the current recipe of the assembling machine.
        
        Note: This method is not yet fully implemented. It will raise NotImplementedError.
        To get recipe information, use get_reachable() and inspect the entity data.
        """
        raise NotImplementedError(
            "AssemblingMachine.get_recipe() is not yet implemented. "
            "This method requires a query method in the Lua mod's RemoteInterface. "
            "To get recipe information, use get_reachable() and inspect the entity data."
        )

    def inspect(self, raw_data: bool = False) -> Union[str, Dict[str, Any]]:
        """Return a representation of assembling machine state.
        
        Args:
            raw_data: If False (default), returns a formatted string representation.
                      If True, returns the raw dictionary data.
        
        Returns:
            If raw_data=False: Formatted string representation
            If raw_data=True: Dictionary with entity inspection data (see BaseEntity.inspect for schema)
        """
        data = self._factory.inspect_entity(self.name, self.position)
        
        if raw_data:
            return data
        
        lines = [
            f"AssemblingMachine({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        # Status
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        # Recipe
        recipe = data.get("recipe")
        if recipe:
            lines.append(f"  Recipe: {recipe}")
        else:
            lines.append("  Recipe: (none)")
        
        # Crafting progress
        crafting_progress = data.get("crafting_progress")
        if crafting_progress is not None:
            lines.append(f"  Crafting Progress: {crafting_progress * 100:.1f}%")
        
        # Productivity bonus
        productivity_bonus = data.get("productivity_bonus")
        if productivity_bonus and productivity_bonus > 0:
            lines.append(f"  Productivity Bonus: {productivity_bonus * 100:.1f}%")
        
        # Inventories
        inventories = data.get("inventories", {})
        
        # Input
        input_inv = inventories.get("input", {})
        if input_inv:
            input_str = ", ".join([f"{name}: {count}" for name, count in input_inv.items()])
            lines.append(f"  Input: {input_str}")
        else:
            lines.append("  Input: (empty)")
        
        # Output
        output_inv = inventories.get("output", {})
        if output_inv:
            output_str = ", ".join([f"{name}: {count}" for name, count in output_inv.items()])
            lines.append(f"  Output: {output_str}")
        else:
            lines.append("  Output: (empty)")
        
        # Energy (if applicable)
        energy = data.get("energy")
        if energy:
            current = energy.get("current", 0)
            capacity = energy.get("capacity", 0)
            if capacity > 0:
                energy_pct = (current / capacity) * 100
                lines.append(f"  Energy: {current:.0f}/{capacity:.0f} ({energy_pct:.1f}%)")
        
        return "\n".join(lines)
    
    def get_output_items(self) -> ItemStack:
        return ItemStack.from_result


class TransportBelt(BaseEntity):
    """A transport belt entity."""

    @property
    def prototype(self) -> TransportBeltPrototype:
        """Get the prototype for this transport belt type."""
        return get_entity_prototypes().transport_belt
    
    @property
    def selection_box(self) -> BoundingBox:
        """Get the selection box of the transport belt."""
        return BoundingBox.from_tuple(self.prototype["selection_box"])

    def extend(self, turn: Optional[Literal["left", "right"]] = None) -> bool:
        """Extend the transport belt by one entity."""
        if turn is not None and turn not in ["left", "right"]:
            raise ValueError(f"Invalid turn: {turn}")
        direction = self.direction
        if turn == "left":
            direction = self.direction.turn_left()
        elif turn == "right":
            direction = self.direction.turn_right()
        position = self.position.offset(offset=(1, 1), direction=direction) # TODO: get offset from prototypes
        return self._factory.place_entity(self.name, position, direction)

    def inspect(self, raw_data: bool = False) -> Union[str, Dict[str, Any]]:
        """Return a representation of transport belt state.
        
        Args:
            raw_data: If False (default), returns a formatted string representation.
                      If True, returns the raw dictionary data.
        
        Returns:
            If raw_data=False: Formatted string representation
            If raw_data=True: Dictionary with entity inspection data (see BaseEntity.inspect for schema)
        """
        data = self._factory.inspect_entity(self.name, self.position)
        
        if raw_data:
            return data
        
        lines = [
            f"TransportBelt({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        return "\n".join(lines)


class Splitter(BaseEntity):
    """A splitter entity."""
    
    def inspect(self, raw_data: bool = False) -> Union[str, Dict[str, Any]]:
        """Return a representation of splitter state.
        
        Args:
            raw_data: If False (default), returns a formatted string representation.
                      If True, returns the raw dictionary data.
        
        Returns:
            If raw_data=False: Formatted string representation
            If raw_data=True: Dictionary with entity inspection data (see BaseEntity.inspect for schema)
        """
        data = self._factory.inspect_entity(self.name, self.position)
        
        if raw_data:
            return data
        
        lines = [
            f"Splitter({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        return "\n".join(lines)

class ElectricMiningDrill(BaseEntity):
    """An electric mining drill entity.
    
    Direction is REQUIRED for mining drills as they have directional output positions.
    """
    
    def __init__(self, name: str, position: MapPosition, direction: Optional[Direction] = None, **kwargs):
        super().__init__(name, position, direction, **kwargs)
        if self.direction is None:
            raise ValueError(
                f"ElectricMiningDrill requires direction to be set. "
                f"Entity at ({position.x}, {position.y}) is missing direction data. "
                f"This is likely a data serialization issue - direction should be provided by the mod."
            )

    @property
    def prototype(self) -> ElectricMiningDrillPrototype:
        """Get the prototype for this electric mining drill type."""
        return get_entity_prototypes().electric_mining_drill

    def place_adjacent(self, side: Literal["left", "right"]) -> bool:
        """Place an adjacent mining drill on left or right side."""
        placeable_item = "electric-mining-drill"
        return self._factory.place_entity(placeable_item, self.position, self.direction)

    def output_position(self) -> MapPosition:
        """Get the output position of the mining drill."""
        # Direction is guaranteed to exist due to __init__ assertion
        return self.prototype.output_position(self.position, self.direction)

    def get_search_area(self) -> BoundingBox:
        """Get the search area of the mining drill."""
        return self.prototype.get_resource_search_area(self.position)

    def inspect(self, raw_data: bool = False) -> Union[str, Dict[str, Any]]:
        """Return a representation of electric mining drill state.
        
        Args:
            raw_data: If False (default), returns a formatted string representation.
                      If True, returns the raw dictionary data.
        
        Returns:
            If raw_data=False: Formatted string representation
            If raw_data=True: Dictionary with entity inspection data (see BaseEntity.inspect for schema)
        """
        data = self._factory.inspect_entity(self.name, self.position)
        
        if raw_data:
            return data
        
        lines = [
            f"ElectricMiningDrill({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        # Mining progress
        mining_progress = data.get("mining_progress")
        if mining_progress is not None:
            lines.append(f"  Mining Progress: {mining_progress:.1f}")
        
        # Energy (if applicable)
        energy = data.get("energy")
        if energy:
            current = energy.get("current", 0)
            capacity = energy.get("capacity", 0)
            if capacity > 0:
                energy_pct = (current / capacity) * 100
                lines.append(f"  Energy: {current:.0f}/{capacity:.0f} ({energy_pct:.1f}%)")
        
        return "\n".join(lines)


class BurnerMiningDrill(BaseEntity):
    """A burner mining drill entity.
    
    Direction is REQUIRED for mining drills as they have directional output positions.
    """
    
    def __init__(self, name: str, position: MapPosition, direction: Optional[Direction] = None, **kwargs):
        super().__init__(name, position, direction, **kwargs)
        if self.direction is None:
            raise ValueError(
                f"BurnerMiningDrill requires direction to be set. "
                f"Entity at ({position.x}, {position.y}) is missing direction data. "
                f"This is likely a data serialization issue - direction should be provided by the mod."
            )
    
    @property
    def prototype(self) -> BurnerMiningDrillPrototype:
        """Get the prototype for this burner mining drill type."""
        return get_entity_prototypes().burner_mining_drill
    
    @property
    def output_position(self) -> MapPosition:
        """Get the output position of the mining drill."""
        # Direction is guaranteed to exist due to __init__ assertion
        return self.prototype.output_position(self.position, self.direction)

    def get_valid_output_positions(self, target: Union['BaseEntity', 'PlaceableItem']) -> List[MapPosition]:
        """
        Returns valid center positions for a target entity to pick up items from this drill.
        Enforces strict grid exclusivity (no tile overlap).
        """
        candidates = []
        
        # 1. Determine Source (Self) Tile Footprint
        # Factorio centers even-sized entities on integer coordinates.
        # A 2x2 at x=42 occupies x=[41, 43].
        s_half_w = self.tile_width / 2.0
        s_half_h = self.tile_height / 2.0
        
        src_left = self.position.x - s_half_w
        src_right = self.position.x + s_half_w
        src_top = self.position.y - s_half_h
        src_bottom = self.position.y + s_half_h

        # 2. Determine Target Geometry
        t_width = target.tile_width
        t_height = target.tile_height
        t_half_w = t_width / 2.0
        t_half_h = t_height / 2.0

        # 3. Identify Drop Tile
        # Use the exact output position
        drop_pos = self.output_position
        drop_tile_x = math.floor(drop_pos.x)
        drop_tile_y = math.floor(drop_pos.y)

        # 4. Generate Candidates
        # Iterate over every relative tile offset the target could have
        for dx in range(t_width):
            for dy in range(t_height):
                # Calculate Candidate Footprint
                # If target's (dx, dy) tile is the drop tile:
                target_left = drop_tile_x - dx
                target_top = drop_tile_y - dy
                
                target_right = target_left + t_width
                target_bottom = target_top + t_height
                
                # 5. Strict Grid Overlap Check (AABB)
                # Logic: If max_x < min_x, they are disjoint.
                # Since we are using exact tile boundaries (integers), 
                # we use strictly less/greater to allow touching edges.
                # E.g. Src Right (41) can touch Target Left (41).
                
                is_disjoint = (
                    target_right <= src_left or  # Target is fully to the left
                    target_left >= src_right or  # Target is fully to the right
                    target_bottom <= src_top or  # Target is fully above
                    target_top >= src_bottom     # Target is fully below
                )
                
                if not is_disjoint:
                    continue # They overlap on the grid
                
                # If valid, calculate center
                center_x = target_left + t_half_w
                center_y = target_top + t_half_h
                candidates.append(MapPosition(center_x, center_y))
                
        def alignment_deviation(pos: MapPosition) -> float:
            # Calculate how far 'pos' is off-center relative to 'self.position'
            # perpendicular to the direction of flow.
            
            if self.direction in (Direction.NORTH, Direction.SOUTH):
                # Vertical Flow: Minimize Horizontal (X) Deviation
                return abs(pos.x - self.position.x)
            
            elif self.direction in (Direction.EAST, Direction.WEST):
                # Horizontal Flow: Minimize Vertical (Y) Deviation
                return abs(pos.y - self.position.y)
            
            return 0.0 # Should not happen for cardinal directions

        # Sort in place: Smallest deviation (0.0) comes first
        candidates.sort(key=alignment_deviation)
        return candidates
    
    def get_search_area(self) -> BoundingBox:
        """Get the search area of the mining drill."""
        return self.prototype.get_resource_search_area(self.position)
    
    def inspect(self, raw_data: bool = False) -> Union[str, Dict[str, Any]]:
        """Return a representation of burner mining drill state.
        
        Args:
            raw_data: If False (default), returns a formatted string representation.
                      If True, returns the raw dictionary data.
        
        Returns:
            If raw_data=False: Formatted string representation
            If raw_data=True: Dictionary with entity inspection data (see BaseEntity.inspect for schema)
        """
        data = self._factory.inspect_entity(self.name, self.position)
        
        if raw_data:
            return data
        
        lines = [
            f"BurnerMiningDrill({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        # Mining progress
        mining_progress = data.get("mining_progress")
        if mining_progress is not None:
            lines.append(f"  Mining Progress: {mining_progress:.1f}")
        
        # Burner information
        burner = data.get("burner")
        if burner:
            currently_burning = burner.get("currently_burning")
            if currently_burning:
                lines.append(f"  Currently Burning: {currently_burning}")
            heat = burner.get("heat", 0)
            heat_capacity = burner.get("heat_capacity", 0)
            if heat_capacity > 0:
                heat_pct = (heat / heat_capacity) * 100
                lines.append(f"  Heat: {heat:.0f}/{heat_capacity:.0f} ({heat_pct:.1f}%)")
        
        # Fuel inventory
        inventories = data.get("inventories", {})
        fuel = inventories.get("fuel", {})
        if fuel:
            fuel_str = ", ".join([f"{name}: {count}" for name, count in fuel.items()])
            lines.append(f"  Fuel Inventory: {fuel_str}")
        else:
            lines.append("  Fuel Inventory: (empty)")
        
        # Output inventory
        output = inventories.get("output", {})
        if output:
            output_str = ", ".join([f"{name}: {count}" for name, count in output.items()])
            lines.append(f"  Output: {output_str}")
        else:
            lines.append("  Output: (empty)")
        
        return "\n".join(lines)
    
    def add_fuel(self, item: Union[Item, ItemStack, List[Item], List[ItemStack]], count: Optional[int] = None):
        """Add fuel to the burner mining drill.
        
        Args:
            item: Item, ItemStack, or list of Items/ItemStacks to add as fuel
            count: Count to add (required if Item, optional if ItemStack - uses stack count)
                  Ignored if item is a list (uses each stack's count)
        
        Raises:
            ValueError: If the item is not a valid chemical fuel type
        """
        # Handle lists (from inventory.get_item_stacks())
        if isinstance(item, list):
            results = []
            for stack in item:
                results.append(self.add_fuel(stack))
            return results
        
        # Handle single ItemStack
        if isinstance(item, ItemStack):
            item_name = item.name
            fuel_count = count if count is not None else item.count
        # Handle single Item
        else:
            item_name = item.name
            if count is None:
                raise ValueError("count is required when using Item (not ItemStack)")
            fuel_count = count

        # Validate fuel type
        from FactoryVerse.dsl.prototypes import get_item_prototypes
        item_protos = get_item_prototypes()
        
        if not item_protos.is_fuel(item_name):
            valid_fuels = item_protos.get_fuel_items()
            raise ValueError(
                f"Cannot add '{item_name}' as fuel to {self.name}. "
                f"Valid fuel items: {', '.join(sorted(valid_fuels))}"
            )
        
        # Check if this burner mining drill accepts this fuel category
        fuel_category = item_protos.get_fuel_category(item_name)
        
        # Burner mining drills only accept chemical fuel
        if fuel_category != 'chemical':
            raise ValueError(
                f"Cannot add '{item_name}' (fuel_category={fuel_category}) to {self.name}. "
                f"Burner mining drills only accept chemical fuels: wood, coal, solid-fuel, rocket-fuel, nuclear-fuel"
            )

        return self._factory.put_inventory_item(
            self.name, self.position, "fuel", item_name, fuel_count
        )

    def take_products(
        self, item: Optional[Union[Item, ItemStack]] = None, count: Optional[int] = None
    ):
        """Get the products from the burner mining drill's output inventory.
        
        Args:
            item: Optional Item or ItemStack to take (if None, takes any item)
            count: Count to take (required if Item, optional if ItemStack - uses stack count)
        """
        if item is None:
            item_name = ""
            take_count = count
        elif isinstance(item, ItemStack):
            item_name = item.name
            take_count = count if count is not None else item.count
        else:
            item_name = item.name
            take_count = count

        return self._factory.take_inventory_item(
            self.name, self.position, "output", item_name, take_count
        )


class Pumpjack(BaseEntity):
    """A pumpjack entity."""

    @property
    def prototype(self) -> PumpjackPrototype:
        """Get the prototype for this pumpjack type."""
        return get_entity_prototypes().pumpjack

    def get_output_pipe_connections(self) -> List[MapPosition]:
        """Get the output pipe connections of the pumpjack."""
        return self.prototype.output_pipe_connections(self.position)

    def inspect(self, raw_data: bool = False) -> Union[str, Dict[str, Any]]:
        """Return a representation of pumpjack state.
        
        Args:
            raw_data: If False (default), returns a formatted string representation.
                      If True, returns the raw dictionary data.
        
        Returns:
            If raw_data=False: Formatted string representation
            If raw_data=True: Dictionary with entity inspection data (see BaseEntity.inspect for schema)
        """
        data = self._factory.inspect_entity(self.name, self.position)
        
        if raw_data:
            return data
        
        lines = [
            f"Pumpjack({self.name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        
        status = data.get("status", "unknown")
        lines.append(f"  Status: {status}")
        
        # Energy (if applicable)
        energy = data.get("energy")
        if energy:
            current = energy.get("current", 0)
            capacity = energy.get("capacity", 0)
            if capacity > 0:
                energy_pct = (current / capacity) * 100
                lines.append(f"  Energy: {current:.0f}/{capacity:.0f} ({energy_pct:.1f}%)")
        
        return "\n".join(lines)


def create_entity_from_data(entity_data: Dict[str, Any]) -> BaseEntity:
    """Factory function to create the appropriate Entity subclass from raw data.
    
    Args:
        entity_data: Raw entity data dict from get_reachable()
        
    Returns:
        BaseEntity instance (or appropriate subclass)
    """
    name = entity_data.get("name", "")
    position_data = entity_data.get("position", {})
    position = MapPosition(x=position_data.get("x", 0), y=position_data.get("y", 0))
    
    # Parse bounding box if available
    bbox_data = entity_data.get("bounding_box")
    if bbox_data:
        # Handle different bounding box formats
        if "left_top" in bbox_data and "right_bottom" in bbox_data:
            left_top = Position(x=bbox_data["left_top"]["x"], y=bbox_data["left_top"]["y"])
            right_bottom = Position(x=bbox_data["right_bottom"]["x"], y=bbox_data["right_bottom"]["y"])
        elif "min_x" in bbox_data:
            # Alternative format from serialize.lua
            left_top = Position(x=bbox_data["min_x"], y=bbox_data["min_y"])
            right_bottom = Position(x=bbox_data["max_x"], y=bbox_data["max_y"])
        else:
            # Fallback
            left_top = Position(x=position.x, y=position.y)
            right_bottom = Position(x=position.x + 1, y=position.y + 1)
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
            dir_value = entity_data["direction"]
            # Handle both int and string representations
            if isinstance(dir_value, (int, float)):
                direction = Direction(int(dir_value))
            elif isinstance(dir_value, str):
                # Try to parse string representation of number
                direction = Direction(int(float(dir_value)))
        except (ValueError, KeyError, TypeError):
            pass
    
    # Fallback to direction_name if direction parsing failed
    if direction is None and "direction_name" in entity_data:
        direction_name = entity_data["direction_name"].upper()
        direction_map = {
            "NORTH": Direction.NORTH,
            "EAST": Direction.EAST,
            "SOUTH": Direction.SOUTH,
            "WEST": Direction.WEST,
        }
        direction = direction_map.get(direction_name)
    
    # Map entity names to specific classes
    entity_map = {
        "electric-mining-drill": ElectricMiningDrill,
        "burner-mining-drill": BurnerMiningDrill,
        "pumpjack": Pumpjack,
        "inserter": Inserter,
        "fast-inserter": FastInserter,
        "long-handed-inserter": LongHandInserter,
        "transport-belt": TransportBelt,
        "splitter": Splitter,
        "assembling-machine-1": AssemblingMachine,
        "assembling-machine-2": AssemblingMachine,
        "assembling-machine-3": AssemblingMachine,
        "stone-furnace": Furnace,
        "steel-furnace": Furnace,
        "electric-furnace": Furnace,
        "small-electric-pole": ElectricPole,
        "medium-electric-pole": ElectricPole,
        "big-electric-pole": ElectricPole,
        "substation": ElectricPole,
        "wooden-chest": WoodenChest,
        "iron-chest": IronChest,
        "steel-chest": Container,
        "crash-site-chest-1": ShipWreck,
        "crash-site-chest-2": ShipWreck,
        "crash-site-spaceship": ShipWreck,
        "crash-site-spaceship-wreck-big-1": ShipWreck,
        "crash-site-spaceship-wreck-big-2": ShipWreck,
        "crash-site-spaceship-wreck-medium-1": ShipWreck,
        "crash-site-spaceship-wreck-medium-2": ShipWreck,
        "crash-site-spaceship-wreck-medium-3": ShipWreck,
    }
    
    entity_class = entity_map.get(name, BaseEntity)
    
    return entity_class(
        name=name,
        position=position,
        bounding_box=bounding_box,
        direction=direction
    )
