from dataclasses import dataclass
import enum


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


class AnchorVector(Position): ...


class MapPosition(Position): ...


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