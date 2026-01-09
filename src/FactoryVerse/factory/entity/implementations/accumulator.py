"""Accumulator entity implementations.

Accumulators store electricity.
"""

from pydantic import BaseModel
from FactoryVerse.factory.entity.base_entity import BaseEntity


class AccumulatorState(BaseModel):
    """State for accumulator entities (stub - implement later).

    Source: runtime_inspection.jsonl accumulator fields
    """

    energy: float = 0
    capacity: float = 0

    @property
    def charge_percentage(self) -> float:
        """Get charge as percentage (0-100)."""
        if self.capacity <= 0:
            return 0.0
        return (self.energy / self.capacity) * 100


class AccumulatorMixin:
    """Mixin for accumulator entities (stub)."""

    is_ghost: bool

    def _get_accumulator_state(self, inspection_data: dict) -> AccumulatorState:
        """Get accumulator state from inspection data."""
        if self.is_ghost:
            return AccumulatorState()

        return AccumulatorState(
            energy=inspection_data.get("energy", 0),
            capacity=inspection_data.get("electric_buffer_size", 0),
        )


class Accumulator(AccumulatorMixin, BaseEntity):
    """Accumulator - stores electricity for later use.

    **For Agents**: Stores energy when production exceeds consumption.
    """

    pass
