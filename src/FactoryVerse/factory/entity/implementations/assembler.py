"""Assembling machine entity implementations.

Assembling machines craft items from recipes.
"""

from FactoryVerse.factory.entity.base_entity import BaseEntity
from FactoryVerse.factory.entity.capabilities import (
    CrafterMixin,
    ElectricMixin,
    FluidMixin,
    SetRecipeMixin,
)


class ProcessingMachine(CrafterMixin, ElectricMixin, SetRecipeMixin, BaseEntity):
    """Base class for electric processing machines.

    **For Agents**: Use set_recipe() to configure, add_ingredients() to supply,
    and take_products() to collect.
    """

    pass


class AssemblingMachine(ProcessingMachine):
    """Assembling machine - crafts items from recipes."""

    pass


class ChemicalPlant(ProcessingMachine, FluidMixin):
    """Chemical plant - processes fluid recipes."""

    pass


class OilRefinery(ProcessingMachine, FluidMixin):
    """Oil refinery - processes crude oil into products."""

    pass


class Centrifuge(ProcessingMachine):
    """Centrifuge - processes uranium."""

    pass


class RocketSilo(ProcessingMachine):
    """Rocket silo - builds and launches rockets.

    **For Agents**: Inspect to see rocket_parts progress.
    """

    pass
