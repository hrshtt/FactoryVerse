import pydantic
from typing import List, Optional, Any, Dict, Literal, Union
from src.FactoryVerse.dsl.types import MapPosition, BoundingBox, AnchorVector, Direction
from src.FactoryVerse.dsl.item.base import PlaceableItemName, ItemName
from src.FactoryVerse.dsl.agent import PlayingFactory, _playing_factory


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

    def add_fuel(self, item_name: str, count: int):
        """Add fuel to the furnace."""

        return self._factory.put_inventory_item(
            self.name, self.position, "fuel", item_name, count
        )

    def put_input_items(self, item_name: str, count: int):
        """Add an item to the furnace's input inventory."""
        return self._factory.set_entity_inventory_item(
            self.name, self.position, "input", item_name, count
        )

    def take_output_items(self, item_name: Optional[str] = None, count: Optional[int] = None):
        """Get the item from the furnace's output inventory."""
        return self._factory.take_inventory_item(self.name, self.position, "output", item_name, count)


class ElectricPole(BaseEntity):
    """An electric pole entity."""

    def extend_to(self, direction: Direction, distance: Optional[float] = None):
        """Extend the electric pole to the given direction and distance."""
        return self._factory.extend_electric_pole(self.name, self.position, direction, distance)


class Inserter(BaseEntity):

    def get_drop_position(self) -> MapPosition:
        """Get the output position of the inserter."""
        return self._factory.get_inserter_output_position(self.name, self.position)

    def get_pickup_position(self) -> MapPosition:
        """Get the input position of the inserter."""
        return self._factory.get_inserter_input_position(self.name, self.position)

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

    def __init__(self, name: str, position: MapPosition, direction: Direction):
        super().__init__(name, position, direction)
        # self.properties = PrototypeProperties(name)
        self.prototype = self._factory.prototypes.electric_mining_drill
    
    def place_adjacent(self, placeable_item: PlaceableItemName) -> bool:
        if placeable_item != "electric-mining-drill":
            raise ValueError(f"Invalid placeable item: {placeable_item}")
        return self._factory.place_entity(placeable_item, self.position, self.direction)

    def output_position(self) -> MapPosition:
        """Get the output position of the mining drill."""
        return self.prototype.output_position(self.position, self.direction)
    
    def get_search_area(self) -> BoundingBox:
        """Get the search area of the mining drill."""
        return self.prototype.get_resource_search_area(self.position)


class BurnerMiningDrill(BaseEntity):
    """A burner mining drill entity."""
    ...


class Pumpjack(BaseEntity):
    """A pumpjack entity."""

    def __init__(self, name: str, position: MapPosition, direction: Direction):
        super().__init__(name, position, direction)
        self.prototype = self._factory.prototypes.pumpjack
    
    def get_output_pipe_connections(self) -> List[MapPosition]:
        """Get the output pipe connections of the pumpjack."""
        return self.prototype.output_pipe_connections(self.position)
