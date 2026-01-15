"""EntityInspection - Master schema for all entity inspections.

This single Pydantic model is returned by ALL entity inspect() calls.
Capability-specific data is placed in namespaced optional slots.

Use model_dump_json(exclude_none=True) for concise LLM output.
"""

from typing import Optional, Dict
from pydantic import BaseModel

from FactoryVerse.factory.types import Direction, EntityStatus

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

    def __repr__(self) -> str:
        """Show inspection with status name instead of enum value."""
        # Build base representation
        parts = [
            f"name='{self.name}'",
            f"position={{'x': {self.position['x']}, 'y': {self.position['y']}}}",
        ]

        if self.direction is not None:
            # Handle both enum objects and raw int values (use_enum_values=True)
            if isinstance(self.direction, int):
                try:
                    parts.append(f"direction={Direction(self.direction).name}")
                except (ValueError, TypeError):
                    parts.append(f"direction={self.direction}")
            else:
                parts.append(f"direction={self.direction.name}")

        if self.status is not None:
            # Handle both enum objects and raw int values (use_enum_values=True)
            if isinstance(self.status, int):
                try:
                    parts.append(f"status={EntityStatus(self.status).name}")
                except (ValueError, TypeError):
                    parts.append(f"status={self.status}")
            else:
                parts.append(f"status={self.status.name}")

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
