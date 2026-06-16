"""Electric pole entity implementations.

Electric poles distribute power.
"""

from typing import List, Optional, TYPE_CHECKING
from pydantic import BaseModel, Field
from FactoryVerse.game.factory.entity.base_entity import BaseEntity

if TYPE_CHECKING:
    from FactoryVerse.game.factory.types import BoundingBox


class PoleNeighbour(BaseModel):
    """An entity wired to / supplied by this pole. name+position so the agent
    can act on it (entities are referenced by name+position, never unit_number)."""

    name: str
    position: Optional[dict] = None


class ElectricPoleState(BaseModel):
    """State for electric pole entities.

    Source: Lua inspect_electric_pole (copper wire connector + supply-area scan)
    """

    electric_network_id: Optional[int] = None
    is_connected: Optional[bool] = None
    # Poles wired to this one via copper wire (name+position refs)
    connected_poles: List[PoleNeighbour] = Field(default_factory=list)
    # Entities inside the supply area (refs capped at ~50 Lua-side; count is exact)
    supply_area_entities: List[PoleNeighbour] = Field(default_factory=list)
    supply_area_entity_count: int = 0


class ElectricPoleMixin:
    """Mixin for electric pole entities."""

    is_ghost: bool

    def _get_electric_pole_state(self, inspection_data: dict) -> ElectricPoleState:
        """Get electric pole state from inspection data.

        Delegates to the transform module (single source of truth for the
        Lua-payload -> state mapping; the previous duplicate stub here drifted).
        """
        if self.is_ghost:
            return ElectricPoleState()

        from FactoryVerse.game.factory.entity.transform import _transform_electric_pole

        state = _transform_electric_pole(
            inspection_data, inspection_data.get("entity_type", "electric-pole")
        )
        return state if state else ElectricPoleState()


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
        from FactoryVerse.game.factory.types import BoundingBox

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
