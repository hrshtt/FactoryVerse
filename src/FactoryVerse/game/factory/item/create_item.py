"""Factory functions for creating items with proper dependency injection.

All item creation should go through these factory functions to ensure
proper PlacementAction injection.
"""

from typing import List, Dict, Any, Union, Optional, TYPE_CHECKING

from .base import Item, PlaceableItem, Fuel, ItemStack

if TYPE_CHECKING:
    from FactoryVerse.game.agent.embodied_actions.place_entity import PlacementAction


def create_item(
    name: str,
    placement: "PlacementAction",
) -> Union[Item, PlaceableItem, Fuel]:
    """Create appropriate item type with injected dependencies.

    Determines the correct item class based on prototype data:
    - PlaceableItem: Items with place_result (can be placed as entities)
    - Fuel: Items with fuel_value (can be used as fuel)
    - Item: Base item class for everything else

    Args:
        name: Item prototype name
        placement: PlacementAction for placing items (injected)

    Returns:
        Item, PlaceableItem, or Fuel instance with proper dependencies
    """
    from FactoryVerse.game.factory.prototypes import (
        get_item_prototypes,
        get_entity_prototypes,
    )

    item_protos = get_item_prototypes()

    # Check if item can be placed
    place_result = item_protos.get_place_result(name)
    if place_result:
        # It's placeable - create PlaceableItem with placement injected
        return PlaceableItem(name=name, placement=placement)

    # Check if it's a fuel item by looking at prototype data
    item_data = item_protos.data.get("item", {}).get(name, {})
    if item_data.get("fuel_value") is not None:
        return Fuel(name=name)

    # Default to base Item
    return Item(name=name)


def create_item_stack(
    name: str,
    count: int,
    placement: "PlacementAction",
    subgroup: Optional[str] = None,
) -> ItemStack:
    """Create ItemStack with injected dependencies.

    Args:
        name: Item prototype name
        count: Number of items in stack
        placement: PlacementAction for placing items (injected)
        subgroup: Optional item subgroup (auto-detected from prototype if None)

    Returns:
        ItemStack with proper dependencies
    """
    # Auto-detect subgroup if not provided
    if subgroup is None:
        from FactoryVerse.game.factory.prototypes import get_item_prototypes

        item_protos = get_item_prototypes()
        item_data = item_protos.data.get("item", {}).get(name, {})
        subgroup = item_data.get("subgroup", "raw-material")

    return ItemStack(
        name=name,
        count=count,
        placement=placement,
        subgroup=subgroup,
    )


def create_item_stacks(
    items: List[Dict[str, Any]],
    placement: "PlacementAction",
) -> List[ItemStack]:
    """Create list of ItemStacks from dictionaries.

    Used for inventory results, crafting results, and entity extraction results.

    Args:
        items: List of dicts with 'name', 'count', and optional 'subgroup'
        placement: PlacementAction for placing items (injected)

    Returns:
        List of ItemStack instances with proper dependencies
    """
    return [
        create_item_stack(
            name=item["name"],
            count=item["count"],
            placement=placement,
            subgroup=item.get("subgroup"),
        )
        for item in items
    ]
