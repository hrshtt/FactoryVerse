"""Pump entity implementations.

Pumps handle fluid movement: offshore pumps extract water,
regular pumps move fluid between pipe networks.
"""

from typing import Optional
from FactoryVerse.game.factory.types import MapPosition, Direction
from FactoryVerse.game.factory.entity.base_entity import BaseEntity
from FactoryVerse.game.factory.entity.capabilities import (
    FluidMixin,
    ElectricMixin,
    RotatableMixin,
)


class OffshorePump(FluidMixin, RotatableMixin, BaseEntity):
    """Offshore pump - extracts water from water tiles.

    **For Agents**: Must be placed adjacent to water. Outputs water
    through the pipe connection. Direction determines output direction.
    """

    def __init__(
        self,
        name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        **kwargs,
    ):
        super().__init__(name, position, **kwargs)
        if direction is None:
            raise ValueError(
                f"OffshorePump requires direction. "
                f"Entity at ({position.x}, {position.y}) is missing direction."
            )
        self.direction = direction


class Pump(FluidMixin, ElectricMixin, RotatableMixin, BaseEntity):
    """Pump - moves fluid between pipe networks.

    **For Agents**: Connect between pipe networks to move fluid.
    Direction determines flow direction. Requires electricity.
    """

    def __init__(
        self,
        name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        **kwargs,
    ):
        super().__init__(name, position, **kwargs)
        if direction is None:
            raise ValueError(
                f"Pump requires direction. "
                f"Entity at ({position.x}, {position.y}) is missing direction."
            )
        self.direction = direction
