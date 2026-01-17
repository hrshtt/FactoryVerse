"""Miner capability - state and mixin for mining drills.

Co-locates MinerState (Pydantic model) and MinerMixin for mining drills.
"""

from typing import Optional, Dict, List, Union, Any, TYPE_CHECKING
from pydantic import BaseModel

if TYPE_CHECKING:
    from FactoryVerse.factory.types import MapPosition, Direction, BoundingBox


class MiningTarget(BaseModel):
    """Information about the resource being mined."""

    name: str
    amount: int
    position: Optional[Dict[str, float]] = None


class MinerState(BaseModel):
    """State for mining drills.

    Source: runtime_inspection.jsonl mining_progress, mining_target, drop_position
    """

    mining_progress: float = 0
    mining_target: Optional[MiningTarget] = None
    drop_position: Optional[Dict[str, float]] = None
    drop_target: Optional[str] = None  # Entity name at drop position


class MinerMixin:
    """Mixin for mining drills (ore extraction).

    Provides:
    - _get_miner_state() for inspection
    - get_output_position() for geometric calculations
    - get_resource_search_area() for geometric calculations

    Requires entity to have:
    - is_ghost: bool
    - direction: Direction
    - position: Position
    - name: str
    - prototype: Dict[str, Any] (from BaseEntity)
    """

    is_ghost: bool
    name: str
    position: Any  # MapPosition at runtime
    direction: "Direction"
    prototype: Any  # Dict[str, Any] at runtime

    def _get_miner_state(self, inspection_data: dict) -> MinerState:
        """Get miner state from inspection data.

        Args:
            inspection_data: Raw inspection data from Lua

        Returns:
            MinerState populated from inspection data
        """
        # Drop position is available even for ghosts (from direction)
        drop_pos = inspection_data.get("drop_position")

        if self.is_ghost:
            return MinerState(drop_position=drop_pos)

        # Use transformer to handle Lua quirks
        from FactoryVerse.factory.entity.transform import _transform_miner

        # Get entity type from inspection data or prototype
        entity_type = inspection_data.get("entity_type", "mining-drill")
        miner_state = _transform_miner(inspection_data, entity_type)
        return miner_state if miner_state else MinerState(drop_position=drop_pos)

    def get_output_position(self) -> "MapPosition":
        """Calculate drill output position (static, geometric).

        Returns the position where the mining drill drops extracted items.
        This is calculated from the prototype's vector_to_place_result,
        rotated by the entity's direction.

        Returns:
            MapPosition where items are dropped

        Example:
            >>> drill = get_entity("electric-mining-drill", pos)
            >>> output_pos = drill.get_output_position()
        """
        from FactoryVerse.factory.prototypes import (
            apply_cardinal_vector,
            snap_to_tile_center,
        )

        vec = tuple(self.prototype["vector_to_place_result"])
        raw_pos = apply_cardinal_vector(self.position, vec, self.direction)
        return snap_to_tile_center(raw_pos)

    def get_resource_search_area(self) -> "BoundingBox":
        """Calculate mining area (static, geometric).

        Returns a bounding box representing the area where the mining drill
        searches for resources to extract.

        Returns:
            BoundingBox covering the resource search area

        Example:
            >>> drill = get_entity("electric-mining-drill", pos)
            >>> search_area = drill.get_resource_search_area()
        """
        from FactoryVerse.factory.types import BoundingBox

        radius = self.prototype["resource_searching_radius"]
        x, y = self.position.x, self.position.y
        return BoundingBox.from_tuple(
            ((x - radius, y - radius), (x + radius, y + radius))
        )
