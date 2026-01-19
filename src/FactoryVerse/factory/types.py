"""Factory Types - Core type definitions for FactoryVerse.

This module provides structural types (Position, BoundingBox) and re-exports
authoritative Factorio types from factorio_types.py.

Type System Overview:
- Direction, EntityStatus: Enums from factorio_types.py (source of truth)
- MapPosition, TilePosition, BoundingBox: Structural position types
- EntityID, ItemID, RecipeID, etc.: Semantic type aliases for prototype names
- TypedDicts: Response/payload types for RCON and async actions

See factorio_types.py for the authoritative Factorio type definitions.
"""

from dataclasses import dataclass
import math
from typing import (
    Self,
    Tuple,
    Any,
    List,
    Dict,
    Optional,
    TypedDict,
)

# =============================================================================
# AUTHORITATIVE FACTORIO TYPES (re-exported from factorio_types.py)
# =============================================================================
# These are the source of truth for Factorio game types.
# Direction and EntityStatus enums have values matching Factorio's defines.

from FactoryVerse.factory.factorio_types import (
    # Enums
    Direction,
    EntityStatus,
    # Type aliases
    MapTick,
    TilePosition,
    EntityID,
    ItemID,
    RecipeID,
    FluidID,
    TechnologyID,
    TileID,
    ResourceCategoryID,
    RecipeCategoryID,
    FuelCategoryID,
    ItemGroupID,
    ItemSubGroupID,
    ModuleCategoryID,
    # Getters for Literal values
    get_entity_ids,
    get_item_ids,
    get_recipe_ids,
    get_resource_entity_ids,
    get_resource_tile_ids,
    # Validators
    is_valid_entity_id,
    is_valid_item_id,
    is_valid_recipe_id,
)


@dataclass
class Position:
    """Coordinates of a tile in a map.

    Positive x goes towards east, positive y goes towards south.
    Can be used as a struct {x, y} or as a tuple (x, y).
    """

    x: float
    y: float

    @classmethod
    def from_tuple(cls, coords):
        """Create MapPosition from (x, y) or ((x, y))."""
        if isinstance(coords, tuple):
            return cls(x=coords[0], y=coords[1])
        elif isinstance(coords, list):
            return cls(x=coords[0][0], y=coords[0][1])
        else:
            raise ValueError("MapPosition expects (x, y) or ((x, y))")

    @classmethod
    def from_dict(cls, pos: Dict[str, float]) -> Self:
        return cls(x=pos["x"], y=pos["y"])

    def offset(self, offset: Tuple[int, int], direction: Direction) -> Self:
        """Offset the position by the offset vector, rotated according to the provided cardinal direction.

        In Factorio, entity offsets (like {x, y} vectors) are specified for the 'north' orientation.
        For other cardinal directions, rotate the offset accordingly:

            - NORTH: (x_off, y_off)
            - EAST:  (y_off, -x_off)
            - SOUTH: (-x_off, -y_off)
            - WEST:  (-y_off, x_off)

        Args:
            offset: A tuple (x, y) given for the north-facing entity.
            direction: The Direction (must be cardinal).

        Returns:
            A new instance of the same type (Position, MapPosition, etc.), offset and rotated in the chosen direction.
        """
        if not direction.is_cardinal():
            raise ValueError(f"Cannot offset non-cardinal direction: {direction.name}")

        x_off, y_off = offset

        if not isinstance(x_off, int) or not isinstance(y_off, int):
            raise ValueError("Offset must be an integer tuple")

        if direction == Direction.NORTH:
            dx, dy = x_off, y_off
        elif direction == Direction.EAST:
            dx, dy = y_off, -x_off
        elif direction == Direction.SOUTH:
            dx, dy = -x_off, -y_off
        elif direction == Direction.WEST:
            dx, dy = -y_off, x_off
        else:
            raise ValueError(f"Cannot offset non-cardinal direction: {direction.name}")

        return type(self)(x=self.x + dx, y=self.y + dy)


class AnchorVector(Position): ...


class MapPosition(Position):
    """Coordinates of a tile in a map.

    Pure position data - just x, y coordinates.
    Can be used as a set key or dictionary key via tuple (x, y).
    """

    def __hash__(self) -> int:
        """Make MapPosition hashable using tuple (x, y)."""
        return hash((self.x, self.y))

    def __eq__(self, other) -> bool:
        """Compare MapPosition instances by their (x, y) coordinates."""
        if not isinstance(other, MapPosition):
            return False
        return (self.x, self.y) == (other.x, other.y)

    def distance(self, other: "MapPosition") -> float:
        """Calculate Euclidean distance to another MapPosition.

        Args:
            other: Another MapPosition to calculate distance to.

        Returns:
            The Euclidean distance between this position and other.
        """
        dx = self.x - other.x
        dy = self.y - other.y
        return math.sqrt(dx * dx + dy * dy)

    def manhattan_distance(self, other: "MapPosition") -> float:
        """Calculate Manhattan distance to another MapPosition.

        Args:
            other: Another MapPosition to calculate distance to.

        Returns:
            The Manhattan distance (sum of absolute differences) between this position and other.
        """
        return abs(self.x - other.x) + abs(self.y - other.y)


class RealOrientation(float):
    """The smooth orientation in range [0, 1), covering a full circle clockwise from north.

    0 = north, 0.5 = south, 0.625 = south-west, 0.875 = north-west, etc.
    """

    def __new__(cls, value):
        if not (0 <= value < 1):
            raise ValueError("RealOrientation must be in [0,1)")
        return float.__new__(cls, value)


@dataclass
class BoundingBox:
    """BoundingBox, typically centered on an entity position.

    Can be specified with left_top and right_bottom (as MapPosition), and optional orientation (RealOrientation).
    Positive x is east, positive y is south.
    The upper-left is the least in x and y, lower-right is the greatest.
    """

    left_top: Position
    right_bottom: Position
    orientation: Optional[RealOrientation] = None

    @classmethod
    def from_tuple(cls, coords):
        """Create BoundingBox from ((x1, y1), (x2, y2)) or ((x1, y1), (x2, y2), orientation)."""
        if len(coords) == 2:
            lt = Position(x=coords[0][0], y=coords[0][1])
            rb = Position(x=coords[1][0], y=coords[1][1])
            return cls(left_top=lt, right_bottom=rb)
        elif len(coords) == 3:
            lt = Position(x=coords[0][0], y=coords[0][1])
            rb = Position(x=coords[1][0], y=coords[1][1])
            orientation = RealOrientation(coords[2])
            return cls(left_top=lt, right_bottom=rb, orientation=orientation)  # type: ignore
        else:
            raise ValueError(
                "BoundingBox expects (left_top, right_bottom) or (left_top, right_bottom, orientation)"
            )


# =============================================================================
# ASYNC ACTION RESPONSES
# =============================================================================
# These TypedDicts match the return schemas from RemoteInterface.lua INTERFACE_METHODS
# Each async action returns immediately with queued status; completion comes via UDP.


class WalkAsyncResponse(TypedDict, total=False):
    """Response from walk_to async action.

    RCON Contract: RemoteInterface.lua walk_to.returns.schema
    """

    queued: bool
    action_id: str


class MineAsyncResponse(TypedDict, total=False):
    """Response from mine_resource async action.

    RCON Contract: RemoteInterface.lua mine_resource.returns.schema
    """

    queued: bool
    action_id: str
    entity_name: str
    entity_position: Dict[str, float]


class CraftAsyncResponse(TypedDict, total=False):
    """Response from craft_enqueue async action.

    RCON Contract: RemoteInterface.lua craft_enqueue.returns.schema
    """

    queued: bool
    action_id: str
    recipe: str
    count: int


# =============================================================================
# ASYNC COMPLETION PAYLOADS (received via UDP)
# =============================================================================


class WalkCompletionPayload(TypedDict, total=False):
    """Completion payload for walk_to action (received via UDP).

    RCON Contract: RemoteInterface.lua walk_to.returns.completion
    """

    success: bool
    position: Dict[str, float]
    elapsed_ticks: int
    action_id: str
    agent_id: int


class MineCompletionPayload(TypedDict, total=False):
    """Completion payload for mine_resource action (received via UDP).

    RCON Contract: RemoteInterface.lua mine_resource.returns.completion
    """

    success: bool
    items: Dict[str, int]  # {item_name: count, ...}
    reason: str  # "completed", "interrupted", etc.
    action_id: str
    agent_id: int


class CraftCompletionPayload(TypedDict, total=False):
    """Completion payload for craft_enqueue action (received via UDP).

    RCON Contract: RemoteInterface.lua craft_enqueue.returns.completion
    """

    success: bool
    items: Dict[str, int]  # {item_name: count, ...}
    action_id: str
    agent_id: int


# =============================================================================
# CRAFTING & RESEARCH STATUS
# =============================================================================


class CraftingQueueItem(TypedDict):
    """Single item in crafting queue.
    
    RCON Contract: RemoteInterface.lua get_crafting_queue.returns.schema.queue.item_schema
    """

    index: int  # 1-based position in queue
    recipe: str
    count: int
    prerequisite: bool


class CraftingQueueStatus(TypedDict):
    """Current crafting queue status.
    
    RCON Contract: RemoteInterface.lua get_crafting_queue.returns.schema
    """

    queue: List[CraftingQueueItem]
    queue_size: int
    progress: float  # 0.0 to 1.0


class CraftingStatus(TypedDict):
    """Current crafting status for an agent.
    
    DEPRECATED: Use CraftingQueueStatus instead for full queue details.
    This is kept for backward compatibility.
    """

    active: bool
    recipe: Optional[str]
    progress: float
    queued_count: int


class ResearchQueueItem(TypedDict):
    """An item in the research queue."""

    technology: str
    progress: float
    level: int


class ResearchStatus(TypedDict):
    """Current research status for the force."""

    queue: List[ResearchQueueItem]
    queue_length: int
    current_research: Optional[str]
    tick: int


# =============================================================================
# ACTION RESULTS (sync operations)
# =============================================================================


class ActionResult(TypedDict, total=False):
    """Consolidated result for sync actions that return validation data and metadata.

    Used for actions where the primary goal is confirmation of success/failure
    and basic feedback, rather than returning an interactable domain object.

    RCON Contract: Covers multiple RemoteInterface.lua methods including:
    - set_entity_filter, set_inventory_limit, put_inventory_item
    - place_entity, remove_ghost, teleport
    - enqueue_research, cancel_current_research, craft_dequeue
    """

    success: bool
    item_name: str
    count: int
    count_put: int
    count_taken: int
    cancelled_count: int
    items: Dict[str, int]
    recipe: str
    technology: str
    position: Dict[str, float]
    entity_name: str
    entity_type: str
    reason: str
    message: str
    actual_products: Dict[str, int]


# =============================================================================
# AGENT INSPECTION
# =============================================================================


class AgentActivityState(TypedDict, total=False):
    """Agent activity state (walking, mining, crafting).

    RCON Contract: RemoteInterface.lua inspect.returns.schema.state
    """

    walking: Dict[str, Any]
    mining: Dict[str, Any]
    crafting: Dict[str, Any]


class AgentInspectionData(TypedDict, total=False):
    """Response from inspect() query.

    RCON Contract: RemoteInterface.lua inspect.returns.schema
    """

    agent_id: int
    tick: int
    position: Dict[str, float]
    state: AgentActivityState  # Only present if attach_state=True


class ResourcePatchData(TypedDict):
    """Structured data for a resource patch inspection."""

    name: str
    type: str
    total_amount: int
    tile_count: int
    position: Dict[str, float]
    tiles: List[Dict[str, Any]]


class ProductData(TypedDict, total=False):
    """Structured data for a mineable product."""

    name: str
    type: str
    amount: int
    amount_min: int
    amount_max: int
    probability: float


class EntityEnergyData(TypedDict, total=False):
    """Energy state for an entity.

    RCON Contract: RemoteInterface.lua inspect_entity.returns.schema.energy
    """

    current: float
    capacity: float


class EntityInventoriesData(TypedDict, total=False):
    """Inventory contents by slot type.

    RCON Contract: RemoteInterface.lua inspect_entity.returns.schema.inventories
    Each slot is a dict of {item_name: count, ...}
    """

    fuel: Dict[str, int]
    input: Dict[str, int]
    output: Dict[str, int]
    chest: Dict[str, int]
    burnt_result: Dict[str, int]


class HeldItemData(TypedDict, total=False):
    """Item held by an inserter.

    RCON Contract: RemoteInterface.lua inspect_entity.returns.schema.held_item
    """

    name: str
    count: int


class EntityInspectionData(TypedDict, total=False):
    """Comprehensive volatile state for a specific entity.

    RCON Contract: RemoteInterface.lua inspect_entity.returns.schema

    This TypedDict covers ALL fields that can be returned from inspect_entity().
    Not all fields are present for all entity types:
    - crafting_progress: Only for assemblers/furnaces with active recipe
    - burning_progress: Only for burner entities (furnaces, burner drills)
    - held_item: Only for inserters
    - inventories: Structure varies by entity type
    """

    # Core identification
    entity_name: str
    entity_type: str
    position: Dict[str, float]
    tick: int  # Game tick when inspection was taken

    # State
    status: str  # "working", "no-power", "waiting-for-space", etc.
    direction: int
    health: float

    # Recipe/Crafting (assemblers, furnaces, chemical plants)
    recipe: Optional[str]
    crafting_progress: float  # 0.0-1.0
    burning_progress: float  # 0.0-1.0 (furnaces)
    productivity_bonus: float

    # Energy (electric entities)
    energy: EntityEnergyData

    # Inventories by slot type
    inventories: EntityInventoriesData

    # Inserter-specific
    held_item: HeldItemData

    # Legacy/compatibility fields (may be used by older code)
    inventory: Dict[str, int]  # Simple contents for containers
    fuel: Dict[str, float]  # Burner fuel info


class EntityFilterOptions(TypedDict, total=False):
    """Filter options for get_entities / get_entity."""

    recipe: str
    direction: Direction
    entity_type: str
    status: str


class GhostAreaFilter(TypedDict, total=False):
    """Area filter for get_ghosts.

    Used to filter ghosts by spatial area and/or metadata.
    All fields are optional - omit to not filter on that criteria.

    Area can be specified as:
    - Bounding box: min_x, min_y, max_x, max_y
    - Circle: center_x, center_y, radius
    """

    # Bounding box filter
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    # Circle filter (alternative to bounding box)
    center_x: float
    center_y: float
    radius: float

    # Ghost-specific filters
    label: Optional[str]  # Filter by ghost label (set when placing)
    placed_tick: Optional[int]  # Filter by tick when ghost was placed
    entity_name: Optional[str]  # Filter by the entity type the ghost represents


# =============================================================================
# REACHABILITY SNAPSHOT DATA
# =============================================================================


class ReachableEntityData(TypedDict, total=False):
    """Entity data from get_reachable snapshot.

    RCON Contract: RemoteInterface.lua get_reachable.returns.schema.entities.item_schema
    """

    name: str
    type: str
    position: Dict[str, float]
    position_key: str
    status: str
    recipe: Optional[str]
    fuel_count: int
    input_contents: Dict[str, int]
    output_contents: Dict[str, int]
    contents: Dict[str, int]  # For chests


class ReachableResourceData(TypedDict, total=False):
    """Resource data from get_reachable snapshot.

    RCON Contract: RemoteInterface.lua get_reachable.returns.schema.resources.item_schema
    """

    name: str
    type: str
    position: Dict[str, float]
    position_key: str
    amount: int
    products: List[Dict[str, Any]]


class ReachableGhostData(TypedDict, total=False):
    """Ghost entity data from get_reachable snapshot.

    RCON Contract: RemoteInterface.lua get_reachable.returns.schema.ghosts.item_schema
    """

    name: str  # Always "entity-ghost"
    type: str  # Always "entity-ghost"
    position: Dict[str, float]
    position_key: str
    ghost_name: str  # The entity this ghost represents
    direction: int


class ReachableSnapshotData(TypedDict, total=False):
    """Full reachable snapshot response.

    RCON Contract: RemoteInterface.lua get_reachable.returns.schema
    """

    entities: List[ReachableEntityData]
    resources: List[ReachableResourceData]
    ghosts: List[ReachableGhostData]  # Only if attach_ghosts=True
    agent_position: Dict[str, float]
    tick: int


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Re-exported from factorio_types.py (authoritative source)
    "Direction",
    "EntityStatus",
    "MapTick",
    "TilePosition",
    "EntityID",
    "ItemID",
    "RecipeID",
    "FluidID",
    "TechnologyID",
    "TileID",
    "ResourceCategoryID",
    "RecipeCategoryID",
    "FuelCategoryID",
    "ItemGroupID",
    "ItemSubGroupID",
    "ModuleCategoryID",
    "get_entity_ids",
    "get_item_ids",
    "get_recipe_ids",
    "get_resource_entity_ids",
    "get_resource_tile_ids",
    "is_valid_entity_id",
    "is_valid_item_id",
    "is_valid_recipe_id",
    # Structural types (defined in this module)
    "Position",
    "AnchorVector",
    "MapPosition",
    "RealOrientation",
    "BoundingBox",
    # Async action types
    "WalkAsyncResponse",
    "MineAsyncResponse",
    "CraftAsyncResponse",
    "WalkCompletionPayload",
    "MineCompletionPayload",
    "CraftCompletionPayload",
    # Status types
    "CraftingQueueItem",
    "CraftingQueueStatus",
    "CraftingStatus",
    "ResearchQueueItem",
    "ResearchStatus",
    "ActionResult",
    # Inspection types
    "AgentActivityState",
    "AgentInspectionData",
    "ResourcePatchData",
    "ProductData",
    "EntityEnergyData",
    "EntityInventoriesData",
    "HeldItemData",
    "EntityInspectionData",
    "EntityFilterOptions",
    "GhostAreaFilter",
    # Reachability types
    "ReachableEntityData",
    "ReachableResourceData",
    "ReachableGhostData",
    "ReachableSnapshotData",
]
