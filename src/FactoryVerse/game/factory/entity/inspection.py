"""EntityInspection - Master schema for all entity inspections.

This single Pydantic model is returned by ALL entity inspect() calls.
Capability-specific data is placed in namespaced optional slots.

Use model_dump_json(exclude_none=True) for concise LLM output.
"""

from typing import Optional, Dict
from pydantic import BaseModel

from FactoryVerse.game.factory.types import Direction, EntityStatus

# Import all capability states
from .capabilities import (
    BurnerState,
    ElectricState,
    CrafterState,
    MinerState,
    InserterState,
    FluidState,
    BeltState,
)

# Import category-specific states
from .implementations.container import ContainerState
from .implementations.lab import LabState
from .implementations.accumulator import AccumulatorState
from .implementations.electric_pole import ElectricPoleState
from .implementations.generator import GeneratorState


class EntityInspection(BaseModel):
    """Master inspection schema - capability registry for all entities.

    This single class is returned by ALL entity inspect() calls.
    Capability-specific data is placed in namespaced optional slots.

    Example:
        inspection = drill.inspect()
        inspection.name  # "burner-mining-drill"
        inspection.burner  # BurnerState(heat=100, ...)
        inspection.miner  # MinerState(mining_progress=0.5, ...)
        inspection.electric  # None (not applicable)
    """

    # ===== Base fields (always present) =====
    name: str
    position: Dict[str, float]
    direction: Optional[Direction] = None
    status: Optional[EntityStatus] = None
    is_ghost: bool = False

    # ===== Capability slots (from mixins) =====
    burner: Optional[BurnerState] = None
    electric: Optional[ElectricState] = None
    crafter: Optional[CrafterState] = None
    miner: Optional[MinerState] = None
    inserter: Optional[InserterState] = None
    fluid: Optional[FluidState] = None
    belt: Optional[BeltState] = None

    # ===== Category-specific slots (from implementations) =====
    container: Optional[ContainerState] = None
    lab: Optional[LabState] = None
    accumulator: Optional[AccumulatorState] = None
    electric_pole: Optional[ElectricPoleState] = None
    generator: Optional[GeneratorState] = None

    class Config:
        use_enum_values = True
        extra = "forbid"  # Strict schema - no unknown fields

    def _format_status(self) -> str:
        """Format status as human-readable name."""
        if self.status is None:
            return None
        # Handle both enum objects and raw int values (use_enum_values=True)
        if isinstance(self.status, int):
            try:
                return EntityStatus(self.status).name
            except (ValueError, TypeError):
                return str(self.status)
        return self.status.name

    def _format_direction(self) -> str:
        """Format direction as human-readable name."""
        if self.direction is None:
            return None
        # Handle both enum objects and raw int values (use_enum_values=True)
        if isinstance(self.direction, int):
            try:
                return Direction(self.direction).name
            except (ValueError, TypeError):
                return str(self.direction)
        return self.direction.name

    def __str__(self) -> str:
        """Human-readable string for agents - shows enum names not values."""
        return self.__repr__()

    def __repr__(self) -> str:
        """Show inspection with status name instead of enum value."""
        # Build base representation
        parts = [
            f"name='{self.name}'",
            f"position={{'x': {self.position['x']}, 'y': {self.position['y']}}}",
        ]

        direction_str = self._format_direction()
        if direction_str:
            parts.append(f"direction={direction_str}")

        status_str = self._format_status()
        if status_str:
            parts.append(f"status={status_str}")

        if self.is_ghost:
            parts.append("is_ghost=True")

        # Add capability slots that are present
        capability_slots = [
            "burner",
            "electric",
            "crafter",
            "miner",
            "inserter",
            "fluid",
            "belt",
            "container",
            "lab",
            "accumulator",
            "electric_pole",
            "generator",
        ]
        for slot in capability_slots:
            if getattr(self, slot, None) is not None:
                parts.append(f"{slot}={getattr(self, slot)}")

        return f"EntityInspection({', '.join(parts)})"
