import pydantic
from typing import List, Optional, Union, Any, Dict, Tuple, Literal, TYPE_CHECKING
from src.FactoryVerse.dsl.types import MapPosition, Direction
from src.FactoryVerse.dsl.prototypes import get_item_prototypes

if TYPE_CHECKING:
    from src.FactoryVerse.dsl.agent import PlayingFactory
    from src.FactoryVerse.dsl.entity.base import BaseEntity, GhostEntity


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
        from src.FactoryVerse.dsl.agent import _playing_factory
        factory = _playing_factory.get()
        if factory is None:
            raise RuntimeError(
                "No active gameplay session. "
                "Use 'with playing_factory(rcon, agent_id):' to enable item operations."
            )
        return factory

    def place(
        self, position: MapPosition, direction: Optional[Direction] = None
    ) -> "BaseEntity":
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

    def place_ghost(
        self, 
        position: MapPosition, 
        direction: Optional[Direction] = None,
        label: Optional[str] = None
    ) -> "GhostEntity":
        """Place this item as a ghost entity on the map.

        Args:
            position: Position to place the ghost
            direction: Optional direction for the ghost
            label: Optional label for grouping/staging (e.g., "bootstrap", "production")

        Returns:
            The created GhostEntity instance.
        """
        from src.FactoryVerse.dsl.entity.base import GhostEntity
        result = self._factory.place_entity(self.name, position, direction, ghost=True, label=label)
        if not result.get("success"):
            error_msg = result.get("error", "Unknown error")
            raise RuntimeError(f"Failed to place ghost entity: {error_msg}")
        
        # Use actual position from result if available
        result_pos = result.get("position", position)
        if isinstance(result_pos, dict):
            position = MapPosition(x=result_pos["x"], y=result_pos["y"])
        
        return GhostEntity(name=self.name, position=position, direction=direction)


class PlacementCueMixin:
    """Mixin for items that require placement cues (mining drills, pumpjack, offshore-pump)."""

    @property
    def _factory(self) -> "PlayingFactory":
        """Get the current playing factory context."""
        from src.FactoryVerse.dsl.agent import _playing_factory
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

    name: str # Relaxed to str to support dynamic names
    subgroup: Union[ItemSubgroup, PlaceableItemSubgroup, str] # Relaxed to str
    count: int

    @property
    def item(self) -> "Item":
        """Get the Item object for this stack."""
        return get_item(self.name)

    @property
    def stack_size(self) -> int:
        """Get stack size from prototype data."""
        from src.FactoryVerse.dsl.prototypes import get_entity_prototypes

        prototypes = get_entity_prototypes()
        # Fallback to item lookup if not in entity prototypes (which is likely)
        # Actually prototypes.data has "item" key.
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
    
    def place(
        self, position: MapPosition, direction: Optional[Direction] = None
    ) -> "BaseEntity":
        """Place one item from this stack as an entity."""
        item = self.item
        if isinstance(item, PlaceableItem):
            return item.place(position, direction)
        raise ValueError(f"Item {self.name} is not placeable")

    def place_ghost(
        self, 
        position: MapPosition, 
        direction: Optional[Direction] = None,
        label: Optional[str] = None
    ) -> "GhostEntity":
        """Place one item from this stack as a ghost entity."""
        item = self.item
        if isinstance(item, PlaceableItem):
            return item.place_ghost(position, direction, label)
        raise ValueError(f"Item {self.name} is not placeable")
        
    def get_placement_cues(self) -> List[Dict[str, Any]]:
        """Get placement cues for this item if applicable."""
        # Check if item has the mixin or method
        item = self.item
        if hasattr(item, "get_placement_cues"):
            return item.get_placement_cues()
        return []

class BeltLine(ItemStack):
    """A belt line item stack."""
    def get_ghost_line(self, position: MapPosition, length: int, direction: Direction) -> "GhostEntity":
        """Get a ghost line of the belt."""
        return self._factory.get_ghost_line(self.name, position, length, direction)

    def get_ghost(self, position: MapPosition) -> "GhostEntity":
        """Get a ghost entity at the position."""
        return self._factory.get_ghost(self.name, position)

    def get_ghost_line_v2(self, position: MapPosition, length: int, direction: Direction) -> "GhostEntity":
        """Get a ghost line of the belt."""
        return self._factory.get_ghost_line(self.name, position, length, direction)


def get_item(name: str) -> Item:
    """Factory function to create the appropriate Item subclass based on prototype data."""
    # Note: We relax the strict input type hint to str to allow dynamic lookup, 
    # but we should ideally validate against known names if possible.
    
    from src.FactoryVerse.dsl.prototypes import get_item_prototypes, get_entity_prototypes

    item_protos = get_item_prototypes()
    place_result = item_protos.get_place_result(name)

    if not place_result:
        # Not placeable - return generic Item (or specialized if we had logic for that)
        return Item(name=name)

    # It is placeable
    entity_protos = get_entity_prototypes()
    entity_type = entity_protos.get_entity_type(place_result)

    if entity_type == "mining-drill":
        if name == "pumpjack":
            return PumpjackItem(name=name)
        return MiningDrillItem(name=name)
    
    elif entity_type == "offshore-pump":
        return OffshorePumpItem(name=name)
            
    # Default placeable
    return PlaceableItem(name=name)


def create_item_stack(items: List[Dict[str, Any]]) -> List[ItemStack]:
    """Create a list of item stacks from a list of dictionaries."""
    # subgroup defaults to something if missing
    return [
        ItemStack(
            name=item["name"], 
            count=item["count"], 
            subgroup=item.get("subgroup", "raw-material")
        ) for item in items
    ]
