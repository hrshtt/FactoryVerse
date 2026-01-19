"""Fluid capability - state and mixin for fluid-handling entities.

Co-locates FluidState (Pydantic model) and FluidMixin for entities
with fluidboxes like pipes, pumps, chemical plants, oil refineries.
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class FluidBox(BaseModel):
    """Contents of a single fluidbox."""

    index: int
    name: Optional[str] = None  # Fluid name, None if empty
    amount: float = 0
    temperature: float = 15  # Default temperature
    capacity: float = 0
    is_empty: bool = True


class FluidState(BaseModel):
    """State for fluid-handling entities.

    Source: runtime_inspection.jsonl fluidboxes array
    """

    fluidboxes: List[FluidBox] = Field(default_factory=list)

    @property
    def total_fluid(self) -> float:
        """Get total fluid amount across all boxes."""
        return sum(fb.amount for fb in self.fluidboxes)

    def get_fluid(self, index: int) -> Optional[FluidBox]:
        """Get fluidbox by index."""
        for fb in self.fluidboxes:
            if fb.index == index:
                return fb
        return None


class FluidMixin:
    """Mixin for entities with fluid connections.

    Provides:
    - _get_fluid_state() for inspection
    - get_fluid() helper

    Note: Pipe connection positions come from Lua via fv_placement_hints
    (engine-computed fluidbox.get_pipe_connections()), not from prototype data.

    Requires entity to have:
    - is_ghost: bool
    """

    is_ghost: bool

    def _get_fluid_state(self, inspection_data: dict) -> FluidState:
        """Get fluid state from inspection data.

        Args:
            inspection_data: Raw inspection data from Lua

        Returns:
            FluidState populated from inspection data
        """
        if self.is_ghost:
            return FluidState()  # Ghosts have no fluid data

        # Use transformer to handle Lua quirks
        from FactoryVerse.factory.entity.transform import _transform_fluid

        fluid_state = _transform_fluid(inspection_data)
        return fluid_state if fluid_state else FluidState()

    def get_fluid(self, index: int = 1) -> Optional[FluidBox]:
        """Get fluid in specific fluidbox.

        Args:
            index: Fluidbox index (1-based, like Lua)

        Returns:
            FluidBox if found, None otherwise
        """
        # This needs runtime inspection - placeholder
        return None
