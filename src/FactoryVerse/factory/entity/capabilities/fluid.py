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
        # Some entities have separate input_fluid_box and output_fluid_box
        # (e.g., boilers have input for water and output for steam)
        # Note: Factorio uses both "fluidbox" and "fluid_box" (with underscore)
        # Some entities use "fluid_boxes" (plural) as an array
        fluidboxes = []
        
        # Check main fluidbox (both spellings)
        if "fluidbox" in self.prototype:
            fluidboxes.append(("fluidbox", self.prototype["fluidbox"]))
        if "fluid_box" in self.prototype:
            fluidboxes.append(("fluid_box", self.prototype["fluid_box"]))
        
        # Check fluid_boxes (plural, array format used by chemical-plant, oil-refinery, etc.)
        if "fluid_boxes" in self.prototype:
            fluid_boxes_data = self.prototype["fluid_boxes"]
            if isinstance(fluid_boxes_data, list):
                # Array of fluidboxes
                for i, fb in enumerate(fluid_boxes_data):
                    if isinstance(fb, dict):
                        fluidboxes.append((f"fluid_boxes[{i}]", fb))
            elif isinstance(fluid_boxes_data, dict):
                # Single fluidbox dict
                fluidboxes.append(("fluid_boxes", fluid_boxes_data))
        
        # Check input fluidbox (if separate)
        if "input_fluid_box" in self.prototype:
            fluidboxes.append(("input_fluid_box", self.prototype["input_fluid_box"]))
        
        # Check output fluidbox (if separate)
        if "output_fluid_box" in self.prototype:
            fluidboxes.append(("output_fluid_box", self.prototype["output_fluid_box"]))
        
        if not fluidboxes:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"Entity {self.name} has no fluidbox data. Available keys: {list(self.prototype.keys())[:30]}")
            return []
        
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Entity {self.name} has {len(fluidboxes)} fluidbox(es): {[name for name, _ in fluidboxes]}")

        positions = []
        # Use entity's direction if available, default to NORTH
        direction = getattr(self, "direction", None)
        if direction is None:
            from FactoryVerse.factory.types import Direction
            direction = Direction.NORTH

        # Process all fluidboxes
        import logging
        logger = logging.getLogger(__name__)
        
        for fluidbox_name, fluidbox in fluidboxes:
            connections = fluidbox.get("pipe_connections", [])
            logger.debug(f"  {fluidbox_name} has {len(connections)} pipe connections")
            
            for i, conn in enumerate(connections):
                # Get positions (can be multiple for rotatable entities)
                pos_list = conn.get("positions", [])
                if not pos_list:
                    # Single position
                    pos_data = conn.get("position")
                    if pos_data:
                        pos_list = [pos_data]

                logger.debug(f"    Connection {i}: {len(pos_list)} positions, keys: {list(conn.keys())}")
                for pos_data in pos_list:
                    # pos_data is [x, y] relative to entity center
                    if isinstance(pos_data, list) and len(pos_data) == 2:
                        vec = tuple(pos_data)
                        calculated_pos = apply_cardinal_vector(self.position, vec, direction)
                        positions.append(calculated_pos)
                        logger.debug(f"      Calculated position: {calculated_pos} from vec {vec}")

        logger.debug(f"Total pipe connection positions: {len(positions)}")
        return positions
