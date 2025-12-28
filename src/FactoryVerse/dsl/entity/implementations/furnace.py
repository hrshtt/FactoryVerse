"""Furnace entity implementations.

Furnaces smelt ore into plates using fuel.
Includes: StoneFurnace, SteelFurnace, ElectricFurnace
"""

from typing import Dict, List, Optional
from FactoryVerse.dsl.types import MapPosition, Direction
from FactoryVerse.dsl.mixins import CrafterMixin, FuelableMixin
from FactoryVerse.dsl.entity.base_entity import BaseEntity
from FactoryVerse.dsl.entity.inspect import (
    FurnaceInspection,
    BurnerData,
    EnergyData,
)


def _parse_burner(data: Optional[Dict]) -> Optional[BurnerData]:
    """Parse burner data from Lua response."""
    if data is None:
        return None
    return BurnerData(
        heat=data.get("heat"),
        heat_capacity=data.get("heat_capacity"),
        remaining_burning_fuel=data.get("remaining_burning_fuel"),
        currently_burning=data.get("currently_burning"),
    )


def _parse_energy(data: Optional[Dict]) -> Optional[EnergyData]:
    """Parse energy data from Lua response."""
    if data is None:
        return None
    return EnergyData(
        current=data.get("current", 0),
        capacity=data.get("capacity", 0),
    )


class Furnace(CrafterMixin, FuelableMixin, BaseEntity):
    """A furnace entity.

    **For Agents**: Furnaces smelt ore into plates. They accept any fuel type (chemical or nuclear).
    Use add_fuel() and add_ingredients() to operate them.
    """

    def _get_accepted_fuel_categories(self) -> List[str]:
        """Furnaces accept all fuel types."""
        return ["chemical", "nuclear"]

    def _format_inspection(self, data: Dict) -> str:
        """Format furnace inspection data.

        Parses raw Lua data into FurnaceInspection dataclass and returns formatted string.

        Args:
            data: Raw inspection data from Lua (matches inspect_crafting_machine output)

        Returns:
            Formatted string for agent consumption
        """
        # Parse position
        pos_data = data.get("position", {})
        position = MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0))

        # Build FurnaceInspection from Lua data
        # NOTE: Lua sends data.input, data.output, data.fuel DIRECTLY (not nested in inventories)
        inspection = FurnaceInspection(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=position,
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
            recipe=data.get("recipe"),
            crafting_progress=data.get("crafting_progress"),
            bonus_progress=data.get("bonus_progress"),
            is_crafting=data.get("is_crafting"),
            input=data.get("input"),  # Direct from Lua, not nested
            output=data.get("output"),  # Direct from Lua, not nested
            fuel=data.get("fuel"),  # Direct from Lua, not nested
            energy=_parse_energy(data.get("energy")),
            beacons_count=data.get("beacons_count"),
            burner=_parse_burner(data.get("burner")),
            previous_recipe=data.get("previous_recipe"),
        )
        return str(inspection)


class StoneFurnace(Furnace):
    """Stone furnace - basic smelting."""

    pass


class SteelFurnace(Furnace):
    """Steel furnace - faster smelting."""

    pass


class ElectricFurnace(Furnace):
    """Electric furnace - no fuel needed, uses electricity."""

    def _get_accepted_fuel_categories(self) -> List[str]:
        """Electric furnaces don't use fuel."""
        return []
