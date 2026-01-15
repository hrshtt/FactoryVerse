"""Generator entity implementations.

Generators produce electricity from fuel or steam.
"""

from typing import List
from pydantic import BaseModel
from FactoryVerse.factory.entity.base_entity import BaseEntity
from FactoryVerse.factory.entity.capabilities import (
    BurnerMixin,
    FluidMixin,
    ElectricMixin,
    RotatableMixin,
)


class GeneratorState(BaseModel):
    """State for generator entities (stub - implement later).

    Source: runtime_inspection.jsonl generator fields
    """

    power_output: float = 0
    max_power_output: float = 0
    effectivity: float = 1.0


class GeneratorMixin:
    """Mixin for generator entities (stub)."""

    is_ghost: bool

    def _get_generator_state(self, inspection_data: dict) -> GeneratorState:
        """Get generator state from inspection data."""
        if self.is_ghost:
            return GeneratorState()

        return GeneratorState(
            power_output=inspection_data.get("power_output", 0),
            max_power_output=inspection_data.get("max_power_output", 0),
            effectivity=inspection_data.get("effectivity", 1.0),
        )


class Boiler(GeneratorMixin, BurnerMixin, FluidMixin, RotatableMixin, BaseEntity):
    """Boiler - heats water into steam using fuel.

    **For Agents**: Connect to water source, add fuel, output steam.
    """

    def _get_accepted_fuel_categories(self) -> List[str]:
        """Boilers accept chemical fuel."""
        return ["chemical"]


class SteamEngine(
    GeneratorMixin, FluidMixin, ElectricMixin, RotatableMixin, BaseEntity
):
    """Steam engine - generates electricity from steam.

    **For Agents**: Connect to steam source (boiler output).
    """

    pass


class SteamTurbine(
    GeneratorMixin, FluidMixin, ElectricMixin, RotatableMixin, BaseEntity
):
    """Steam turbine - high-output steam generator.

    **For Agents**: Requires high-temperature steam from heat exchangers.
    """

    pass
