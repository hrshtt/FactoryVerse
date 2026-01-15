"""Electric capability - state and mixin for electric-powered entities.

Co-locates ElectricState (Pydantic model) and ElectricMixin for entities
that consume/store electricity.
"""

from typing import Optional, TYPE_CHECKING
from pydantic import BaseModel

if TYPE_CHECKING:
    pass


class ElectricState(BaseModel):
    """State for electric-powered entities.

    Source: runtime_inspection.jsonl energy and electric_buffer_size fields
    """

    energy: float = 0
    buffer_capacity: float = 0
    electric_network_id: Optional[int] = None

    @property
    def charge_percentage(self) -> float:
        """Get charge as percentage (0-100)."""
        if self.buffer_capacity <= 0:
            return 0.0
        return (self.energy / self.buffer_capacity) * 100


class ElectricMixin:
    """Mixin for entities that consume/store electricity.

    Provides:
    - _get_electric_state() for inspection

    Requires entity to have:
    - is_ghost: bool
    """

    is_ghost: bool

    def _get_electric_state(self, inspection_data: dict) -> ElectricState:
        """Get electric state from inspection data.

        Args:
            inspection_data: Raw inspection data from Lua

        Returns:
            ElectricState populated from inspection data
        """
        if self.is_ghost:
            return ElectricState()  # Ghosts have no electric data

        return ElectricState(
            energy=inspection_data.get("energy", 0),
            buffer_capacity=inspection_data.get("electric_buffer_size", 0),
            electric_network_id=inspection_data.get("electric_network_id"),
        )
