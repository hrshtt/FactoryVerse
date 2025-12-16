from typing import Tuple, List, Dict, Any, Optional
from src.FactoryVerse.dsl.types import MapPosition, Direction, BoundingBox
from dataclasses import dataclass
import json
import math


def apply_cardinal_vector(
    map_position: MapPosition,
    vector: Tuple[float, float],
    direction: Direction,
) -> MapPosition:
    """Apply a vector transformation based on direction.

    Rotates a vector relative to NORTH based on the given direction.
    """
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


def get_width_height(bbox: List[List[float]]) -> Tuple[float, float]:
    """Calculate width and height from a bounding box.
    
    Args:
        bbox: A list of two points, e.g., [[x1, y1], [x2, y2]],
              representing opposite corners of the bounding box.
    
    Returns:
        Tuple of (width, height).
    """
    (x1, y1) = bbox[0]
    (x2, y2) = bbox[1]
    width = abs(x1 - x2)
    height = abs(y1 - y2)
    return width, height


@dataclass(frozen=True, slots=True)
class BasePrototype:
    """Base class for prototype property accessors."""

    _data: Dict[str, Any]

    def __getitem__(self, key):
        return self._data[key]

    def get_raw(self) -> Dict[str, Any]:
        return self._data

    @property
    def tile_width(self) -> int:
        """Get the tile width of this entity.
        
        Uses explicit tile_width if available, otherwise calculates from collision_box.
        """
        # Tiny value to prevent 2.000001 rounding up to 3
        EPSILON = 0.001
        
        # 1. Check for explicit tile_width
        final_w = self._data.get('tile_width')
        if final_w is not None:
            return int(final_w)
        
        # 2. Calculate from collision_box
        if 'collision_box' in self._data:
            c_w, _ = get_width_height(self._data['collision_box'])
            return int(math.ceil(c_w - EPSILON))
        
        # 3. Entities with no collision box (e.g. smoke, ghosts)
        return 0

    @property
    def tile_height(self) -> int:
        """Get the tile height of this entity.
        
        Uses explicit tile_height if available, otherwise calculates from collision_box.
        """
        # Tiny value to prevent 2.000001 rounding up to 3
        EPSILON = 0.001
        
        # 1. Check for explicit tile_height
        final_h = self._data.get('tile_height')
        if final_h is not None:
            return int(final_h)
        
        # 2. Calculate from collision_box
        if 'collision_box' in self._data:
            _, c_h = get_width_height(self._data['collision_box'])
            return int(math.ceil(c_h - EPSILON))
        
        # 3. Entities with no collision box (e.g. smoke, ghosts)
        return 0


@dataclass(frozen=True)
class TransportBeltPrototype(BasePrototype):
    """Prototype accessor for transport-belt."""

    pass


@dataclass(frozen=True)
class ElectricMiningDrillPrototype(BasePrototype):
    """Prototype accessor for electric-mining-drill."""

    _output_vector: Tuple[float, float]
    _search_radius: float

    @classmethod
    def from_data(cls, data: Dict[str, Any]) -> "ElectricMiningDrillPrototype":
        """Create instance from raw prototype data."""
        return cls(
            _data=data,
            _output_vector=tuple(data["vector_to_place_result"]),
            _search_radius=data["resource_searching_radius"],
        )

    def get_resource_search_area(self, centroid: MapPosition) -> BoundingBox:
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

    def output_position(
        self, centroid: MapPosition, direction: Direction
    ) -> MapPosition:
        """
        Given a centroid (MapPosition) and a direction (Direction.{NORTH, EAST, SOUTH, WEST}),
        return the actual MapPosition of the drill's output.
        The vector_to_place_result is always for NORTH; just map 0/4/8/12 to rotation.
        """
        return apply_cardinal_vector(centroid, self._output_vector, direction)


@dataclass(frozen=True)
class BurnerMiningDrillPrototype(BasePrototype):
    """Prototype accessor for burner-mining-drill."""

    def get_fuel_type(self) -> str:
        return self._data.get("energy_source", {}).get("fuel_category")


@dataclass(frozen=True)
class PumpjackPrototype(BasePrototype):
    """Prototype accessor for pumpjack."""

    _pipe_vectors: List[Tuple[float, float]]

    @classmethod
    def from_data(cls, data: Dict[str, Any]) -> "PumpjackPrototype":
        """Create instance from raw prototype data."""
        pipe_vectors = [
            tuple(v)
            for v in data["output_fluid_box"]["pipe_connections"][0]["positions"]
        ]
        return cls(
            _data=data,
            _pipe_vectors=pipe_vectors,
        )

    def get_output_fluid_box(self) -> dict:
        return self._data.get("output_fluid_box")

    def output_pipe_connections(self, centroid: MapPosition) -> List[MapPosition]:
        return [
            apply_cardinal_vector(centroid, vector, Direction.NORTH)
            for vector in self._pipe_vectors
        ]

@dataclass(frozen=True)
class ElectricPolePrototype(BasePrototype):
    """Prototype accessor for electric-pole."""

    _supply_area_distance: float
    _maximum_wire_distance: float

    @classmethod
    def from_data(cls, data: Dict[str, Any]) -> "ElectricPolePrototype":
        return cls(
            _data=data,
            _supply_area_distance=data["supply_area_distance"],
            _maximum_wire_distance=data["maximum_wire_distance"],
        )

    def get_supply_area(self, centroid: MapPosition) -> BoundingBox:
        return BoundingBox.from_tuple((centroid.x - self._supply_area_distance, centroid.y - self._supply_area_distance), (centroid.x + self._supply_area_distance, centroid.y + self._supply_area_distance))
    
    @property
    def supply_area_distance(self) -> float:
        return self._supply_area_distance
    
    @property
    def maximum_wire_distance(self) -> float:
        return self._maximum_wire_distance


@dataclass(frozen=True)
class InserterPrototype(BasePrototype):
    """Prototype accessor for inserter."""

    _pickup_vector: Tuple[float, float]
    _insert_vector: Tuple[float, float]

    @classmethod
    def from_data(cls, data: Dict[str, Any]) -> "InserterPrototype":
        """Create instance from raw prototype data."""
        return cls(
            _data=data,
            _pickup_vector=tuple(data["pickup_position"]),
            _insert_vector=tuple(data["insert_position"]),
        )

    def pickup_position(
        self, centroid: MapPosition, direction: Direction
    ) -> MapPosition:
        return apply_cardinal_vector(centroid, self._pickup_vector, direction)

    def drop_position(self, centroid: MapPosition, direction: Direction) -> MapPosition:
        return apply_cardinal_vector(centroid, self._insert_vector, direction)


@dataclass(frozen=True)
class LongHandedInserterPrototype(InserterPrototype):
    """Prototype accessor for long-handed-inserter."""

    # Inherits pickup/drop methods from InserterPrototype
    @classmethod
    def from_data(cls, data: Dict[str, Any]) -> "LongHandedInserterPrototype":
        """Create instance from raw prototype data."""
        return cls(
            _data=data,
            _pickup_vector=tuple(data["pickup_position"]),
            _insert_vector=tuple(data["insert_position"]),
        )


@dataclass(frozen=True)
class FastInserterPrototype(InserterPrototype):
    """Prototype accessor for fast-inserter."""

    @classmethod
    def from_data(cls, data: Dict[str, Any]) -> "FastInserterPrototype":
        """Create instance from raw prototype data."""
        return cls(
            _data=data,
            _pickup_vector=tuple(data["pickup_position"]),
            _insert_vector=tuple(data["insert_position"]),
        )

class EntityPrototypes:
    """Aggregator for all prototype property accessors."""

    def __init__(self, dump_file: str):
        with open(dump_file, "r") as f:
            self.data = json.load(f)

        # Build reverse map: entity_name -> category (type)
        # Exclude known non-entity categories to avoid collisions (e.g., technology vs entity name)
        ignore_categories = {
            "item", "recipe", "technology", "fluid", "tile", "virtual-signal", 
            "achievement", "item-group", "item-subgroup", "recipe-category",
            "fuel-category", "resource-category", "module-category", "equipment-category",
            "ammo-category", "autoplace-control", "custom-input", "font", "gui-style",
            "mouse-cursor", "noise-layer", "particle", "sound", "sprite", "tile-effect",
            "tips-and-tricks-item-category", "tips-and-tricks-item", "trivial-smoke",
            "utility-constants", "utility-sounds", "utility-sprites"
        }
        
        self.entity_type_map: Dict[str, str] = {}
        for category, entities in self.data.items():
            if category in ignore_categories:
                continue
            if isinstance(entities, dict):
                for entity_name in entities:
                    self.entity_type_map[entity_name] = category

        # Instantiate all prototypes once
        if "transport-belt" in self.data and "transport-belt" in self.data["transport-belt"]:
            self.transport_belt = TransportBeltPrototype(
                _data=self.data["transport-belt"]["transport-belt"]
            )
        else:
             # Fallback or optional?
             pass

        if "mining-drill" in self.data:
            if "electric-mining-drill" in self.data["mining-drill"]:
                self.electric_mining_drill = ElectricMiningDrillPrototype.from_data(
                    self.data["mining-drill"]["electric-mining-drill"]
                )
            if "burner-mining-drill" in self.data["mining-drill"]:
                self.burner_mining_drill = BurnerMiningDrillPrototype(
                    _data=self.data["mining-drill"]["burner-mining-drill"]
                )
            if "pumpjack" in self.data["mining-drill"]:
                self.pumpjack = PumpjackPrototype.from_data(
                    self.data["mining-drill"]["pumpjack"]
                )
        
        if "inserter" in self.data:
            if "inserter" in self.data["inserter"]:
                self.inserter = InserterPrototype.from_data(self.data["inserter"]["inserter"])
            if "long-handed-inserter" in self.data["inserter"]:
                self.long_handed_inserter = LongHandedInserterPrototype.from_data(
                    self.data["inserter"]["long-handed-inserter"]
                )
            if "fast-inserter" in self.data["inserter"]:
                self.fast_inserter = FastInserterPrototype.from_data(
                    self.data["inserter"]["fast-inserter"]
                )
        
        if "electric-pole" in self.data:
            for pole_name, pole_data in self.data["electric-pole"].items():
                if not hasattr(self, 'electric_poles'):
                    self.electric_poles = {}
                self.electric_poles[pole_name] = ElectricPolePrototype.from_data(pole_data)
        
        # Cache tile dimensions for all placeable entities
        self._tile_dimensions_cache: Dict[str, Tuple[int, int]] = {}
        self._build_tile_dimensions_cache()

    def _build_tile_dimensions_cache(self):
        """Pre-compute tile dimensions for all placeable entities."""
        EPSILON = 0.001
        
        for category, entities in self.data.items():
            if category in {
                "item", "recipe", "technology", "fluid", "tile", "virtual-signal", 
                "achievement", "item-group", "item-subgroup", "recipe-category",
                "fuel-category", "resource-category", "module-category", "equipment-category",
                "ammo-category", "autoplace-control", "custom-input", "font", "gui-style",
                "mouse-cursor", "noise-layer", "particle", "sound", "sprite", "tile-effect",
                "tips-and-tricks-item-category", "tips-and-tricks-item", "trivial-smoke",
                "utility-constants", "utility-sounds", "utility-sprites"
            }:
                continue
            
            if isinstance(entities, dict):
                for entity_name, entity_data in entities.items():
                    if "collision_box" not in entity_data:
                        continue
                    
                    # Calculate tile dimensions
                    final_w = entity_data.get('tile_width')
                    final_h = entity_data.get('tile_height')
                    
                    if final_w is None or final_h is None:
                        if 'collision_box' in entity_data:
                            c_w, c_h = get_width_height(entity_data['collision_box'])
                            if final_w is None:
                                final_w = int(math.ceil(c_w - EPSILON))
                            if final_h is None:
                                final_h = int(math.ceil(c_h - EPSILON))
                        else:
                            final_w, final_h = 0, 0
                    
                    self._tile_dimensions_cache[entity_name] = (int(final_w), int(final_h))

    def get_entity_type(self, entity_name: str) -> Optional[str]:
        """Get the prototype category (type) for an entity name."""
        return self.entity_type_map.get(entity_name)

    def get_tile_dimensions(self, entity_name: str) -> Tuple[int, int]:
        """Get tile dimensions (width, height) for an entity by name.
        
        Args:
            entity_name: Name of the entity (e.g., "stone-furnace", "electric-mining-drill")
        
        Returns:
            Tuple of (tile_width, tile_height)
        
        Raises:
            KeyError: If entity_name is not found in the cache
        """
        if entity_name not in self._tile_dimensions_cache:
            # Try to compute on the fly if not in cache
            entity_type = self.get_entity_type(entity_name)
            if entity_type and entity_type in self.data:
                entities = self.data[entity_type]
                if isinstance(entities, dict) and entity_name in entities:
                    entity_data = entities[entity_name]
                    if "collision_box" in entity_data:
                        EPSILON = 0.001
                        final_w = entity_data.get('tile_width')
                        final_h = entity_data.get('tile_height')
                        
                        if final_w is None or final_h is None:
                            if 'collision_box' in entity_data:
                                c_w, c_h = get_width_height(entity_data['collision_box'])
                                if final_w is None:
                                    final_w = int(math.ceil(c_w - EPSILON))
                                if final_h is None:
                                    final_h = int(math.ceil(c_h - EPSILON))
                            else:
                                final_w, final_h = 0, 0
                        
                        dims = (int(final_w), int(final_h))
                        self._tile_dimensions_cache[entity_name] = dims
                        return dims
        
        return self._tile_dimensions_cache[entity_name]

class ItemPrototypes:
    """Prototype accessor for items."""

    def __init__(self, dump_file: str):
        with open(dump_file, "r") as f:
            self.data = json.load(f)
        
        # item data is usually under data['item']
        self.items = self.data.get("item", {})

    def get_place_result(self, item_name: str) -> Optional[str]:
        """Get the entity name that this item places, if any."""
        item_data = self.items.get(item_name)
        if not item_data:
            return None
        return item_data.get("place_result")


# Singleton instance - owned by this module
_prototypes: Optional[EntityPrototypes] = None
_item_prototypes: Optional[ItemPrototypes] = None

# Default dump file path (can be overridden in get_prototypes)
DEFAULT_DUMP_FILE = "factorio-data-dump.json"


def get_entity_prototypes(dump_file: str = DEFAULT_DUMP_FILE) -> EntityPrototypes:
    """Get the global prototypes singleton instance.
    
    The singleton is instantiated on first call and reused for subsequent calls.
    This ensures all entities share the same prototype instances.
    
    Args:
        dump_file: Path to the Factorio prototype data dump JSON file.
                  Only used on first call; subsequent calls ignore this parameter.
        
    Returns:
        EntityPrototypes instance (singleton, instantiated on first call)
        
    Example:
        >>> prototypes = get_prototypes()
        >>> drill_proto = prototypes.electric_mining_drill
        >>> output_pos = drill_proto.output_position(centroid, Direction.EAST)
    """
    global _prototypes
    if _prototypes is None:
        _prototypes = EntityPrototypes(dump_file)
    return _prototypes


def reset_prototypes():
    """Reset the singleton instance (useful for testing or reloading).
    
    After calling this, the next call to get_prototypes() will create a new
    instance from the dump file.
    
    Example:
        >>> reset_prototypes()
        >>> prototypes = get_prototypes("new-dump-file.json")
    """
    global _prototypes
    global _item_prototypes
    _prototypes = None
    _item_prototypes = None

def get_item_prototypes(dump_file: str = DEFAULT_DUMP_FILE) -> ItemPrototypes:
    """Get the global item prototypes singleton instance."""
    global _item_prototypes
    if _item_prototypes is None:
        _item_prototypes = ItemPrototypes(dump_file)
    return _item_prototypes