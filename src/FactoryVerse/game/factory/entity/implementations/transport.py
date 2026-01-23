"""Transport belt entity implementations.

Transport belts move items along conveyor paths.
"""

from FactoryVerse.game.factory.entity.base_entity import BaseEntity
from FactoryVerse.game.factory.entity.capabilities import (
    BeltMixin,
    RotatableMixin,
    Rotatable180Mixin,
)


class TransportBelt(BeltMixin, RotatableMixin, BaseEntity):
    """Transport belt - moves items in one direction.

    **For Agents**: Belts have left and right lanes. Use inspect() to see shape.
    """

    pass


class FastTransportBelt(TransportBelt):
    """Fast transport belt - 2x speed."""

    pass


class ExpressTransportBelt(TransportBelt):
    """Express transport belt - 3x speed."""

    pass


class UndergroundBelt(BeltMixin, RotatableMixin, BaseEntity):
    """Underground belt - goes under obstacles.

    **For Agents**: Comes in pairs (input/output). Inspect belt_to_ground_type.
    """

    pass


class FastUndergroundBelt(UndergroundBelt):
    """Fast underground belt."""

    pass


class ExpressUndergroundBelt(UndergroundBelt):
    """Express underground belt."""

    pass


class Splitter(BeltMixin, Rotatable180Mixin, BaseEntity):
    """Splitter - splits belt contents between two outputs.

    **For Agents**: Can configure input/output priority and filters.
    """

    pass


class FastSplitter(Splitter):
    """Fast splitter."""

    pass


class ExpressSplitter(Splitter):
    """Express splitter."""

    pass


class Loader(BeltMixin, RotatableMixin, BaseEntity):
    """Loader - quickly loads/unloads between belts and containers."""

    pass


class FastLoader(Loader):
    """Fast loader."""

    pass


class ExpressLoader(Loader):
    """Express loader."""

    pass
