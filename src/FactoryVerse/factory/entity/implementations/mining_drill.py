"""Mining drill entity implementations.

Mining drills extract resources from the ground.
"""

from typing import List, Optional
from FactoryVerse.factory.types import MapPosition, Direction
from FactoryVerse.factory.entity.base_entity import BaseEntity
from FactoryVerse.factory.entity.capabilities import (
    BurnerMixin,
    ElectricMixin,
    MinerMixin,
    RotatableMixin,
)


class ElectricMiningDrill(MinerMixin, ElectricMixin, RotatableMixin, BaseEntity):
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


class BurnerMiningDrill(MinerMixin, BurnerMixin, RotatableMixin, BaseEntity):
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
