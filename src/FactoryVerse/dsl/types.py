from dataclasses import dataclass
import enum
import math
from typing import Self, Tuple, Union, Any, List, Dict, TypeVar, Optional, TYPE_CHECKING
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
