"""Inserter capability - state and mixin for inserter entities.

Co-locates InserterState (Pydantic model) and InserterMixin.
"""

from typing import Optional, List, Dict, Any, TYPE_CHECKING
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from FactoryVerse.agent.actions.entity_operations import EntityOperationsAction
    from FactoryVerse.factory.types import MapPosition, Direction


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
    - get_pickup_position() for geometric calculations
    - get_drop_position() for geometric calculations
    - set_filter() for filter inserters

    Requires entity to have:
    - is_ghost: bool
    - direction: Direction
    - position: Position
    - name: str
    - prototype: Dict[str, Any] (from BaseEntity)
    - _entity_ops: EntityOperationsAction
    """

    is_ghost: bool
    name: str
    position: Any  # MapPosition at runtime
    direction: "Direction"
    prototype: Any  # Dict[str, Any] at runtime
    _entity_ops: Optional["EntityOperationsAction"]

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

        # Parse held item
        held_item = None
        held_data = inspection_data.get("held_stack")
        if held_data and held_data.get("name"):
            held_item = HeldItem(
                name=held_data["name"],
                count=held_data.get("count", 1),
            )

        # Parse targets
        pickup_target = None
        if inspection_data.get("pickup_target"):
            pickup_target = inspection_data["pickup_target"].get("name")

        drop_target = None
        if inspection_data.get("drop_target"):
            drop_target = inspection_data["drop_target"].get("name")

        # Parse filters
        filters = []
        filter_data = inspection_data.get("filters", {})
        if isinstance(filter_data, dict):
            filters = list(filter_data.values())
        elif isinstance(filter_data, list):
            filters = filter_data

        return InserterState(
            held_item=held_item,
            pickup_position=pickup_pos,
            drop_position=drop_pos,
            pickup_target=pickup_target,
            drop_target=drop_target,
            filters=filters,
        )

    def get_pickup_position(self) -> "MapPosition":
        """Calculate inserter pickup position (static, geometric).

        Returns the position where the inserter picks up items from.
        This is calculated from the prototype's pickup_position,
        rotated by the entity's direction.

        Returns:
            MapPosition where items are picked up

        Example:
            >>> inserter = get_entity("inserter", pos)
            >>> pickup_pos = inserter.get_pickup_position()
        """
        from FactoryVerse.factory.prototypes import apply_cardinal_vector

        vec = tuple(self.prototype["pickup_position"])
        return apply_cardinal_vector(self.position, vec, self.direction)

    def get_drop_position(self) -> "MapPosition":
        """Calculate inserter drop position (static, geometric).

        Returns the position where the inserter drops items to.
        This is calculated from the prototype's insert_position,
        rotated by the entity's direction.

        Returns:
            MapPosition where items are dropped

        Example:
            >>> inserter = get_entity("inserter", pos)
            >>> drop_pos = inserter.get_drop_position()
        """
        from FactoryVerse.factory.prototypes import apply_cardinal_vector

        vec = tuple(self.prototype["insert_position"])
        return apply_cardinal_vector(self.position, vec, self.direction)

    def set_filter(self, slot: int, item_name: str) -> bool:
        """Set a filter slot on this inserter.

        **For Agents**: Use on filter inserters to restrict what items get moved.

        Args:
            slot: Filter slot index (1-based)
            item_name: Item name to filter for

        Returns:
            True if filter was set successfully
        """
        if self._entity_ops is None:
            raise RuntimeError("entity_ops not injected.")

        result = self._entity_ops.set_entity_filter(
            self.name,
            self.position,
            "inserter_filter",  # Inventory type for inserter filters
            filter_index=slot,
            filter_item=item_name,
        )
        return result.success
