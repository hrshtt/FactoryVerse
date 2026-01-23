"""Inserter capability - state and mixin for inserter entities.

Co-locates InserterState (Pydantic model) and InserterMixin.
"""

from typing import Optional, List, Dict, Any, TYPE_CHECKING
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from FactoryVerse.game.agent.embodied_actions.entity_operations import (
        EntityOperationsAction,
    )


class HeldItem(BaseModel):
    """Item held by an inserter."""

    name: str
    count: int


class InserterState(BaseModel):
    """State for inserter entities.

    Source: runtime_inspection.jsonl inserter fields
    """

    held_item: Optional[HeldItem] = None
    pickup_position: Optional[Dict[str, float]] = None
    drop_position: Optional[Dict[str, float]] = None
    pickup_target: Optional[str] = None  # Entity name
    drop_target: Optional[str] = None  # Entity name
    filters: List[str] = Field(default_factory=list)


class InserterMixin:
    """Mixin for inserter entities.

    Provides:
    - _get_inserter_state() for inspection
    - set_filter() for filter inserters

    Note: Pickup/drop positions come from Lua inspection data (engine-computed),
    not calculated from prototypes. Use fv_placement_hints for placement queries.

    Requires entity to have:
    - is_ghost: bool
    - direction: Direction
    - position: Position
    - name: str
    - _entity_ops: EntityOperationsAction
    """

    is_ghost: bool
    name: str
    position: Any  # MapPosition at runtime
    _entity_ops: "EntityOperationsAction"

    def _get_inserter_state(self, inspection_data: dict) -> InserterState:
        """Get inserter state from inspection data.

        Args:
            inspection_data: Raw inspection data from Lua

        Returns:
            InserterState populated from inspection data
        """
        # Position data is available even for ghosts
        pickup_pos = inspection_data.get("pickup_position")
        drop_pos = inspection_data.get("drop_position")

        if self.is_ghost:
            return InserterState(
                pickup_position=pickup_pos,
                drop_position=drop_pos,
            )

        # Use transformer to handle Lua quirks
        from FactoryVerse.game.factory.entity.transform import _transform_inserter

        entity_type = inspection_data.get("entity_type", "inserter")
        inserter_state = _transform_inserter(inspection_data, entity_type)

        # Fallback to minimal state if transformer returns None
        if not inserter_state:
            pickup_pos = inspection_data.get("pickup_position")
            drop_pos = inspection_data.get("drop_position")
            return InserterState(pickup_position=pickup_pos, drop_position=drop_pos)

        return inserter_state

    def set_filter(self, slot: int, item_name: str) -> bool:
        """Set a filter slot on this inserter.

        **For Agents**: Use on filter inserters to restrict what items get moved.

        Args:
            slot: Filter slot index (1-based)
            item_name: Item name to filter for

        Returns:
            True if filter was set successfully
        """
        result = self._entity_ops.set_entity_filter(
            self.name,
            self.position,
            "inserter_filter",  # Inventory type for inserter filters
            filter_index=slot,
            filter_item=item_name,
        )
        return result.success
