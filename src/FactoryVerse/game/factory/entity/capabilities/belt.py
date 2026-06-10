"""Belt capability - state and mixin for transport belt entities.

Co-locates BeltState (Pydantic model) and BeltMixin.
"""

from typing import Optional, List, Dict
from pydantic import BaseModel, Field


class BeltNeighbour(BaseModel):
    """A belt connected to this one. name+position so the agent can act on it
    (entities are referenced by name+position, never unit_number)."""

    name: str
    position: Optional[Dict[str, float]] = None


class BeltState(BaseModel):
    """State for transport belt entities.

    Source: runtime_inspection.jsonl belt-related fields
    """

    belt_shape: Optional[str] = None  # "straight", "left-turn", "right-turn"
    # Directional flow: inputs feed THIS belt, THIS belt feeds outputs.
    belt_inputs: List[BeltNeighbour] = Field(default_factory=list)
    belt_outputs: List[BeltNeighbour] = Field(default_factory=list)
    belt_to_ground_type: Optional[str] = None  # "input" or "output" for underground
    linked_belt_neighbour: Optional[BeltNeighbour] = None  # underground pair
    linked_belt_type: Optional[str] = None  # "input" or "output"
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

        # Use transformer to handle Lua quirks
        from FactoryVerse.game.factory.entity.transform import _transform_belt

        entity_type = inspection_data.get("entity_type", "transport-belt")
        belt_state = _transform_belt(inspection_data, entity_type)
        return belt_state if belt_state else BeltState()
