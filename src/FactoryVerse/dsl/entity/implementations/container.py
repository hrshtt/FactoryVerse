"""Container entity implementations.

Containers store items.
Includes: WoodenChest, IronChest, SteelChest, ShipWreck (crash site chests)
"""

from typing import Dict, Optional
from FactoryVerse.dsl.types import MapPosition, Direction
from FactoryVerse.dsl.entity.base_entity import BaseEntity
from FactoryVerse.dsl.entity.inspect import ContainerInspection


class Container(BaseEntity):
    """A container entity (chest).

    **For Agents**: Containers store items. Use take_inventory_item() and put_inventory_item()
    to transfer items.
    """

    def _format_inspection(self, data: Dict) -> str:
        """Format container inspection data.

        Args:
            data: Raw inspection data from Lua (matches inspect_container output)

        Returns:
            Formatted string for agent consumption
        """
        pos_data = data.get("position", {})
        position = MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0))

        inspection = ContainerInspection(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=position,
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
            contents=data.get("contents"),  # Direct from Lua
            inventory_bar=data.get("inventory_bar"),
            inventory_size_override=data.get("inventory_size_override"),
            storage_filter=data.get("storage_filter"),
            filter_slot_count=data.get("filter_slot_count"),
            filters=data.get("filters"),
            request_from_buffers=data.get("request_from_buffers"),
        )
        return str(inspection)


class WoodenChest(Container):
    """Wooden chest - basic storage."""

    pass


class IronChest(Container):
    """Iron chest - medium storage."""

    pass


class SteelChest(Container):
    """Steel chest - large storage."""

    pass


class ShipWreck(Container):
    """Ship wreck / crash site chest - special container from crashes."""

    pass
