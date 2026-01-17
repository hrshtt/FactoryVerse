"""Electric pole entity implementations.

Electric poles distribute power.
"""

from typing import List, Optional, TYPE_CHECKING
from pydantic import BaseModel, Field
from FactoryVerse.factory.entity.base_entity import BaseEntity

if TYPE_CHECKING:
    from FactoryVerse.factory.types import BoundingBox


class ElectricPoleState(BaseModel):
    """State for electric pole entities (stub - implement later).

    Source: runtime_inspection.jsonl electric pole fields
    """

    electric_network_id: Optional[int] = None
    connected_poles: List[str] = Field(default_factory=list)  # Entity names
    supply_area_entities: int = 0  # Count of entities in supply area


class ElectricPoleMixin:
    """Mixin for electric pole entities (stub)."""

    is_ghost: bool

    def _get_electric_pole_state(self, inspection_data: dict) -> ElectricPoleState:
        """Get electric pole state from inspection data."""
        if self.is_ghost:
            return ElectricPoleState()

        # Parse connected poles
        connected = []
        neighbours = inspection_data.get("neighbours", [])
        if isinstance(neighbours, list):
            for n in neighbours:
                if n and n.get("name"):
                    connected.append(n["name"])

        return ElectricPoleState(
            electric_network_id=inspection_data.get("electric_network_id"),
            connected_poles=connected,
        )


class ElectricPole(ElectricPoleMixin, BaseEntity):
    """Electric pole - distributes power.

    **For Agents**: Connects to other poles to form power network.
    """

    def get_supply_area(self) -> "BoundingBox":
        """Calculate power supply area (static, geometric).

        Returns a bounding box representing the area where this pole
        can supply power to entities.

        Returns:
            BoundingBox covering the supply area

        Example:
            >>> pole = get_entity("small-electric-pole", pos)
            >>> supply_area = pole.get_supply_area()
        """
        from FactoryVerse.factory.types import BoundingBox

        distance = self.prototype["supply_area_distance"]
        x, y = self.position.x, self.position.y
        return BoundingBox.from_tuple(
            ((x - distance, y - distance), (x + distance, y + distance))
        )

    @property
    def supply_area_distance(self) -> float:
        """Get supply area radius from prototype."""
        return self.prototype["supply_area_distance"]

    @property
    def maximum_wire_distance(self) -> float:
        """Get maximum wire connection distance from prototype."""
        return self.prototype["maximum_wire_distance"]


class SmallElectricPole(ElectricPole):
    """Small electric pole - basic, short range."""

    pass


class MediumElectricPole(ElectricPole):
    """Medium electric pole - longer range, larger supply area."""

    pass


class BigElectricPole(ElectricPole):
    """Big electric pole - very long range, no supply area."""

    pass


class Substation(ElectricPole):
    """Substation - long range with large supply area."""

    pass
