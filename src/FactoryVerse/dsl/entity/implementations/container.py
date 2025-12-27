"""Container entity implementations.

Containers are entities that store items in their inventory.
Includes: WoodenChest, IronChest, SteelChest, ShipWreck
"""

from typing import Optional, Dict
from FactoryVerse.dsl.types import MapPosition, Direction
from FactoryVerse.dsl.mixins import ContainerMixin
from FactoryVerse.dsl.entity.base_entity import BaseEntity


class Container(ContainerMixin, BaseEntity):
    """A container entity with inventory.

    **For Agents**: Chests store items. Use store_items() and take_items() to move items in/out.
    """

    def __init__(
        self,
        name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        inventory_size: int = 0,
        **kwargs,
    ):
        super().__init__(name, position, direction, **kwargs)
        self.inventory_size = inventory_size

    def _get_inventory_type(self) -> str:
        """Containers use 'chest' inventory type."""
        return "chest"

    def _format_inspection(self, data: Dict) -> str:
        """Format container inspection data.

        Args:
            data: Raw inspection data from the game

        Returns:
            Formatted string for agent consumption
        """
        from FactoryVerse.dsl.entity.inspect import BaseInspectionData

        inspection = BaseInspectionData(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=MapPosition.from_dict(data["position"]),
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
        )

        # Add inventory info if available
        lines = [str(inspection)]
        inventories = data.get("inventories", {})
        if inventories.get("chest"):
            chest_str = ", ".join(
                [f"{name}: {count}" for name, count in inventories["chest"].items()]
            )
            lines.append(f"  Contents: {chest_str}")
        else:
            lines.append("  Contents: (empty)")

        return "\n".join(lines)


class WoodenChest(Container):
    """Wooden chest - basic storage container."""

    pass


class IronChest(Container):
    """Iron chest - medium storage container."""

    pass


class SteelChest(Container):
    """Steel chest - large storage container."""

    pass


class ShipWreck(Container):
    """A ship wreck entity (crash-site entities)."""

    pass
