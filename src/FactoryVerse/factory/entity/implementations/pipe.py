"""Pipe and fluid storage entity implementations.

Pipes transport fluids between entities.
Storage tanks store large amounts of fluid.
"""

from typing import Optional
from FactoryVerse.factory.types import MapPosition, Direction
from FactoryVerse.factory.entity.base_entity import BaseEntity
from FactoryVerse.factory.entity.capabilities import (
    FluidMixin,
    RotatableMixin,
)


class StorageTank(FluidMixin, RotatableMixin, BaseEntity):
    """Storage tank - stores large amounts of fluid.

    **For Agents**: Can hold 25,000 units of a single fluid type.
    Connect with pipes. Direction affects visual orientation but
    fluid connections work in all directions.
    """

    def __init__(
        self,
        name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        **kwargs,
    ):
        super().__init__(name, position, **kwargs)
        # Direction is optional for storage tanks (defaults to NORTH)
        self.direction = direction or Direction.NORTH


class Pipe(FluidMixin, BaseEntity):
    """Pipe - transports fluids between entities.

    **For Agents**: Connect fluid-producing entities (offshore pumps, chemical plants)
    to fluid-consuming entities (boilers, refineries). Pipes automatically connect
    to adjacent pipes and entities with fluid connections.
    """

    pass


class PipeToGround(FluidMixin, RotatableMixin, BaseEntity):
    """Pipe-to-ground - underground pipe connection.

    **For Agents**: Like underground belts but for fluids. Place two facing
    each other to create underground connection. Direction determines which
    end (input/output) this is. Maximum underground distance varies by tier.
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
                f"PipeToGround requires direction. "
                f"Entity at ({position.x}, {position.y}) is missing direction."
            )
        self.direction = direction
