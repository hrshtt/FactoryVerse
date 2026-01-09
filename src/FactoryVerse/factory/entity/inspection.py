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
