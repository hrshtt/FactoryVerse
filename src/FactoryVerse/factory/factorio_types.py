"""Factorio Type System - Source of Truth for Game Types.

This module provides the authoritative type definitions for Factorio concepts:

1. ENUMS (from prototype-api.json - static, from Factorio devs):
   - Direction: 16 compass directions (ordered by game's defines.direction)
   - EntityStatus: 67 entity status codes (ordered by game's defines.entity_status)

2. TYPE ALIASES (structural types):
   - MapPosition: Float coordinates (x, y)
   - TilePosition: Integer tile coordinates (x, y)
   - BoundingBox: Rectangle with left_top and right_bottom
   - MapTick: Game tick counter (int)

3. LITERAL TYPE GENERATORS (from factorio-data-dump.json - runtime, filtered):
   - EntityID: Literal of valid entity prototype names
   - ItemID: Literal of valid item prototype names
   - RecipeID: Literal of valid recipe prototype names
   - FluidID, TechnologyID, TileID, etc.

Data Sources:
- prototype-api.json: Static API definitions from Factorio devs (enums, type structures)
- factorio-data-dump.json: Runtime dump from game (actual prototype names, varies by mods)

Usage:
    from FactoryVerse.factory.factorio_types import Direction, EntityStatus, MapTick
    from FactoryVerse.factory.factorio_types import get_entity_ids, get_item_ids
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Tuple,
)

if TYPE_CHECKING:
    from FactoryVerse.prototype_data import PrototypeDataManager


# =============================================================================
# ENUM LOADERS (from prototype-api.json)
# =============================================================================


@lru_cache(maxsize=1)
def _load_defines() -> Dict[str, List[Dict[str, Any]]]:
    """Load defines from prototype-api.json (cached).

    Uses FactoryVerseConfig to get the path - single source of truth for paths.

    Returns:
        Dict mapping define name to list of values with 'name' and 'order' keys.
    """
    from FactoryVerse.config import FactoryVerseConfig

    config = FactoryVerseConfig()
    proto_path = config.prototype_api_path

    if not proto_path.exists():
        raise FileNotFoundError(
            f"prototype-api.json not found at {proto_path}. "
            "Download from https://lua-api.factorio.com/2.0.72/prototype-api.json"
        )

    with open(proto_path, "r") as f:
        data = json.load(f)

    return {
        define["name"]: sorted(
            define.get("values", []), key=lambda x: x.get("order", 999)
        )
        for define in data.get("defines", [])
    }


# =============================================================================
# DIRECTION ENUM
# =============================================================================


class Direction(enum.Enum):
    """Direction in the game world.

    16 compass directions ordered by Factorio's defines.direction.
    Cardinal directions are: NORTH (0), EAST (4), SOUTH (8), WEST (12).

    Usually specified using defines.direction in Lua.
    Values match the game's internal representation.
    """

    # Cardinal directions
    NORTH = 0
    NORTH_NORTH_EAST = 1
    NORTH_EAST = 2
    EAST_NORTH_EAST = 3
    EAST = 4
    EAST_SOUTH_EAST = 5
    SOUTH_EAST = 6
    SOUTH_SOUTH_EAST = 7
    SOUTH = 8
    SOUTH_SOUTH_WEST = 9
    SOUTH_WEST = 10
    WEST_SOUTH_WEST = 11
    WEST = 12
    WEST_NORTH_WEST = 13
    NORTH_WEST = 14
    NORTH_NORTH_WEST = 15

    def is_cardinal(self) -> bool:
        """Check if this is a cardinal direction (N, E, S, W)."""
        return self in (
            Direction.NORTH,
            Direction.EAST,
            Direction.SOUTH,
            Direction.WEST,
        )

    def turn_left(self) -> "Direction":
        """Turn 90 degrees counter-clockwise (only for cardinal directions)."""
        if not self.is_cardinal():
            raise ValueError(f"Cannot turn non-cardinal direction: {self.name}")
        return Direction((self.value - 4) % 16)

    def turn_right(self) -> "Direction":
        """Turn 90 degrees clockwise (only for cardinal directions)."""
        if not self.is_cardinal():
            raise ValueError(f"Cannot turn non-cardinal direction: {self.name}")
        return Direction((self.value + 4) % 16)

    def flip(self) -> "Direction":
        """Turn 180 degrees (only for cardinal directions)."""
        if not self.is_cardinal():
            raise ValueError(f"Cannot flip non-cardinal direction: {self.name}")
        return Direction((self.value + 8) % 16)

    def to_lua_name(self) -> str:
        """Get Lua-style name (e.g., 'north', 'northnortheast')."""
        return self.name.lower().replace("_", "")


# =============================================================================
# ENTITY STATUS ENUM
# =============================================================================


class EntityStatus(enum.Enum):
    """Entity status codes from defines.entity_status (Factorio 2.0).

    These represent the operational state of entities in the game.
    Values match Factorio 2.0's internal defines.entity_status exactly.

    Common statuses:
    - WORKING (1): Entity is actively working
    - NO_POWER (54): Entity lacks electrical power
    - NO_FUEL (53): Burner entity lacks fuel
    - NO_RECIPE (19): Crafter has no recipe set
    - FULL_OUTPUT (27): Output inventory is full

    Note: Factorio 2.0 completely reorganized these values compared to 1.x.
    """

    # Core states (1-4)
    WORKING = 1
    NORMAL = 2
    GHOST = 3
    BROKEN = 4

    # Electric network states (5-15)
    NOT_PLUGGED_IN_ELECTRIC_NETWORK = 5
    NETWORKS_CONNECTED = 6
    NETWORKS_DISCONNECTED = 7
    CHARGING = 8
    DISCHARGING = 9
    FULLY_CHARGED = 10
    TURNED_OFF_DURING_DAYTIME = 11
    CANT_DIVIDE_SEGMENTS = 12
    NOT_CONNECTED_TO_RAIL = 13
    LOW_POWER = 14
    OUT_OF_LOGISTIC_NETWORK = 15

    # Agriculture/growth states (16-17)
    WAITING_FOR_PLANTS_TO_GROW = 16
    NO_SPOT_SEEDABLE_BY_INPUTS = 17

    # Recipe/ingredient states (18-31)
    NO_INGREDIENTS = 18
    NO_RECIPE = 19
    NO_RESEARCH_IN_PROGRESS = 20
    NO_MINABLE_RESOURCES = 21
    NOT_CONNECTED_TO_HUB_OR_PAD = 22
    LOW_INPUT_FLUID = 23
    NO_INPUT_FLUID = 24
    FLUID_INGREDIENT_SHORTAGE = 25
    ITEM_INGREDIENT_SHORTAGE = 26
    FULL_OUTPUT = 27
    NOT_ENOUGH_SPACE_IN_OUTPUT = 28
    FULL_BURNT_RESULT_OUTPUT = 29
    MISSING_REQUIRED_FLUID = 30
    MISSING_SCIENCE_PACKS = 31

    # Waiting states (32-34)
    WAITING_FOR_SOURCE_ITEMS = 32
    WAITING_FOR_MORE_ITEMS = 33
    WAITING_FOR_SPACE_IN_DESTINATION = 34

    # Rocket/space states (35-49)
    PREPARING_ROCKET_FOR_LAUNCH = 35
    WAITING_TO_LAUNCH_ROCKET = 36
    WAITING_FOR_SPACE_IN_PLATFORM_HUB = 37
    LAUNCHING_ROCKET = 38
    THRUST_NOT_REQUIRED = 39
    ON_THE_WAY = 40
    WAITING_IN_ORBIT = 41
    WAITING_AT_STOP = 42
    WAITING_FOR_ROCKETS_TO_ARRIVE = 43
    NOT_ENOUGH_THRUST = 44
    DESTINATION_STOP_FULL = 45
    NO_PATH = 46
    NO_MODULES_TO_TRANSMIT = 47
    RECHARGING_AFTER_POWER_OUTAGE = 48
    WAITING_FOR_TARGET_TO_BE_BUILT = 49

    # Train/power/control states (50-62)
    WAITING_FOR_TRAIN = 50
    NO_AMMO = 51
    LOW_TEMPERATURE = 52
    NO_FUEL = 53
    NO_POWER = 54
    DISABLED_BY_CONTROL_BEHAVIOR = 55
    CLOSED_BY_CIRCUIT_NETWORK = 56
    OPENED_BY_CIRCUIT_NETWORK = 57
    FROZEN = 58
    PAUSED = 59
    DISABLED_BY_SCRIPT = 60
    DISABLED = 61
    MARKED_FOR_DECONSTRUCTION = 62

    # Navigation/misc states (63-67)
    COMPUTING_NAVIGATION = 63
    NO_FILTER = 64
    PIPELINE_OVEREXTENDED = 65
    RECIPE_NOT_RESEARCHED = 66
    RECIPE_IS_PARAMETER = 67

    def to_lua_name(self) -> str:
        """Get Lua-style name (e.g., 'working', 'no_power')."""
        return self.name.lower()

    @classmethod
    def from_lua_name(cls, name: str) -> "EntityStatus":
        """Create from Lua-style name."""
        return cls[name.upper()]


# =============================================================================
# BASIC TYPE ALIASES
# =============================================================================


# MapTick: Game tick counter (60 ticks = 1 second)
MapTick = int


@dataclass(frozen=True)
class TilePosition:
    """Integer tile coordinates on the map.

    Each tile is a 1x1 unit area. Positive x goes east, positive y goes south.
    Unlike MapPosition, TilePosition uses integer coordinates.
    """

    x: int
    y: int

    def __hash__(self) -> int:
        return hash((self.x, self.y))

    @classmethod
    def from_map_position(cls, x: float, y: float) -> "TilePosition":
        """Convert map position to tile position (floors coordinates)."""
        import math

        return cls(x=math.floor(x), y=math.floor(y))

    def to_tuple(self) -> Tuple[int, int]:
        """Convert to tuple (x, y)."""
        return (self.x, self.y)


# =============================================================================
# LITERAL TYPE GENERATORS (from runtime dump)
# =============================================================================


def _get_prototype_manager() -> "PrototypeDataManager":
    """Get PrototypeDataManager (lazy import to avoid circular deps)."""
    from FactoryVerse.prototype_data import get_prototype_manager

    return get_prototype_manager()


def get_entity_ids() -> List[str]:
    """Get list of valid EntityID values (filtered entity names).

    These come from factorio-data-dump.json, filtered by fv_filters.yaml.

    Returns:
        Sorted list of entity prototype names like ['assembling-machine-1', 'stone-furnace', ...]
    """
    return _get_prototype_manager().get_filtered_entities()


def get_item_ids() -> List[str]:
    """Get list of valid ItemID values (filtered item names).

    These come from factorio-data-dump.json, filtered by fv_filters.yaml.

    Returns:
        Sorted list of item prototype names like ['iron-plate', 'copper-plate', ...]
    """
    return _get_prototype_manager().get_filtered_items()


def get_recipe_ids() -> List[str]:
    """Get list of valid RecipeID values (filtered recipe names).

    These come from factorio-data-dump.json, filtered by fv_filters.yaml.

    Returns:
        Sorted list of recipe prototype names like ['iron-plate', 'automation-science-pack', ...]
    """
    return _get_prototype_manager().get_filtered_recipes()


def get_resource_entity_ids() -> List[str]:
    """Get list of valid ResourceEntityID values (trees, rocks).

    Returns:
        Sorted list of resource entity names like ['tree-01', 'rock-big', ...]
    """
    return _get_prototype_manager().get_resource_entities()


def get_resource_tile_ids() -> List[str]:
    """Get list of valid ResourceTileID values (ore patches).

    Returns:
        Sorted list of resource tile names like ['iron-ore', 'copper-ore', ...]
    """
    return _get_prototype_manager().get_resource_tiles()


# =============================================================================
# TYPE ALIASES FOR SEMANTIC CLARITY
# =============================================================================

# These are string types but provide semantic meaning
# In practice they're Literal[...] of the actual valid values

# Entity prototype name (e.g., "stone-furnace", "assembling-machine-1")
EntityID = str

# Item prototype name (e.g., "iron-plate", "copper-plate")
ItemID = str

# Recipe prototype name (e.g., "iron-plate", "automation-science-pack")
RecipeID = str

# Fluid prototype name (e.g., "water", "petroleum-gas")
FluidID = str

# Technology prototype name (e.g., "automation", "logistics")
TechnologyID = str

# Tile prototype name (e.g., "grass-1", "water")
TileID = str

# Resource category name (e.g., "basic-solid", "basic-fluid")
ResourceCategoryID = str

# Recipe category name (e.g., "crafting", "smelting")
RecipeCategoryID = str

# Fuel category name (e.g., "chemical", "nuclear")
FuelCategoryID = str

# Item group name (e.g., "logistics", "production")
ItemGroupID = str

# Item subgroup name (e.g., "belt", "inserter")
ItemSubGroupID = str

# Module category name (e.g., "speed", "productivity")
ModuleCategoryID = str


# =============================================================================
# VALIDATION HELPERS
# =============================================================================


def is_valid_entity_id(name: str) -> bool:
    """Check if a name is a valid filtered EntityID."""
    return name in get_entity_ids()


def is_valid_item_id(name: str) -> bool:
    """Check if a name is a valid filtered ItemID."""
    return name in get_item_ids()


def is_valid_recipe_id(name: str) -> bool:
    """Check if a name is a valid filtered RecipeID."""
    return name in get_recipe_ids()


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "Direction",
    "EntityStatus",
    # Type aliases
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
    # Getters for Literal values
    "get_entity_ids",
    "get_item_ids",
    "get_recipe_ids",
    "get_resource_entity_ids",
    "get_resource_tile_ids",
    # Validators
    "is_valid_entity_id",
    "is_valid_item_id",
    "is_valid_recipe_id",
]
