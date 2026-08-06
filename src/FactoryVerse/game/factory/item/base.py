"""Base item classes for FactoryVerse.

Items represent things in agent inventory that can be used, consumed, or placed.
All items are agent-owned references - they exist from the perspective of what
the agent currently possesses.
"""

from typing import List, Optional, Union, Any, Dict, Tuple, Literal, TYPE_CHECKING
from FactoryVerse.game.factory.types import MapPosition, Direction
from FactoryVerse.game.factory.prototypes import (
    get_item_prototypes,
    get_entity_prototypes,
    get_width_height,
)
import math

if TYPE_CHECKING:
    from FactoryVerse.game.factory.entity.base_entity import BaseEntity
    from FactoryVerse.game.agent.embodied_actions.place_entity import PlacementAction

# Import BaseEntity for runtime isinstance checks
from FactoryVerse.game.factory.entity.base_entity import BaseEntity


# =============================================================================
# Type Literals - for filtering and research
# =============================================================================

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


# =============================================================================
# Base Item Classes
# =============================================================================


class Item:
    """Base class for all items.

    Items are things in inventory that can be used, consumed, or placed.
    They have prototypes that define their properties.

    Items are agent-owned references - they only exist when the agent
    possesses them in inventory, or has just crafted/extracted them.
    """

    def __init__(self, name: str):
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

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}('{self.name}')"


class Fuel(Item):
    """Fuel item with energy properties.

    Provides fuel-specific properties from prototype data.
    """

    @property
    def fuel_value(self) -> Optional[float]:
        """Get fuel value from prototype."""
        return self._item_prototype_data.get("fuel_value")

    @property
    def fuel_category(self) -> Optional[str]:
        """Get fuel category from prototype."""
        return self._item_prototype_data.get("fuel_category")

    @property
    def burnt_result(self) -> Optional[str]:
        """Get burnt result item name from prototype."""
        return self._item_prototype_data.get("burnt_result")


class PlaceableItem(Item):
    """Items that can be placed as entities.

    These items have a place_result in their prototype, pointing to the entity they create.
    Provides spatial awareness (tile dimensions) for placement reasoning.

    **For Agents**: These are items you can place in the world (furnaces, drills, chests, etc.).
    Use tile_width and tile_height for spatial planning before placing.
    """

    def __init__(self, name: str, placement: "PlacementAction"):
        super().__init__(name)
        self._placement = placement
        self._entity_prototype_cache: Optional[Dict[str, Any]] = None

    @property
    def prototype(self) -> Dict[str, Any]:
        """Get entity prototype data as dict that this item creates when placed.

        Loads the entity prototype by resolving the item's place_result.
        """
        if self._entity_prototype_cache is None:
            item_protos = get_item_prototypes()
            place_result = item_protos.get_place_result(self.name)
            if place_result:
                entity_protos = get_entity_prototypes()
                self._entity_prototype_cache = entity_protos.get_prototype(place_result)
            else:
                self._entity_prototype_cache = {}
        return self._entity_prototype_cache

    @property
    def tile_width(self) -> int:
        """Calculate tile width from entity prototype collision_box."""
        EPSILON = 0.001
        proto = self.prototype
        if "tile_width" in proto:
            return int(proto["tile_width"])
        if "collision_box" in proto:
            w, _ = get_width_height(proto["collision_box"])
            return int(math.ceil(w - EPSILON))
        return 0

    @property
    def tile_height(self) -> int:
        """Calculate tile height from entity prototype collision_box."""
        EPSILON = 0.001
        proto = self.prototype
        if "tile_height" in proto:
            return int(proto["tile_height"])
        if "collision_box" in proto:
            _, h = get_width_height(proto["collision_box"])
            return int(math.ceil(h - EPSILON))
        return 0

    @property
    def footprint(self) -> Tuple[int, int]:
        """Get (width, height) tuple for spatial calculations."""
        return (self.tile_width, self.tile_height)

    def place(
        self, position: MapPosition, direction: Optional[Direction] = Direction.NORTH
    ) -> "BaseEntity":
        """Place this item as an entity on the map.

        Returns the created entity with REACHABLE view.

        Args:
            position: Position to place the entity
            direction: Direction for the entity (default: NORTH)

        Returns:
            The created entity instance with REACHABLE view

        Raises:
            RuntimeError: If placement fails
        """
        # Place entity and request BaseEntity return if entity_ops is available
        result = self._placement.place(
            self.name,  # type: ignore
            position,
            direction,
            ghost=False,
            return_entity=True,  # Request BaseEntity return
        )

        # If we got a BaseEntity, return it directly
        if isinstance(result, BaseEntity):
            return result

        # Otherwise, we got EntityPlaced - check if it succeeded
        if not result.success:
            raise RuntimeError(f"Failed to place {self.name}: {result.error}")

        # Create entity from inspection
        placed_pos = result.placed_position
        if placed_pos is None:
            raise RuntimeError("Placement succeeded but position is missing")

        # Inspect the entity to get full entity data
        entity_data = self._placement._entity_ops.inspect_entity(
            self.name, placed_pos  # type: ignore
        )

        # Create BaseEntity from the inspection data
        from FactoryVerse.game.factory.entity.create_entity import create_reachable_entity

        return create_reachable_entity(
            entity_data,
            self._placement._entity_ops,
            self._placement,
            is_ghost=False,
        )

    def place_ghost(
        self,
        position: MapPosition,
        direction: Optional[Direction] = Direction.NORTH,
        label: Optional[str] = None,
    ) -> bool:
        """Place a ghost entity for this item.

        Args:
            position: Position to place the ghost
            direction: Optional direction for the ghost
            label: Optional label for grouping (stored in ghost table)

        Returns:
            True if ghost was placed successfully.

        Raises:
            RuntimeError: If placement fails
        """
        result = self._placement.place(
            self.name,  # type: ignore
            position,
            direction,
            ghost=True,
            label=label,
        )

        return result.success


# =============================================================================
# ItemStack - Item + Count
# =============================================================================


class ItemStack:
    """Item stack representing a quantity of items.

    A stack is just an Item + count. Access individual items via indexing.
    Example: stack[0].place(position) to place one item from the stack.

    Items are agent-owned references - when you have an ItemStack, those
    items are guaranteed to be in the agent's inventory.
    """

    def __init__(
        self,
        name: str,
        count: int,
        placement: "PlacementAction",
        subgroup: Union[ItemSubgroup, PlaceableItemSubgroup, str] = "raw-material",
    ):
        self.name = name
        self.count = count
        self.subgroup = subgroup
        self._placement = placement
        self._item_cache: Optional[Union[Item, PlaceableItem, Fuel]] = None

    @property
    def item(self) -> Union[Item, PlaceableItem, Fuel]:
        """Get the Item object for this stack (cached).

        Creates the item through factory logic with placement injected.
        """
        if self._item_cache is None:
            # Import here to avoid circular dependency
            from FactoryVerse.game.factory.item.create_item import create_item

            self._item_cache = create_item(self.name, self._placement)
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

    def __getitem__(self, index: int) -> Union[Item, PlaceableItem, Fuel]:
        """Get a single item from the stack.

        Args:
            index: Index of the item (must be < count)

        Returns:
            The Item object with placement injected

        Example:
            >>> stack = inventory.get_item("stone-furnace")
            >>> stack[0].place(position)  # Place one item from stack
        """
        if index >= self.count:
            raise IndexError(
                f"Stack only has {self.count} items, cannot access index {index}"
            )
        return self.item

    def __iter__(self):
        """Iterate over individual items in the stack."""
        for _ in range(self.count):
            yield self.item

    def __len__(self) -> int:
        """Get the count of items in the stack."""
        return self.count

