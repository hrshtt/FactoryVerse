from dataclasses import dataclass
import enum
import math
from typing import (
    Self, Tuple, Union, Any, List, Dict, TypeVar, Optional, 
    TYPE_CHECKING, TypedDict
)
from contextvars import ContextVar

if TYPE_CHECKING:
    from FactoryVerse.dsl.agent import PlayingFactory


class Direction(enum.Enum):
    """Direction in the game world.

    Usually specified by using [defines.direction](runtime:defines.direction).
    """

    NORTH = 0  # North
    NORTH_NORTH_EAST = 1  # NorthNorthEast
    NORTH_EAST = 2  # NorthEast
    EAST_NORTH_EAST = 3  # EastNorthEast
    EAST = 4  # East
    EAST_SOUTH_EAST = 5  # EastSouthEast
    SOUTH_EAST = 6  # SouthEast
    SOUTH_SOUTH_EAST = 7  # SouthSouthEast
    SOUTH = 8  # South
    SOUTH_SOUTH_WEST = 9  # SouthSouthWest
    SOUTH_WEST = 10  # SouthWest
    WEST_SOUTH_WEST = 11  # WestSouthWest
    WEST = 12  # West
    WEST_NORTH_WEST = 13  # WestNorthWest
    NORTH_WEST = 14  # NorthWest
    NORTH_NORTH_WEST = 15  # NorthNorthWest

    def is_cardinal(self) -> bool:
        return self in (
            Direction.NORTH,
            Direction.EAST,
            Direction.SOUTH,
            Direction.WEST,
        )

    def turn_left(self) -> "Direction":
        # For cardinal directions, turn left by subtracting 4 (90 degrees CCW) modulo 16.
        if not self.is_cardinal():
            raise ValueError(f"Cannot turn non-cardinal direction: {self.name}")
        return Direction((self.value - 4) % 16)

    def turn_right(self) -> "Direction":
        # For cardinal directions, turn right by adding 4 (90 degrees CW) modulo 16.
        if not self.is_cardinal():
            raise ValueError(f"Cannot turn non-cardinal direction: {self.name}")
        return Direction((self.value + 4) % 16)

    def flip(self) -> "Direction":
        """Flip the direction 180 degrees."""
        if not self.is_cardinal():
            raise ValueError(f"Cannot flip non-cardinal direction: {self.name}")
        return Direction((self.value + 8) % 16)


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
    orientation: RealOrientation = None

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
            return cls(left_top=lt, right_bottom=rb, orientation=orientation)
        else:
            raise ValueError(
                "BoundingBox expects (left_top, right_bottom) or (left_top, right_bottom, orientation)"
            )
# Game context: agent is "playing" the factory game
# Defined here to break circular dependencies between agent, entity, and mixins
_playing_factory: ContextVar[Optional["PlayingFactory"]] = ContextVar(
    "playing_factory", default=None
)


# =============================================================================
# ASYNC ACTION RESPONSES
# =============================================================================
# These TypedDicts match the return schemas from RemoteInterface.lua INTERFACE_METHODS
# Each async action returns immediately with queued status; completion comes via UDP.

class AsyncActionResponse(TypedDict, total=False):
    """Base response from an asynchronous RCON action.
    
    RCON Contract: RemoteInterface.lua async_action.schema
    All async actions return at least {queued, action_id}.
    """
    queued: bool
    action_id: Optional[str]
    estimated_ticks: Optional[int]


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

class CraftingStatus(TypedDict):
    """Current crafting status for an agent."""
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
    burning_progress: float   # 0.0-1.0 (furnaces)
    productivity_bonus: float
    
    # Energy (electric entities)
    energy: EntityEnergyData
    
    # Inventories by slot type
    inventories: EntityInventoriesData
    
    # Inserter-specific
    held_item: HeldItemData
    
    # Legacy/compatibility fields (may be used by older code)
    inventory: Dict[str, int]  # Simple contents for containers
    fuel: Dict[str, float]     # Burner fuel info


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
    label: Optional[str]        # Filter by ghost label (set when placing)
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
# PLACEMENT CUES DATA
# =============================================================================

class PlacementCueData(TypedDict, total=False):
    """Single placement cue position.
    
    RCON Contract: RemoteInterface.lua get_placement_cues.returns.schema
    """
    position: Dict[str, float]
    resource_name: Optional[str]
    resource_amount: Optional[int]


class PlacementCuesResponse(TypedDict):
    """Response from get_placement_cues query.
    
    RCON Contract: RemoteInterface.lua get_placement_cues.returns.schema
    """
    entity_name: str
    collision_box: Dict[str, Any]
    tile_width: int
    tile_height: int
    positions: List[PlacementCueData]
    reachable_positions: List[PlacementCueData]
