"""Fluid capability - state and mixin for fluid-handling entities.

Co-locates FluidState (Pydantic model) and FluidMixin for entities
with fluidboxes like pipes, pumps, chemical plants, oil refineries.
"""

from typing import Optional, List, Any, TYPE_CHECKING
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from FactoryVerse.factory.types import MapPosition, Direction


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
    - get_pipe_connections() for geometric calculations

    Requires entity to have:
    - is_ghost: bool
    - position: Position
    - direction: Direction
    - prototype: Dict[str, Any] (from BaseEntity)
    """

    is_ghost: bool
    position: Any  # MapPosition at runtime
    direction: Any  # Direction at runtime
    prototype: Any  # Dict[str, Any] at runtime

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

    def get_pipe_connections(self) -> List["MapPosition"]:
        """Get pipe connection positions (static, geometric).

        Returns positions where pipes can connect to this entity's fluidboxes.
        This is calculated from the prototype's fluidbox pipe_connections,
        rotated by the entity's direction.

        Returns:
            List of MapPosition where pipes can connect

        Example:
            >>> boiler = get_entity("boiler", pos)
            >>> pipe_positions = boiler.get_pipe_connections()
        """
        from FactoryVerse.factory.prototypes import apply_cardinal_vector
        from FactoryVerse.factory.types import MapPosition

        # Extract from fluidbox data - check multiple possible locations
        fluidbox = (
            self.prototype.get("fluidbox")
            or self.prototype.get("output_fluid_box")
            or self.prototype.get("input_fluid_box")
        )
        if not fluidbox:
            return []

        connections = fluidbox.get("pipe_connections", [])
        positions = []

        for conn in connections:
            # Get positions (can be multiple for rotatable entities)
            pos_list = conn.get("positions", [])
            if not pos_list:
                # Single position
                pos_data = conn.get("position")
                if pos_data:
                    pos_list = [pos_data]

            for pos_data in pos_list:
                # pos_data is [x, y] relative to entity center
                if isinstance(pos_data, list) and len(pos_data) == 2:
                    vec = tuple(pos_data)
                    positions.append(
                        apply_cardinal_vector(self.position, vec, self.direction)
                    )

        return positions
