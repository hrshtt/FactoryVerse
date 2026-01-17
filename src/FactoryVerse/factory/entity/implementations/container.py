"""Container entity implementations.

Containers store items.
"""

from typing import Dict, Optional, List, TYPE_CHECKING

from pydantic import BaseModel, Field
from FactoryVerse.factory.entity.base_entity import BaseEntity

if TYPE_CHECKING:
    from FactoryVerse.factory.item.base import ItemStack
    from FactoryVerse.agent.embodied_actions.entity_operations import (
        EntityOperationsAction,
    )


class ContainerState(BaseModel):
    """State for container entities.

    Source: runtime_inspection.jsonl container inventory
    """

    contents: Dict[str, int] = Field(default_factory=dict)
    inventory_size: int = 0
    filters: Dict[int, str] = Field(default_factory=dict)  # slot -> item_name

    @property
    def is_empty(self) -> bool:
        """Check if container has no items."""
        return len(self.contents) == 0

    @property
    def total_items(self) -> int:
        """Get total item count."""
        return sum(self.contents.values())


class Container(BaseEntity):
    """Container (chest) - stores items.

    **For Agents**: Use store_item/take_item to manage inventory.
    """

    _entity_ops: "EntityOperationsAction"

    def _get_container_state(self, inspection_data: dict) -> ContainerState:
        """Get container state from inspection data."""
        if self._is_ghost:
            return ContainerState()

        # Use transformer to handle Lua quirks
        from FactoryVerse.factory.entity.transform import _transform_container

        entity_type = inspection_data.get("entity_type", "container")
        container_state = _transform_container(inspection_data, entity_type)
        return container_state if container_state else ContainerState()

    def get_item_count(self, item_name: str) -> int:
        """Get count of a specific item in the container.

        Args:
            item_name: Name of the item to count

        Returns:
            Number of items in container, 0 if not present
        """
        raw_data = self._entity_ops.inspect_entity(self.name, self.position)
        state = self._get_container_state(raw_data)
        return state.contents.get(item_name, 0)

    def store_item(self, items: List["ItemStack"]) -> List:
        """Store items into the container.

        **For Agents**: Use this to put items into chests.

        Args:
            items: List of ItemStack to store

        Returns:
            List of results from storage operation
        """
        results = []
        for item in items:
            result = self._entity_ops.put_inventory_item(
                self.name,
                "chest",
                item,
                self.position,
            )
            results.append(result)
        return results

    def take_item(self, item_name: str, count: int) -> List["ItemStack"]:
        """Take items from the container.

        **For Agents**: Use this to retrieve items from chests.

        Args:
            item_name: Name of item to take
            count: Number of items to take

        Returns:
            List of ItemStack taken from container
        """
        result = self._entity_ops.take_inventory_item(
            self.name,
            "chest",
            item_name,
            count,
            self.position,
        )
        return result.to_item_stacks(self._place_ops)


class WoodenChest(Container):
    """Wooden chest - basic storage (16 slots)."""

    pass


class IronChest(Container):
    """Iron chest - medium storage (32 slots)."""

    pass


class SteelChest(Container):
    """Steel chest - large storage (48 slots)."""

    pass


class ShipWreck(Container):
    """Ship wreck / crash site chest."""

    pass
