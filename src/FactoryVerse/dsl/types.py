from dataclasses import dataclass
from typing import Tuple, List
import enum
import json


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


class PrototypeProperties:

    def __init__(self, dump_file: str):
        with open(dump_file, "r") as f:
            self.data = json.load(f)

    def apply_vector(
        self,
        map_position: MapPosition,
        vector: Tuple[float, float],
        direction: Direction,
    ):
        vx, vy = vector
        if not direction.is_cardinal():
            raise ValueError("Direction must be cardinal")
        if direction == Direction.EAST:
            vx, vy = vy, -vx
        elif direction == Direction.SOUTH:
            vx, vy = -vx, -vy
        elif direction == Direction.WEST:
            vx, vy = -vy, vx
        return MapPosition(x=map_position.x + vx, y=map_position.y + vy)

    @property
    def transport_belt(self):
        data = self.data["transport-belt"]["transport-belt"]

        class _Proxy:
            def __init__(self, data, root):
                self._data = data
                self._root = root

            def __getitem__(self, key):
                return self._data[key]

            def get_raw(self):
                return self._data

        return _Proxy(data, self)

    @property
    def electric_mining_drill(self):
        data = self.data["mining-drill"]["electric-mining-drill"]
        from src.FactoryVerse.dsl.types import MapPosition, BoundingBox

        import math

        class _Proxy:
            def __init__(self, data, root):
                self._data = data
                self._root = root
                self._output_vector = data["vector_to_place_result"]
                self._search_radius = data["resource_searching_radius"]

            def __getitem__(self, key):
                return self._data[key]

            def get_raw(self):
                return self._data

            def get_resource_search_area(self, centroid: MapPosition):
                """
                Return a BoundingBox for the resource search area,
                centering the box at the centroid and with a half-width of resource_searching_radius.
                """
                r = self._search_radius
                if r is None:
                    raise ValueError(
                        "resource_searching_radius not found in electric-mining-drill prototype"
                    )
                x = centroid.x
                y = centroid.y
                left_top = (x - r, y - r)
                right_bottom = (x + r, y + r)
                return BoundingBox.from_tuple((left_top, right_bottom))

            def output_position(self, centroid: MapPosition, direction: Direction):
                """
                Given a centroid (MapPosition) and a direction (Direction.{NORTH, EAST, SOUTH, WEST}),
                return the actual MapPosition of the drill's output.
                The vector_to_place_result is always for NORTH; just map 0/4/8/12 to rotation.
                """
                return self.apply_vector(centroid, self._output_vector, direction)

        return _Proxy(data, self)

    @property
    def burner_mining_drill(self):
        data = self.data["mining-drill"]["burner-mining-drill"]

        class _Proxy:
            def __init__(self, data, root):
                self._data = data
                self._root = root

            def __getitem__(self, key):
                return self._data[key]

            def get_raw(self):
                return self._data

            def get_fuel_type(self):
                return self._data.get("energy_source", {}).get("fuel_category")

        return _Proxy(data, self)

    @property
    def pumpjack(self):
        data = self.data["mining-drill"]["pumpjack"]

        class _Proxy:
            def __init__(self, data, root):
                self._data = data
                self._root = root
                self._pipe_vectors = data["output_fluid_box"]["pipe_connections"][0]["positions"]

            def __getitem__(self, key):
                return self._data[key]

            def get_raw(self):
                return self._data

            def get_output_fluid_box(self):
                return self._data.get("output_fluid_box")
            
            def output_pipe_connections(self, centroid: MapPosition) -> List[MapPosition]:
                return [self.apply_vector(centroid, vector, Direction.NORTH) for vector in self._pipe_vectors]

        return _Proxy(data, self)

    @property
    def inserter(self):
        data = self.data["inserter"]["inserter"]

        class _Proxy:
            def __init__(self, data, root):
                self._data = data
                self._root = root

                # These are relative positions from inserter center.
                self._pickup_vector = self._data["pickup_vector"]
                self._insert_vector = self._data["insert_vector"]

            def __getitem__(self, key):
                return self._data[key]

            def get_raw(self):
                return self._data

            def pickup_position(self, centroid: MapPosition, direction: Direction):
                return self.apply_vector(centroid, self._pickup_vector, direction)

            def drop_position(self, centroid: MapPosition, direction: Direction):
                return self.apply_vector(centroid, self._insert_vector, direction)

        return _Proxy(data, self)

    @property
    def long_handed_inserter(self):
        data = self.data["inserter"]["long-handed-inserter"]

        class _Proxy:
            def __init__(self, data, root):
                self._data = data
                self._root = root

            def __getitem__(self, key):
                return self._data[key]

            def get_raw(self):
                return self._data

            def pickup_position(self, centroid: MapPosition, direction: Direction):
                return self.apply_vector(centroid, self._pickup_vector, direction)

            def drop_position(self, centroid: MapPosition, direction: Direction):
                return self.apply_vector(centroid, self._insert_vector, direction)

        return _Proxy(data, self)
