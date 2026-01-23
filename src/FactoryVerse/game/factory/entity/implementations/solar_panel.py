"""Solar panel entity implementation.

Solar panels generate electricity from sunlight.
"""

from FactoryVerse.game.factory.entity.base_entity import BaseEntity
from FactoryVerse.game.factory.entity.capabilities import ElectricMixin
from .generator import GeneratorMixin


class SolarPanel(GeneratorMixin, ElectricMixin, BaseEntity):
    """Solar panel - generates electricity from sunlight.

    **For Agents**: Produces 60kW during full daylight (noon),
    less during dawn/dusk, nothing at night. Pair with accumulators
    to store excess energy for nighttime use. No direction required.
    """

    pass
