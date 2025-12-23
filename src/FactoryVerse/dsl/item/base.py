from typing import List, Optional, Union, Any, Dict, Tuple, Literal, TYPE_CHECKING
from FactoryVerse.dsl.types import MapPosition, Direction
from FactoryVerse.dsl.prototypes import get_item_prototypes, get_entity_prototypes, BasePrototype
from FactoryVerse.dsl.mixins import FactoryContextMixin, SpatialPropertiesMixin, PrototypeMixin

if TYPE_CHECKING:
    from FactoryVerse.dsl.agent import PlayingFactory
    from FactoryVerse.dsl.entity.base import ReachableEntity, GhostEntity


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


class Item:
    """Base class for all items.
    
    Items are things in inventory that can be used, consumed, or placed.
    They have prototypes that define their properties.
    """

    def __init__(self, name: Union[ItemName, PlaceableItemName]):
        self.name = name
        self._prototype_cache: Optional[Dict[str, Any]] = None

    @property
    def _item_prototype_data(self) -> Dict[str, Any]:
        """Get cached item prototype data.
        
        Lazily loads and caches the item prototype on first access.
        """
        if self._prototype_cache is None:
            prototypes = get_item_prototypes()
            self._prototype_cache = prototypes.data.get("item", {}).get(self.name, {})
        return self._prototype_cache

    @property
    def stack_size(self) -> int:
        """Get stack size from prototype data."""
        return self._item_prototype_data.get("stack_size", 50)


class RawMaterial(Item):
    """Raw material item."""
    def __init__(self, name: Union[ItemName, PlaceableItemName]):
        super().__init__(name)
        self.subgroup: ItemSubgroup = "raw-material"


class RawResource(Item):
    """Raw resource item."""
    def __init__(self, name: Union[ItemName, PlaceableItemName]):
        super().__init__(name)
        self.subgroup: ItemSubgroup = "raw-resource"


class IntermediateProduct(Item):
    """Intermediate product item."""
    def __init__(self, name: Union[ItemName, PlaceableItemName]):
        super().__init__(name)
        self.subgroup: ItemSubgroup = "intermediate-product"


class Module(Item):
    """Module item."""
    def __init__(self, name: Union[ItemName, PlaceableItemName]):
        super().__init__(name)
        self.subgroup: ItemSubgroup = "module"


class SciencePack(Item):
    """Science pack item."""
    def __init__(self, name: Union[ItemName, PlaceableItemName]):
        super().__init__(name)
        self.subgroup: ItemSubgroup = "science-pack"


class Fuel(Item):
    """Fuel item with energy properties."""
    def __init__(
        self,
        name: Union[ItemName, PlaceableItemName],
        fuel_value: Optional[float] = None,
        fuel_category: Optional[Literal["chemical", "nuclear"]] = None,
        burnt_result: Optional[ItemName] = None,
        fuel_acceleration_multiplier: Optional[float] = None,
        fuel_top_speed_multiplier: Optional[float] = None
    ):
        super().__init__(name)
        self.fuel_value = fuel_value
        self.fuel_category = fuel_category
        self.burnt_result = burnt_result
        self.fuel_acceleration_multiplier = fuel_acceleration_multiplier
        self.fuel_top_speed_multiplier = fuel_top_speed_multiplier


class PlaceableItem(FactoryContextMixin, SpatialPropertiesMixin, PrototypeMixin, Item):
    """Items that can be placed as entities.
    
    These items have a place_result in their prototype, pointing to the entity they create.
    Provides spatial awareness (tile dimensions) for placement reasoning.
    
    **For Agents**: These are items you can place in the world (furnaces, drills, chests, etc.).
    Use tile_width and tile_height for spatial planning before placing.
    """

    def __init__(self, name: PlaceableItemName):
        super().__init__(name)
        self._entity_prototype_cache: Optional[BasePrototype] = None

    def _load_prototype(self) -> BasePrototype:
        """Load entity prototype by resolving item's place_result.
        
        Items need to know what entity they become when placed, so we:
        1. Load item prototype
        2. Get place_result (entity name)
        3. Load entity prototype for that entity
        """
        item_protos = get_item_prototypes()
        place_result = item_protos.get_place_result(self.name)
        if place_result:
            entity_protos = get_entity_prototypes()
            entity_type = entity_protos.get_entity_type(place_result)
            if entity_type and entity_type in entity_protos.data:
                entity_data = entity_protos.data[entity_type].get(place_result, {})
                return BasePrototype(_data=entity_data)
        # Fallback to empty prototype if no place_result
        return BasePrototype(_data={})

    def place(
        self, position: MapPosition, direction: Optional[Direction] = Direction.NORTH
    ) -> "ReachableEntity":
        """Place this item as an entity on the map.

        Returns the created ReachableEntity instance.
        """
        from FactoryVerse.dsl.entity.base import (
            ReachableEntity,
            ElectricMiningDrill,
            BurnerMiningDrill,
            Pumpjack,
            Inserter,
            FastInserter,
            LongHandInserter,
            TransportBelt,
            Splitter,
            AssemblingMachine,
            Furnace,
            ElectricPole,
            WoodenChest,
            IronChest,
            Container,
        )
        
        result = self._factory.place_entity(self.name, position, direction, ghost=False)
        if not result.get("success"):
            error_msg = result.get("error", "Unknown error")
            raise RuntimeError(f"Failed to place entity: {error_msg}")
        
        # Use actual position from result if available
        result_pos = result.get("position", position)
        if isinstance(result_pos, dict):
            position = MapPosition(x=result_pos["x"], y=result_pos["y"])
        
        # Get entity name from result (might differ from item name in some cases)
        entity_name = result.get("entity_name", self.name)
        
        # Map entity names to specific classes (same as create_entity_from_data)
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
        }
        
        entity_class = entity_map.get(entity_name, ReachableEntity)
        
        # For Container subclasses, we need inventory_size from prototypes
        if entity_class in (WoodenChest, IronChest, Container):
            from FactoryVerse.dsl.prototypes import get_entity_prototypes
            entity_protos = get_entity_prototypes()
            entity_type = entity_protos.get_entity_type(entity_name)
            
            # Try to get inventory_size from prototype data
            inventory_size = None
            if entity_type and entity_type in entity_protos.data:
                entities = entity_protos.data[entity_type]
                if isinstance(entities, dict) and entity_name in entities:
                    entity_data = entities[entity_name]
                    # Container entities have inventory_size in their prototype
                    if "inventory_size" in entity_data:
                        inventory_size = entity_data["inventory_size"]
            
            if inventory_size is not None:
                # We have inventory_size, create the proper container class
                return entity_class(
                    name=entity_name,
                    position=position,
                    direction=direction,
                    inventory_size=inventory_size
                )
            else:
                # Fallback to ReachableEntity if we can't get inventory_size
                entity_class = ReachableEntity
        
        return entity_class(name=entity_name, position=position, direction=direction)

    def place_ghost(
        self, 
        position: MapPosition, 
        direction: Optional[Direction] = Direction.NORTH,
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
        from FactoryVerse.dsl.entity.base import GhostEntity
        result = self._factory.place_entity(self.name, position, direction, ghost=True, label=label)
        if not result.get("success"):
            error_msg = result.get("error", "Unknown error")
            raise RuntimeError(f"Failed to place ghost entity: {error_msg}")
        
        # Use actual position from result if available
        result_pos = result.get("position", position)
        if isinstance(result_pos, dict):
            position = MapPosition(x=result_pos["x"], y=result_pos["y"])
        
        return GhostEntity(name=self.name, position=position, direction=direction)



class PlacementCues:
    """Wrapper for placement cues that provides smart repr to avoid context spam.
    
    Placement cues contain two separate lists:
    - positions: All valid positions in scanned chunks (5x5 chunks around agent)
    - reachable_positions: Valid positions within agent's build distance
    """
    
    def __init__(self, data: Dict[str, Any], entity_name: str):
        self.entity_name = entity_name
        self._data = data
        
        # Extract positions and reachable_positions
        self._all_cues = data.get("positions", [])
        self._reachable_cues = data.get("reachable_positions", [])
        
        # Cache for MapPosition conversions
        self._positions_cache: Optional[List[MapPosition]] = None
        self._reachable_positions_cache: Optional[List[MapPosition]] = None
    
    @property
    def positions(self) -> List[MapPosition]:
        """Get all valid positions as MapPosition objects (from scanned chunks)."""
        if self._positions_cache is None:
            self._positions_cache = [
                MapPosition(x=cue["position"]["x"], y=cue["position"]["y"])
                for cue in self._all_cues
            ]
        return self._positions_cache
    
    @property
    def reachable_positions(self) -> List[MapPosition]:
        """Get reachable positions as MapPosition objects (within build distance)."""
        if self._reachable_positions_cache is None:
            self._reachable_positions_cache = [
                MapPosition(x=cue["position"]["x"], y=cue["position"]["y"])
                for cue in self._reachable_cues
            ]
        return self._reachable_positions_cache
    
    @property
    def count(self) -> int:
        """Total number of placement cues (all positions)."""
        return len(self._all_cues)
    
    @property
    def reachable_count(self) -> int:
        """Number of reachable placement cues."""
        return len(self._reachable_cues)
    
    def by_resource(self) -> Dict[str, List[MapPosition]]:
        """Group all positions by resource name (for mining drills/pumpjacks)."""
        groups: Dict[str, List[MapPosition]] = {}
        for cue in self._all_cues:
            resource = cue.get("resource_name", "any")
            if resource not in groups:
                groups[resource] = []
            groups[resource].append(MapPosition(x=cue["position"]["x"], y=cue["position"]["y"]))
        return groups
    
    def reachable_by_resource(self) -> Dict[str, List[MapPosition]]:
        """Group reachable positions by resource name."""
        groups: Dict[str, List[MapPosition]] = {}
        for cue in self._reachable_cues:
            resource = cue.get("resource_name", "any")
            if resource not in groups:
                groups[resource] = []
            groups[resource].append(MapPosition(x=cue["position"]["x"], y=cue["position"]["y"]))
        return groups
    
    def __len__(self) -> int:
        return len(self._all_cues)
    
    def __getitem__(self, index: int) -> Dict[str, Any]:
        return self._all_cues[index]
    
    def __iter__(self):
        return iter(self._all_cues)
    
    def __repr__(self) -> str:
        """Smart repr that shows preview without spamming context."""
        if not self._all_cues:
            return f"PlacementCues(entity='{self.entity_name}', count=0, reachable=0)"
        
        # Group by resource if available
        by_resource = self.by_resource()
        
        # Check if we have resource information (not just "any")
        has_resources = len(by_resource) > 0 and "any" not in by_resource
        
        if has_resources and len(by_resource) > 1:
            # Multiple resources - show summary with resource breakdown
            resource_summary = ", ".join([f"{k}: {len(v)}" for k, v in by_resource.items()])
            return (
                f"PlacementCues(entity='{self.entity_name}', count={self.count}, reachable={self.reachable_count}, "
                f"by_resource={{{resource_summary}}})"
            )
        elif has_resources and len(by_resource) == 1:
            # Single resource - show resource name in summary
            resource_name = list(by_resource.keys())[0]
            return (
                f"PlacementCues(entity='{self.entity_name}', resource='{resource_name}', "
                f"count={self.count}, reachable={self.reachable_count})"
            )
        else:
            # No resource grouping (water, or generic entities)
            return (
                f"PlacementCues(entity='{self.entity_name}', count={self.count}, reachable={self.reachable_count})"
            )



class PlacementCueMixin(FactoryContextMixin):
    """Mixin for items that require placement cues (mining drills, pumpjack, offshore-pump).
    
    **For Agents**: Use get_placement_cues() to find valid positions for resource-dependent entities.
    """

    def get_placement_cues(self, resource_name: Optional[str] = None) -> PlacementCues:
        """Get valid placement positions for this item type.

        Args:
            resource_name: Optional resource name to filter by (e.g., "copper-ore", "iron-ore", "coal")

        Returns PlacementCues object with:
        - positions: All valid positions in scanned chunks
        - reachable_positions: Valid positions within build distance
        
        **IMPORTANT**: Placement cues are extremely granular and can contain thousands of positions.
        Do not randomly pick positions - use them to verify planned positions are valid.
        Always ensure you are in vicinity of the scanned area before using these cues.
        """
        data = self._factory.get_placement_cues(self.name, resource_name=resource_name)
        return PlacementCues(data, self.name)



class MiningDrillItem(PlaceableItem, PlacementCueMixin):
    """Mining drill item (burner or electric) - requires placement cues.

    Handles both "electric-mining-drill" and "burner-mining-drill" based on name.
    """
    pass


class PumpjackItem(PlaceableItem, PlacementCueMixin):
    """Pumpjack item - requires placement cues."""
    pass


class OffshorePumpItem(PlaceableItem, PlacementCueMixin):
    """Offshore pump item - requires placement cues."""
    pass


class PlaceAsEntityItem(Item):
    """Legacy class - use PlaceableItem instead."""
    
    def __init__(self, name: Union[ItemName, PlaceableItemName], place_result: PlaceableItemName):
        super().__init__(name)
        self.place_result = place_result


class ItemStack:
    """Item stack representing a quantity of items.
    
    A stack is just an Item + count. Access individual items via indexing.
    Example: stack[0].place(position) to place one item from the stack.
    """

    def __init__(
        self,
        name: str,
        count: int,
        subgroup: Union[ItemSubgroup, PlaceableItemSubgroup, str] = "raw-material"
    ):
        self.name = name
        self.count = count
        self.subgroup = subgroup
        self._item_cache: Optional[Item] = None

    @property
    def item(self) -> Item:
        """Get the Item object for this stack (cached)."""
        if self._item_cache is None:
            self._item_cache = get_item(self.name)
        return self._item_cache

    @property
    def stack_size(self) -> int:
        """Get stack size from prototype data."""
        return self.item.stack_size

    @property
    def half(self) -> int:
        """Get half of the stack count."""
        return self.count // 2

    @property
    def full(self) -> int:
        """Get full stack count."""
        return self.count

    def __repr__(self) -> str:
        """Simple, explicit representation of the item stack."""
        return f"{self.__class__.__name__}(name='{self.name}', count={self.count})"
    
    def __getitem__(self, index: int) -> Item:
        """Get a single item from the stack.
        
        Args:
            index: Index of the item (must be < count)
        
        Returns:
            The Item object
        
        Example:
            >>> stack = inventory.get_item("stone-furnace")
            >>> stack[0].place(position)  # Place one item from stack
        """
        if index >= self.count:
            raise IndexError(f"Stack only has {self.count} items, cannot access index {index}")
        return self.item
    
    def __iter__(self):
        """Iterate over individual items in the stack."""
        for _ in range(self.count):
            yield self.item
    
    def __len__(self) -> int:
        """Get the count of items in the stack."""
        return self.count

class BeltLine(FactoryContextMixin, ItemStack):
    """A belt line item stack with belt-specific operations.
    
    **For Agents**: Use for placing lines of belts efficiently.
    """
    
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
    
    from FactoryVerse.dsl.prototypes import get_item_prototypes, get_entity_prototypes

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
