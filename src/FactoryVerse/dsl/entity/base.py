from __future__ import annotations
from typing import List, Optional, Union, Literal, Dict, Any, TYPE_CHECKING
from src.FactoryVerse.dsl.types import MapPosition, BoundingBox, Direction, Position
from src.FactoryVerse.dsl.item.base import PlaceableItemName, ItemName, Item, ItemStack, PlaceableItem
from src.FactoryVerse.dsl.prototypes import (
    get_entity_prototypes,
    ElectricMiningDrillPrototype,
    PumpjackPrototype,
    InserterPrototype,
    LongHandedInserterPrototype,
    FastInserterPrototype,
    TransportBeltPrototype,
    BasePrototype,
    apply_cardinal_vector,
)

if TYPE_CHECKING:
    from src.FactoryVerse.dsl.agent import PlayingFactory

# Import _playing_factory safely
from src.FactoryVerse.dsl.agent import _playing_factory


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


class BaseEntity:
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
        return self._factory.put_inventory_items(self.name, self.position, items)

    def take_items(self, items: List[ItemStack]):
        """Take items from the container."""
        return self._factory.take_inventory_items(self.name, self.position, items)

class WoodenChest(Container): ...

class IronChest(Container): ...


class ShipWreck(Container):
    """A ship wreck entity (crash-site entities)."""
    ...


class Furnace(BaseEntity):
    """A furnace entity."""

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

    def put_input_items(self, item: Union[Item, ItemStack], count: Optional[int] = None):
        """Add an item to the furnace's input inventory.
        
        Args:
            item: Item or ItemStack to add
            count: Count to add (required if Item, optional if ItemStack - uses stack count)
        """
        if isinstance(item, ItemStack):
            item_name = item.name
            input_count = count if count is not None else item.count
        else:
            item_name = item.name
            if count is None:
                raise ValueError("count is required when using Item (not ItemStack)")
            input_count = count

        return self._factory.set_entity_inventory_item(
            self.name, self.position, "input", item_name, input_count
        )

    def take_output_items(
        self, item: Optional[Union[Item, ItemStack]] = None, count: Optional[int] = None
    ):
        """Get the item from the furnace's output inventory.
        
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


class ElectricPole(BaseEntity):
    """An electric pole entity."""

    def extend(self, direction: Direction, distance: Optional[float] = None):
        """Extend the electric pole to the given direction and distance.
        No distance = MAX possible for the entity"""
        return self._factory.extend_electric_pole(self.name, self.position, direction, distance)


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

    def set_recipe(self, recipe: "Recipe") -> bool: # TODO: Implement Recipe literal
        """Set the recipe of the assembling machine."""
        return self._factory.set_assembling_machine_recipe(self.name, self.position, recipe)

    def get_recipe(self) -> Optional["Recipe"]:
        """Get the input type of the assembling machine."""
        return self._factory.get_assembling_machine_input_type(self.name, self.position)
    
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


class Splitter(BaseEntity):
    """A splitter entity."""
    ...

class ElectricMiningDrill(BaseEntity):
    """An electric mining drill entity."""

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
        if self.direction is None:
            raise ValueError("Mining drill direction must be set to calculate output position")
        return self.prototype.output_position(self.position, self.direction)

    def get_search_area(self) -> BoundingBox:
        """Get the search area of the mining drill."""
        return self.prototype.get_resource_search_area(self.position)


class BurnerMiningDrill(BaseEntity):
    """A burner mining drill entity."""
    ...


class Pumpjack(BaseEntity):
    """A pumpjack entity."""

    @property
    def prototype(self) -> PumpjackPrototype:
        """Get the prototype for this pumpjack type."""
        return get_entity_prototypes().pumpjack

    def get_output_pipe_connections(self) -> List[MapPosition]:
        """Get the output pipe connections of the pumpjack."""
        return self.prototype.output_pipe_connections(self.position)


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
            direction = Direction(entity_data["direction"])
        except (ValueError, KeyError, TypeError):
            pass
    
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
