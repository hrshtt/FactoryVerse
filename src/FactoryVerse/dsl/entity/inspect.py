"""Shared inspection types and base classes.

This module defines the base inspection data structure and shared types
used across all entity inspection dataclasses.
"""

from dataclasses import dataclass
from typing import Optional
from FactoryVerse.dsl.types import MapPosition


@dataclass
class EntityRef:
    """Reference to another entity.

    **For Agents**: Identifies an entity by name and position.
    """

    name: str
    position: MapPosition

    def __str__(self) -> str:
        return f"{self.name} @ ({self.position.x:.1f}, {self.position.y:.1f})"


@dataclass
class BurnerData:
    """Burner component state.

    **For Agents**: Check burner status, fuel levels, and heat.
    """

    heat: Optional[float] = None
    heat_capacity: Optional[float] = None
    remaining_burning_fuel: Optional[float] = None
    currently_burning: Optional[str] = None

    @property
    def is_burning(self) -> bool:
        """Check if burner is actively burning fuel."""
        return self.currently_burning is not None

    @property
    def heat_percentage(self) -> Optional[float]:
        """Heat as percentage (0-100)."""
        if self.heat is None or self.heat_capacity is None:
            return None
        if self.heat_capacity == 0:
            return 0.0
        return (self.heat / self.heat_capacity) * 100

    def __str__(self) -> str:
        lines = []
        if self.currently_burning:
            lines.append(f"Burning: {self.currently_burning}")
            if self.remaining_burning_fuel:
                lines.append(f"  Remaining: {self.remaining_burning_fuel:.0f} J")
        else:
            lines.append("Burning: (none)")

        if self.heat is not None and self.heat_capacity:
            pct = self.heat_percentage or 0
            lines.append(
                f"  Heat: {self.heat:.0f}/{self.heat_capacity:.0f} ({pct:.1f}%)"
            )

        return "\n".join(lines)


@dataclass
class EnergyData:
    """Electric energy state.

    **For Agents**: Check energy buffer levels.
    """

    current: float
    capacity: float

    @property
    def percentage(self) -> float:
        """Energy as percentage (0-100)."""
        if self.capacity == 0:
            return 0.0
        return (self.current / self.capacity) * 100

    @property
    def is_full(self) -> bool:
        """Check if energy buffer is full."""
        return self.current >= self.capacity

    @property
    def is_empty(self) -> bool:
        """Check if energy buffer is empty."""
        return self.current <= 0

    def __str__(self) -> str:
        return f"{self.current:.0f}/{self.capacity:.0f} ({self.percentage:.1f}%)"


@dataclass
class BoundingBoxData:
    """Bounding box structure.

    **For Agents**: Defines a rectangular area.
    """

    left_top: MapPosition
    right_bottom: MapPosition

    def __str__(self) -> str:
        return f"[({self.left_top.x:.1f}, {self.left_top.y:.1f}) to ({self.right_bottom.x:.1f}, {self.right_bottom.y:.1f})]"


@dataclass
class FluidBoxData:
    """Fluid box contents.

    **For Agents**: Check fluid type, amount, and temperature.
    """

    name: str
    amount: float
    temperature: float

    def __str__(self) -> str:
        return f"{self.name}: {self.amount:.1f} @ {self.temperature:.1f}°"


@dataclass
class BaseInspectionData:
    """Base inspection data present on all entities.

    **For Agents**: Every entity inspection includes these base fields.
    """

    entity_name: str
    entity_type: str
    position: MapPosition
    direction: int
    tick: int
    health: Optional[float] = None
    max_health: Optional[float] = None
    status: Optional[str] = None

    @property
    def health_percentage(self) -> Optional[float]:
        """Health as percentage (0-100)."""
        if self.health is None or self.max_health is None:
            return None
        if self.max_health == 0:
            return 0.0
        return (self.health / self.max_health) * 100

    @property
    def is_damaged(self) -> bool:
        """Check if entity is damaged."""
        if self.health is None or self.max_health is None:
            return False
        return self.health < self.max_health

    def __str__(self) -> str:
        """Default formatting for base inspection."""
        lines = [
            f"{self.entity_type}({self.entity_name}) at ({self.position.x:.1f}, {self.position.y:.1f})"
        ]
        if self.status:
            lines.append(f"  Status: {self.status}")
        if self.health is not None:
            health_pct = self.health_percentage or 0
            lines.append(
                f"  Health: {self.health:.0f}/{self.max_health:.0f} ({health_pct:.1f}%)"
            )
        return "\n".join(lines)
