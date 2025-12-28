"""Ghost tracking data types.

TrackedGhost is a lightweight Python-only data class for tracking planned
ghost placements. This is different from Ghost[BaseEntity] views which
wrap actual in-game ghost entities.
"""

from dataclasses import dataclass
from typing import Optional

from FactoryVerse.dsl.types import MapPosition


@dataclass
class TrackedGhost:
    """A tracked ghost placement (Python-only, not in-game yet).

    Used by GhostManager to track planned entity placements.
    This is a lightweight tracking object, not a full entity.

    Attributes:
        name: Entity prototype name (e.g., "stone-furnace")
        position: Where the ghost should be placed
        label: Optional grouping label for the ghost
        placed_tick: Game tick when tracking was added
    """

    name: str
    position: MapPosition
    label: Optional[str] = None
    placed_tick: int = 0
