"""Pumpjack entity implementation.

Pumpjacks extract crude oil from oil patches.
"""

from typing import Optional
from FactoryVerse.factory.types import MapPosition, Direction
from FactoryVerse.factory.entity.base_entity import BaseEntity
from FactoryVerse.factory.entity.capabilities import (
    MinerMixin,
    ElectricMixin,
    FluidMixin,
    RotatableMixin,
)


class Pumpjack(MinerMixin, ElectricMixin, FluidMixin, RotatableMixin, BaseEntity):
    """Pumpjack - extracts crude oil from oil patches.

    **For Agents**: Must be placed on oil deposits. Output goes through fluid pipe.
    Direction is REQUIRED as pumpjacks have directional fluid outputs.
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
                f"Pumpjack requires direction. "
                f"Entity at ({position.x}, {position.y}) is missing direction."
            )
        self.direction = direction
