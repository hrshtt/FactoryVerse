"""Lab entity implementations.

Labs research technologies.
"""

from typing import Dict

from pydantic import BaseModel, Field
from FactoryVerse.game.factory.entity.base_entity import BaseEntity
from FactoryVerse.game.factory.entity.capabilities import ElectricMixin


class LabState(BaseModel):
    """State for lab entities (stub - implement later).

    Source: runtime_inspection.jsonl lab fields
    """

    research_progress: float = 0
    researching_speed: float = 1.0
    science_packs: Dict[str, int] = Field(default_factory=dict)


class LabMixin:
    """Mixin for lab entities (stub)."""

    is_ghost: bool

    def _get_lab_state(self, inspection_data: dict) -> LabState:
        """Get lab state from inspection data."""
        if self.is_ghost:
            return LabState()

        # TODO: Implement proper parsing when needed
        return LabState(
            research_progress=inspection_data.get("research_progress", 0),
            researching_speed=inspection_data.get("researching_speed", 1.0),
        )


class Lab(LabMixin, ElectricMixin, BaseEntity):
    """Lab - researches technologies.

    **For Agents**: Insert science packs to enable research.
    """

    pass
