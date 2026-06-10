"""Capabilities package - cross-cutting mixins and their states.

Each capability module co-locates:
- State model (Pydantic BaseModel)
- Mixin class with _get_*_state() method

This enables entities to compose capabilities via multiple inheritance:
    class StoneFurnace(BaseEntity, BurnerMixin, CrafterMixin):
        pass
"""

# State models
from .burner import BurnerState
from .electric import ElectricState
from .crafter import CrafterState
from .miner import MinerState, MiningTarget
from .inserter import InserterState, HeldItem
from .fluid import FluidState, FluidBox
from .belt import BeltState, BeltNeighbour

# Mixins
from .burner import BurnerMixin
from .electric import ElectricMixin
from .crafter import CrafterMixin, SetRecipeMixin
from .miner import MinerMixin
from .inserter import InserterMixin
from .fluid import FluidMixin
from .belt import BeltMixin
from .rotatable import RotatableMixin, Rotatable180Mixin

__all__ = [
    # States
    "BurnerState",
    "ElectricState",
    "CrafterState",
    "MinerState",
    "MiningTarget",
    "InserterState",
    "HeldItem",
    "FluidState",
    "FluidBox",
    "BeltState",
    "BeltNeighbour",
    # Mixins
    "BurnerMixin",
    "ElectricMixin",
    "CrafterMixin",
    "SetRecipeMixin",
    "MinerMixin",
    "InserterMixin",
    "FluidMixin",
    "BeltMixin",
    "RotatableMixin",
    "Rotatable180Mixin",
]
