"""Mining drill entity implementations.

Mining drills extract resources from the ground.
Includes: ElectricMiningDrill, BurnerMiningDrill
"""

from typing import List, Optional, Dict
from FactoryVerse.dsl.types import MapPosition, Direction
from FactoryVerse.dsl.mixins import CrafterMixin, FuelableMixin
from FactoryVerse.dsl.entity.base_entity import BaseEntity


class ElectricMiningDrill(BaseEntity):
    """An electric mining drill entity.

    Direction is REQUIRED for mining drills as they have directional output positions.
    """

    def __init__(
        self,
        name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        **kwargs,
    ):
        super().__init__(name, position, direction, **kwargs)
        if self.direction is None:
            raise ValueError(
                f"ElectricMiningDrill requires direction to be set. "
                f"Entity at ({position.x}, {position.y}) is missing direction data."
            )

    def _format_inspection(self, data: Dict) -> str:
        """Format electric mining drill inspection data.

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
        return str(inspection)


class BurnerMiningDrill(CrafterMixin, FuelableMixin, BaseEntity):
    """A burner mining drill entity.

    Direction is REQUIRED for mining drills as they have directional output positions.
    """

    def __init__(
        self,
        name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        **kwargs,
    ):
        super().__init__(name, position, direction, **kwargs)
        if self.direction is None:
            raise ValueError(
                f"BurnerMiningDrill requires direction to be set. "
                f"Entity at ({position.x}, {position.y}) is missing direction data."
            )

    def _get_accepted_fuel_categories(self) -> List[str]:
        """Burner drills accept chemical fuel."""
        return ["chemical"]

    def _format_inspection(self, data: Dict) -> str:
        """Format burner mining drill inspection data.

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

        # Add fuel info if available
        lines = [str(inspection)]
        inventories = data.get("inventories", {})
        if inventories.get("fuel"):
            fuel_str = ", ".join(
                [f"{name}: {count}" for name, count in inventories["fuel"].items()]
            )
            lines.append(f"  Fuel: {fuel_str}")

        return "\n".join(lines)
