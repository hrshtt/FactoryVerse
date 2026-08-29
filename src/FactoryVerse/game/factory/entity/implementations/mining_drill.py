"""Mining drill entity implementations.

Mining drills extract resources from the ground.
"""

from typing import List, Optional
from FactoryVerse.game.factory.types import MapPosition, Direction
from FactoryVerse.game.factory.entity.base_entity import BaseEntity
from FactoryVerse.game.factory.entity.capabilities import (
    BurnerMixin,
    ElectricMixin,
    MinerMixin,
    RotatableMixin,
)


class _DropArrowMirror:
    """Same-named twin of ``EntityReference.drop_position``: where a drill of
    this type at ``position`` facing ``direction`` drops its output."""

    def drop_position(self, position=None, direction=None):
        from FactoryVerse.game.agent.entity_reference import EntityReference
        from FactoryVerse.game.factory.types import Direction as _D

        pos = position if position is not None else self.position
        d = direction if direction is not None else (getattr(self, "direction", None) or _D.NORTH)
        return EntityReference(self.name).drop_position(pos, d)


class ElectricMiningDrill(_DropArrowMirror, MinerMixin, ElectricMixin, RotatableMixin, BaseEntity):
    """Electric mining drill - extracts ore using electricity.

    Capabilities: miner, electric, rotatable
    Direction is REQUIRED as drills have directional output.
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
                f"ElectricMiningDrill requires direction. "
                f"Entity at ({position.x}, {position.y}) is missing direction."
            )
        self.direction = direction


class BurnerMiningDrill(_DropArrowMirror, MinerMixin, BurnerMixin, RotatableMixin, BaseEntity):
    """Burner mining drill - extracts ore using fuel.

    Capabilities: miner, burner, rotatable
    Needs fuel to operate. Use add_fuel() to refuel.
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
                f"BurnerMiningDrill requires direction. "
                f"Entity at ({position.x}, {position.y}) is missing direction."
            )
        self.direction = direction

    def _get_accepted_fuel_categories(self) -> List[str]:
        """Burner drills accept chemical fuel."""
        return ["chemical"]
