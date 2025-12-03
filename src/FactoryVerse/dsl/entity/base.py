import pydantic
from typing import List, Optional, Any, Dict, Literal, Union
from src.FactoryVerse.dsl.types import MapPosition, BoundingBox, AnchorVector, Direction
from src.FactoryVerse.dsl.item.base import PlaceableItemName, ItemName, Item, ItemStack
from src.FactoryVerse.dsl.agent import PlayingFactory, _playing_factory
from src.FactoryVerse.dsl.prototypes import (
    get_entity_prototypes,
    ElectricMiningDrillPrototype,
    PumpjackPrototype,
    InserterPrototype,
    LongHandedInserterPrototype,
)


class BaseEntity(pydantic.BaseModel):
    """Base class for all entities."""

    name: str
    position: MapPosition
    bounding_box: BoundingBox
    direction: Optional[Direction] = None

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

    def pickup(self) -> bool:
        """Pick up the entity."""
        return self._factory.pickup_entity(self.name, self.position)


class Container(BaseEntity):
    """A container entity."""

    inventory_size: int


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

    def extend_to(self, direction: Direction, distance: Optional[float] = None):
        """Extend the electric pole to the given direction and distance."""
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

    def extend_to(self, direction: Direction, distance: Optional[float] = None):
        """Extend the inserter to the given direction and distance."""
        return self._factory.extend_inserter(self.name, self.position, direction, distance)



class FastInserter(Inserter): ...

    # def extend_to(self, direction: Direction, distance: Optional[float] = None):
    #     """Extend the fast inserter to the given direction and distance."""
    #     if distance is None:
    #         return self._factory.extend_fast_inserter(self.name, self.position, direction)
    #     else:
    #         return self._factory.extend_fast_inserter(self.name, self.position, direction, distance)


class LongHandInserter(Inserter):
    """Long-handed inserter entity."""

    @property
    def prototype(self) -> LongHandedInserterPrototype:
        """Get the prototype for this long-handed inserter type."""
        return get_entity_prototypes().long_handed_inserter

    def extend_to(self, direction: Direction, distance: Optional[float] = None):
        """Extend the long hand inserter to the given direction and distance."""
        if distance is None:
            self._factory.rcon.execute_command(
                f"extend_long_hand_inserter {self.name} {self.position.x} {self.position.y} {direction.value}"
            )
        else:
            self._factory.rcon.execute_command(
                f"extend_long_hand_inserter {self.name} {self.position.x} {self.position.y} {direction.value} {distance}"
            )

class AssemblingMachine(BaseEntity):
    """An assembling machine entity."""

    def set_recipe(self, recipe: Union[ItemName, PlaceableItemName]) -> bool: # TODO: Implement Recipe literal
        """Set the recipe of the assembling machine."""
        return self._factory.set_assembling_machine_recipe(self.name, self.position, recipe)

    def get_input_type(self) -> ItemName:
        """Get the input type of the assembling machine."""
        return self._factory.get_assembling_machine_input_type(self.name, self.position)
    
    def get_output_type(self) -> ItemName:
        """Get the output type of the assembling machine."""
        return self._factory.get_assembling_machine_output_type(self.name, self.position)


class TransportBelt(BaseEntity):
    """A transport belt entity."""

    def extend_by_one(self, direction: Optional[Direction] = None) -> bool:
        """Extend the transport belt by one entity."""
        if direction is None:
            direction = self.direction
        return self._factory.place_entity(self.name, self.position, direction)


class Splitter(BaseEntity):
    """A splitter entity."""
    ...

class ElectricMiningDrill(BaseEntity):
    """An electric mining drill entity."""

    @property
    def prototype(self) -> ElectricMiningDrillPrototype:
        """Get the prototype for this electric mining drill type."""
        return get_entity_prototypes().electric_mining_drill

    def place_adjacent(self, placeable_item: PlaceableItemName) -> bool:
        """Place an adjacent mining drill."""
        if placeable_item != "electric-mining-drill":
            raise ValueError(f"Invalid placeable item: {placeable_item}")
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
