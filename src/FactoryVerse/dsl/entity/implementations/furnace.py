"""Furnace entity implementations.

Furnaces smelt ore into plates using fuel.
Includes: StoneFurnace, SteelFurnace, ElectricFurnace
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from FactoryVerse.dsl.types import MapPosition, Direction
from FactoryVerse.dsl.mixins import CrafterMixin, FuelableMixin
from FactoryVerse.dsl.entity.base_entity import BaseEntity
from FactoryVerse.dsl.entity.inspect import BaseInspectionData, BurnerData, EnergyData


@dataclass
class FurnaceInspection(BaseInspectionData):
    """Furnace inspection data.

    **For Agents**: Use this to check furnace state, recipe, progress, and inventories.
    Access properties directly or print for formatted output.
    """

    recipe: Optional[str] = None
    crafting_progress: Optional[float] = None
    bonus_progress: Optional[float] = None
    is_crafting: Optional[bool] = None
    input: Optional[Dict[str, int]] = None
    output: Optional[Dict[str, int]] = None
    fuel: Optional[Dict[str, int]] = None
    energy: Optional[EnergyData] = None
    beacons_count: Optional[int] = None
    burner: Optional[BurnerData] = None
    previous_recipe: Optional[str] = None

    # Helper properties for LLM decision-making
    @property
    def needs_fuel(self) -> bool:
        """Check if furnace needs fuel.

        **For Agents**: Use this to determine if you should add fuel.
        """
        if self.burner is None:
            return False
        return (
            not self.burner.is_burning
            and (self.burner.remaining_burning_fuel or 0) == 0
        )

    @property
    def has_input(self) -> bool:
        """Check if furnace has input materials."""
        return self.input is not None and len(self.input) > 0

    @property
    def has_output(self) -> bool:
        """Check if furnace has output products.

        **For Agents**: Use this to determine if you should take products.
        """
        return self.output is not None and len(self.output) > 0

    @property
    def is_idle(self) -> bool:
        """Check if furnace is idle (no recipe or not crafting).

        **For Agents**: Idle furnaces can be given new recipes.
        """
        return self.recipe is None or (self.is_crafting is False)

    def __str__(self) -> str:
        """Format furnace inspection for human readability."""
        lines = [
            f"Furnace({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]

        # Status
        lines.append(f"  Status: {self.status or 'unknown'}")

        # Recipe and progress
        if self.recipe:
            lines.append(f"  Recipe: {self.recipe}")
            if self.crafting_progress is not None:
                lines.append(f"  Progress: {self.crafting_progress * 100:.1f}%")
        else:
            lines.append("  Recipe: (none)")

        # Burner info
        if self.burner:
            burner_lines = str(self.burner).split("\n")
            for line in burner_lines:
                lines.append(f"  {line}")

        # Inventories
        if self.fuel:
            fuel_str = ", ".join(
                [f"{name}: {count}" for name, count in self.fuel.items()]
            )
            lines.append(f"  Fuel: {fuel_str}")
        else:
            lines.append("  Fuel: (empty)")

        if self.input:
            input_str = ", ".join(
                [f"{name}: {count}" for name, count in self.input.items()]
            )
            lines.append(f"  Input: {input_str}")
        else:
            lines.append("  Input: (empty)")

        if self.output:
            output_str = ", ".join(
                [f"{name}: {count}" for name, count in self.output.items()]
            )
            lines.append(f"  Output: {output_str}")
        else:
            lines.append("  Output: (empty)")

        return "\n".join(lines)


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

        Args:
            data: Raw inspection data from the game

        Returns:
            Formatted string for agent consumption
        """

        # Extract burner data if present
        burner_data = None
        if data.get("burner"):
            burner_info = data["burner"]
            burner_data = BurnerData(
                heat=burner_info.get("heat"),
                heat_capacity=burner_info.get("heat_capacity"),
                remaining_burning_fuel=burner_info.get("remaining_burning_fuel"),
                currently_burning=burner_info.get("currently_burning"),
            )

        # Extract energy data if present
        energy_data = None
        if data.get("energy"):
            energy_info = data["energy"]
            energy_data = EnergyData(
                current=energy_info.get("current", 0),
                capacity=energy_info.get("capacity", 0),
            )

        # Get inventories
        inventories = data.get("inventories", {})

        inspection = FurnaceInspection(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=MapPosition.from_dict(data["position"]),
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
            recipe=data.get("recipe"),
            crafting_progress=data.get("crafting_progress"),
            bonus_progress=data.get("productivity_bonus"),
            is_crafting=data.get("is_crafting"),
            input=inventories.get("input"),
            output=inventories.get("output"),
            fuel=inventories.get("fuel"),
            energy=energy_data,
            beacons_count=data.get("beacons_count"),
            burner=burner_data,
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
