"""Belt capability - state and mixin for transport belt entities.

Co-locates BeltState (Pydantic model) and BeltMixin.
"""

from typing import Optional
from pydantic import BaseModel


class BeltState(BaseModel):
    """State for transport belt entities.

    Source: runtime_inspection.jsonl belt-related fields
    """

    belt_shape: Optional[str] = None  # "straight", "left-turn", "right-turn"
    belt_to_ground_type: Optional[str] = None  # "input" or "output" for underground
    linked_belt_neighbour: Optional[str] = None  # Entity name for underground pair
    # Splitter-specific
    splitter_filter: Optional[str] = None
    splitter_input_priority: Optional[str] = None  # "left", "right", "none"
    splitter_output_priority: Optional[str] = None  # "left", "right", "none"


class BeltMixin:
    """Mixin for transport belt entities.

    Provides:
    - _get_belt_state() for inspection

    Used by: TransportBelt, UndergroundBelt, Splitter and their variants.

    Requires entity to have:
    - is_ghost: bool
    """

    is_ghost: bool

    def _get_belt_state(self, inspection_data: dict) -> BeltState:
        """Get belt state from inspection data.

        Args:
            inspection_data: Raw inspection data from Lua

        Returns:
            BeltState populated from inspection data
        """
        # Belt state is mostly the same for ghosts and real entities
        # (shape, type are static from placement)

        # Parse linked neighbour
        linked_neighbour = None
        linked_data = inspection_data.get("linked_belt_neighbour")
        if linked_data:
            linked_neighbour = linked_data.get("name")

        return BeltState(
            belt_shape=inspection_data.get("belt_shape"),
            belt_to_ground_type=inspection_data.get("belt_to_ground_type"),
            linked_belt_neighbour=linked_neighbour,
            splitter_filter=inspection_data.get("splitter_filter"),
            splitter_input_priority=inspection_data.get("splitter_input_priority"),
            splitter_output_priority=inspection_data.get("splitter_output_priority"),
        )
