import pydantic
from typing import List, Optional, Union, Any, Dict, Tuple, Literal
from src.FactoryVerse.dsl.types import MapPosition, Direction
from src.FactoryVerse.dsl.agent import PlayingFactory, _playing_factory
from src.FactoryVerse.dsl.entity.base import BaseEntity, GhostEntity
from src.FactoryVerse.dsl.prototypes import get_item_prototypes


ItemSubgroup = Literal[
    "barrel",
    "intermediate-product",
    "module",
    "raw-material",
    "raw-resource",
    "science-pack",
    "terrain",
    "uranium-processing",
]
ItemName = Literal[
    "stone-brick",
    "wood",
    "coal",
    "stone",
    "iron-ore",
    "copper-ore",
    "iron-plate",
    "copper-plate",
    "copper-cable",
    "iron-stick",
    "iron-gear-wheel",
    "electronic-circuit",
    "steel-plate",
    "engine-unit",
    "solid-fuel",
    "rocket-fuel",
    "concrete",
    "refined-concrete",
    "hazard-concrete",
    "refined-hazard-concrete",
    "landfill",
    "uranium-ore",
    "advanced-circuit",
    "processing-unit",
    "sulfur",
    "barrel",
    "plastic-bar",
    "electric-engine-unit",
    "explosives",
    "battery",
    "flying-robot-frame",
    "low-density-structure",
    "nuclear-fuel",
    "rocket-part",
    "uranium-235",
    "uranium-238",
    "uranium-fuel-cell",
    "depleted-uranium-fuel-cell",
    "empty-module-slot",
    "science",
    "water-barrel",
    "sulfuric-acid-barrel",
    "crude-oil-barrel",
    "heavy-oil-barrel",
    "light-oil-barrel",
    "petroleum-gas-barrel",
    "lubricant-barrel",
]

FuelItemName = Literal[
    "coal",
    "solid-fuel",
    "rocket-fuel",
    "nuclear-fuel",
    "wood",
]

PlaceableItemSubgroup = Literal[
    "belt",
    "energy",
    "energy-pipe-distribution",
    "extraction-machine",
    "inserter",
    "module",
    "production-machine",
    "smelting-machine",
    "storage",
]

PlaceableItemName = Literal[
    "wooden-chest",
    "stone-furnace",
    "burner-mining-drill",
    "electric-mining-drill",
    "burner-inserter",
    "inserter",
    "fast-inserter",
    "long-handed-inserter",
    "offshore-pump",
    "pipe",
    "boiler",
    "steam-engine",
    "small-electric-pole",
    "pipe-to-ground",
    "assembling-machine-1",
    "assembling-machine-2",
    "lab",
    "electric-furnace",
    "iron-chest",
    "big-electric-pole",
    "medium-electric-pole",
    "steel-furnace",
    "steel-chest",
    "solar-panel",
    "accumulator",
    "transport-belt",
    "fast-transport-belt",
    "express-transport-belt",
    "bulk-inserter",
    "assembling-machine-3",
    "underground-belt",
    "fast-underground-belt",
    "express-underground-belt",
    "splitter",
    "fast-splitter",
    "express-splitter",
    "loader",
    "fast-loader",
    "express-loader",
    "substation",
    "beacon",
    "storage-tank",
    "pump",
    "pumpjack",
    "oil-refinery",
    "chemical-plant",
    "nuclear-reactor",
    "centrifuge",
    "heat-exchanger",
    "steam-turbine",
    "heat-pipe",
]


class Item(pydantic.BaseModel):
    """Base class for all items."""

    name: Union[ItemName, PlaceableItemName]

    @property
    def stack_size(self) -> int:
        """Get stack size from prototype data."""
        # TODO: Implement item prototype lookup
        # For now, return default stack sizes

        prototypes = get_item_prototypes()
        # Items are in prototypes.data["item"][self.name]["stack_size"]
        item_data = prototypes.data.get("item", {}).get(self.name, {})
        return item_data.get("stack_size", 50)  # Default to 50 if not found


class RawMaterial(Item):
    subgroup: ItemSubgroup = "raw-material"


class RawResource(Item):
    subgroup: ItemSubgroup = "raw-resource"


class IntermediateProduct(Item):
    subgroup: ItemSubgroup = "intermediate-product"


class Module(Item):
    subgroup: ItemSubgroup = "module"


class SciencePack(Item):
    subgroup: ItemSubgroup = "science-pack"


class Fuel(Item):
    fuel_value: Optional[float] = None
    fuel_category: Optional[Literal["chemical", "nuclear"]] = None
    burnt_result: Optional[ItemName] = None
    fuel_acceleration_multiplier: Optional[float] = None
    fuel_top_speed_multiplier: Optional[float] = None


class PlaceableItem(Item):
    """Base class for items that can be placed as entities."""

    name: PlaceableItemName  # Constrained to placeable items only

    @property
    def _factory(self) -> "PlayingFactory":
        """Get the current playing factory context."""
        factory = _playing_factory.get()
        if factory is None:
            raise RuntimeError(
                "No active gameplay session. "
                "Use 'with playing_factory(rcon, agent_id):' to enable item operations."
            )
        return factory

    def place(
        self, position: MapPosition, direction: Optional[Direction] = None
    ) -> BaseEntity:
        """Place this item as an entity on the map.

        Returns the created BaseEntity instance.
        """
        options = {}
        if direction is not None:
            options["direction"] = direction.value

        result = self._factory.place_entity(self.name, position, options)
        # TODO: Convert result to BaseEntity based on entity type
        # For now, return a placeholder
        raise NotImplementedError(
            "Entity creation from placement result not yet implemented"
        )

    def place_ghost(self, position: MapPosition, direction: Optional[Direction] = None) -> GhostEntity:
        """Place this item as a ghost entity on the map.

        Returns the created GhostEntity instance.
        """
        result = self._factory.place_entity(self.name, position, direction, ghost=True)
        if not result.success:
            raise RuntimeError(f"Failed to place ghost entity: {result.error}")
        return GhostEntity(name=self.name, position=position, direction=direction)


class PlacementCueMixin:
    """Mixin for items that require placement cues (mining drills, pumpjack, offshore-pump)."""

    @property
    def _factory(self) -> "PlayingFactory":
        """Get the current playing factory context."""
        factory = _playing_factory.get()
        if factory is None:
            raise RuntimeError(
                "No active gameplay session. "
                "Use 'with playing_factory(rcon, agent_id):' to enable item operations."
            )
        return factory

    def get_placement_cues(self) -> List[Dict[str, Any]]:
        """Get valid placement positions for this item type.

        Returns list of {position: MapPosition, can_place: bool, direction?: Direction}
        Scans 5x5 chunks (160x160 tiles) around agent.
        """
        return self._factory.get_placement_cues(self.name)


class MiningDrillItem(PlaceableItem, PlacementCueMixin):
    """Mining drill item (burner or electric) - requires placement cues.

    Handles both "electric-mining-drill" and "burner-mining-drill" based on name.
    """

    name: Literal["electric-mining-drill", "burner-mining-drill"]


class PumpjackItem(PlaceableItem, PlacementCueMixin):
    """Pumpjack item - requires placement cues."""

    name: Literal["pumpjack"]


class OffshorePumpItem(PlaceableItem, PlacementCueMixin):
    """Offshore pump item - requires placement cues."""

    name: Literal["offshore-pump"]


class PlaceAsEntityItem(Item):
    """Legacy class - use PlaceableItem instead."""

    place_result: PlaceableItemName


class ItemStack(pydantic.BaseModel):
    """Item stack with count information from inventory."""

    name: Union[ItemName, PlaceableItemName]
    subgroup: Union[ItemSubgroup, PlaceableItemSubgroup]
    count: int

    @property
    def stack_size(self) -> int:
        """Get stack size from prototype data."""
        from src.FactoryVerse.dsl.prototypes import get_entity_prototypes

        prototypes = get_entity_prototypes()
        item_data = prototypes.data.get("item", {}).get(self.name, {})
        return item_data.get("stack_size", 50)

    @property
    def half(self) -> int:
        """Get half of the stack count."""
        return self.count // 2

    @property
    def full(self) -> int:
        """Get full stack count."""
        return self.count

class BeltLine(ItemStack):
    """A belt line item stack."""
    def get_ghost_line(self, position: MapPosition, length: int, direction: Direction) -> GhostEntity:
        """Get a ghost line of the belt."""
        return self._factory.get_ghost_line(self.name, position, length, direction)

    def get_ghost(self, position: MapPosition) -> GhostEntity:
        """Get a ghost entity at the position."""
        return self._factory.get_ghost(self.name, position)

    def get_ghost_line(self, position: MapPosition, length: int, direction: Direction) -> GhostEntity:
        """Get a ghost line of the belt."""
        return self._factory.get_ghost_line(self.name, position, length, direction)


def get_item(name: Union[ItemName, PlaceableItemName]) -> Item:

    if name not in PlaceableItemName:
        raise ValueError(f"Invalid item name: {name}")
    if name == "pumpjack":
        return PumpjackItem(name=name)
    elif name == "offshore-pump":
        return OffshorePumpItem(name=name)
    elif name == "electric-mining-drill":
        return MiningDrillItem(name=name)
    elif name == "burner-mining-drill":
        return MiningDrillItem(name=name)
    else:
        return PlaceableItem(name=name)


def create_item_stack(items: List[Dict[Literal["name", "count"], Any]]) -> List[ItemStack]:
    """Create a list of item stacks from a list of dictionaries."""
    return [
        ItemStack(name=get_item(item["name"]), count=item["count"]) for item in items
    ]
