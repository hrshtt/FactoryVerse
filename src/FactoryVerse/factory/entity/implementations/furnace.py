"""Furnace entity implementations.

Furnaces smelt ore into plates using fuel (burner) or electricity.
"""

from typing import List
from FactoryVerse.factory.entity.base_entity import BaseEntity
from FactoryVerse.factory.entity.capabilities import (
    BurnerMixin,
    ElectricMixin,
    CrafterMixin,
)


class Furnace(CrafterMixin, BurnerMixin, BaseEntity):
    """Base furnace - smelts ore using fuel.

    **For Agents**: Use add_fuel() to power it, add_ingredients() to add ore,
    and take_products() to collect plates.
    """

    def _get_accepted_fuel_categories(self) -> List[str]:
        """Furnaces accept chemical and nuclear fuel."""
        return ["chemical", "nuclear"]


class StoneFurnace(Furnace):
    """Stone furnace - basic smelting."""

    pass


class SteelFurnace(Furnace):
    """Steel furnace - faster smelting."""

    pass


class ElectricFurnace(CrafterMixin, ElectricMixin, BaseEntity):
    """Electric furnace - uses electricity instead of fuel.

    **For Agents**: No fuel needed. Just add_ingredients() and take_products().
    """

    pass
