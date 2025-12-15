"""
DuckDB schema and initialization helpers for FactoryVerse map view + analytics.

This module defines the new normalized schema with ENUMs and spatial types.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import duckdb
import json


DEFAULT_DB_FILENAME = "factoryverse-map.duckdb"


def _get_direction_enum(prototype_api_file: Optional[str] = None) -> List[str]:
    """Get direction enum values from prototype API or Direction enum."""
    if prototype_api_file:
        try:
            with open(prototype_api_file, "r") as f:
                raw_proto = json.load(f)
                defines = {i["name"]: i for i in raw_proto.get("defines", []) if i["name"] == "direction"}
                if "direction" in defines:
                    direction_enum = [item['name'] for item in sorted(defines["direction"]["values"], key=lambda x: x['order'])]
                    return direction_enum
        except:
            pass
    
    # Fallback to Direction enum
    from src.FactoryVerse.dsl.types import Direction
    return [d.name for d in Direction]


def _get_status_enum(prototype_api_file: Optional[str] = None) -> List[str]:
    """Get status enum values from prototype API or default values."""
    if prototype_api_file:
        try:
            with open(prototype_api_file, "r") as f:
                raw_proto = json.load(f)
                defines = {i["name"]: i for i in raw_proto.get("defines", []) if i["name"] == "entity_status"}
                if "entity_status" in defines:
                    status_enum = [item['name'] for item in sorted(defines["entity_status"]["values"], key=lambda x: x['order'])]
                    return status_enum
        except:
            pass
    
    # Fallback to default values
    return ["active", "inactive", "disabled", "working", "no_power", "no_fuel", "no_recipe"]


def _extract_enums_from_prototypes(dump_file: str, prototype_api_file: Optional[str] = None) -> Dict[str, List[str]]:
    """Extract enum values from prototype data dump, matching the filtering logic from the original schema."""
    try:
        with open(dump_file, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {
            "recipes": [],
            "resource_entities": [],
            "resource_tiles": [],
            "placeable_entities": [],
        }
    
    # Extract recipes with filtering (matching original logic)
    skip_subgroup = [
        'logistic-network',
        'defensive-structure',
        'space-related',
        'train-transport',
        'turret',
        'equipment',
        'display-panel',
        'circuit-network',
        'defensive-structure',
        'military-equipment',
        'parameters',
        'utility-equipment',
        'spawnables',
        'other'
    ]
    
    skip_names = [
        "module",
        "equipment",
        "turret",
        "display-panel",
        "small-lamp",
        "armor",
        "gun",
        "magazine",
        "concrete",
        "capsule",
        "bomb",
        "shell",
        "flamethrower",
        "robot",
        "spidertron",
        "roboport",
        "tank",
        "wagon",
        "combinator",
        "locomotive",
        "rail",
        "land-mine",
        "grenade",
        "train",
        'power-switch',
        'programmable-speaker',
        "barrel"
    ]
    
    recipes = []
    for k, item in data.get("recipe", {}).items():
        if isinstance(item, dict):
            if item.get("hidden"):
                continue
            if item.get("subgroup") in skip_subgroup:
                continue
            if any(skip_name in item.get("name", k) for skip_name in skip_names):
                continue
            if "place_result" in item:
                continue
            recipes.append(item.get("name", k))
    
    # Extract resource entities (trees, rocks, etc.)
    resource_entities = []
    for category in ["tree", "simple-entity"]:
        resource_entities.extend(data.get(category, {}).keys())
    
    # Extract resource tiles
    resource_tiles = list(data.get("resource", {}).keys())
    
    # Extract placeable entities with filtering (matching original logic)
    keep = {
        'accumulator',
        'assembling-machine',
        'beacon',
        'boiler',
        'burner-generator',
        'container',
        'electric-pole',
        'furnace',
        'gate',
        'generator',
        'heat-interface',
        'heat-pipe',
        'inserter',
        'lab',
        'lane-splitter',
        'mining-drill',
        'offshore-pump',
        'pipe',
        'pipe-to-ground',
        'pump',
        'radar',
        'reactor',
        'rocket-silo',
        'solar-panel',
        'splitter',
        'transport-belt',
        'underground-belt',
        'wall'
    }
    
    skip_kk = ['crash-site-', 'factorio-logo-', 'bottomless-chest']
    
    flat_proto = {}
    for k, v in data.items():
        if k not in keep:
            continue
        if not isinstance(v, dict):
            continue
        for kk, vv in v.items():
            if any(skip in kk for skip in skip_kk):
                continue
            # Use entity name as key to deduplicate
            flat_proto[kk] = vv
    
    placeable_entities = sorted(set(flat_proto.keys()))  # Deduplicate using set
    
    return {
        "recipes": sorted(set(recipes)),  # Deduplicate
        "resource_entities": sorted(set(resource_entities)),  # Deduplicate
        "resource_tiles": sorted(set(resource_tiles)),  # Deduplicate
        "placeable_entities": placeable_entities,  # Already deduplicated
    }


def _type_exists(con: duckdb.DuckDBPyConnection, type_name: str) -> bool:
    """Check if a type exists in the database."""
    try:
        result = con.execute(
            "SELECT type_name FROM duckdb_types() WHERE type_name = ?",
            [type_name]
        ).fetchone()
        return result is not None
    except:
        return False


def _create_type_if_not_exists(con: duckdb.DuckDBPyConnection, type_name: str, create_sql: str) -> None:
    """Create a type only if it doesn't already exist."""
    if not _type_exists(con, type_name):
        try:
            con.execute(create_sql)
        except Exception:
            # If creation fails for any reason, ignore
            # (type might have been created by another connection)
            pass


def create_schema(con: duckdb.DuckDBPyConnection, dump_file: str = "factorio-data-dump.json", prototype_api_file: Optional[str] = None) -> None:
    """
    Create the complete schema with ENUMs and all tables.
    
    Args:
        con: DuckDB connection
        dump_file: Path to Factorio prototype data dump JSON file
        prototype_api_file: Optional path to prototype-api.json file
    """
    # Install and load extensions (ignore errors if already installed)
    try:
        con.execute("INSTALL spatial;")
        con.execute("LOAD spatial;")
    except:
        pass
    try:
        con.execute("INSTALL json;")
        con.execute("LOAD json;")
    except:
        pass
    
    # Extract enum values
    enums = _extract_enums_from_prototypes(dump_file, prototype_api_file)
    direction_enum = _get_direction_enum(prototype_api_file)
    status_enum = _get_status_enum(prototype_api_file)
    
    # Create ENUM types (only if they don't exist)
    if enums["recipes"]:
        recipes_str = "(" + ", ".join([f"'{r}'" for r in enums["recipes"]]) + ")"
        _create_type_if_not_exists(con, "recipe", f"CREATE TYPE recipe AS ENUM {recipes_str};")
    else:
        _create_type_if_not_exists(con, "recipe", "CREATE TYPE recipe AS ENUM ('none');")
    
    if enums["resource_entities"]:
        resource_entities_str = "(" + ", ".join([f"'{e}'" for e in enums["resource_entities"]]) + ")"
        _create_type_if_not_exists(con, "resource_entity", f"CREATE TYPE resource_entity AS ENUM {resource_entities_str};")
    else:
        _create_type_if_not_exists(con, "resource_entity", "CREATE TYPE resource_entity AS ENUM ('none');")
    
    if enums["resource_tiles"]:
        resource_tiles_str = "(" + ", ".join([f"'{t}'" for t in enums["resource_tiles"]]) + ")"
        _create_type_if_not_exists(con, "resource_tile", f"CREATE TYPE resource_tile AS ENUM {resource_tiles_str};")
    else:
        _create_type_if_not_exists(con, "resource_tile", "CREATE TYPE resource_tile AS ENUM ('none');")
    
    if enums["placeable_entities"]:
        placeable_entities_str = "(" + ", ".join([f"'{e}'" for e in enums["placeable_entities"]]) + ")"
        _create_type_if_not_exists(con, "placeable_entity", f"CREATE TYPE placeable_entity AS ENUM {placeable_entities_str};")
    else:
        _create_type_if_not_exists(con, "placeable_entity", "CREATE TYPE placeable_entity AS ENUM ('none');")
    
    direction_str = "(" + ", ".join([f"'{d}'" for d in direction_enum]) + ")"
    _create_type_if_not_exists(con, "direction", f"CREATE TYPE direction AS ENUM {direction_str};")
    
    status_str = "(" + ", ".join([f"'{s}'" for s in status_enum]) + ")"
    _create_type_if_not_exists(con, "status", f"CREATE TYPE status AS ENUM {status_str};")
    
    # Create STRUCT types
    _create_type_if_not_exists(con, "chunk_id", "CREATE TYPE chunk_id AS STRUCT(x INTEGER, y INTEGER);")
    _create_type_if_not_exists(con, "map_position", "CREATE TYPE map_position AS STRUCT(x DOUBLE, y DOUBLE);")
    
    # Create base tables
    con.execute("""
        CREATE TABLE IF NOT EXISTS water_tile (
            entity_key VARCHAR PRIMARY KEY,
            type VARCHAR NOT NULL DEFAULT 'water-tile',
            position map_position NOT NULL
        );
    """)
    
    con.execute("""
        CREATE TABLE IF NOT EXISTS resource_tile (
            entity_key VARCHAR PRIMARY KEY,
            name resource_tile NOT NULL,
            position map_position NOT NULL,
            amount INTEGER
        );
    """)
    
    con.execute("""
        CREATE TABLE IF NOT EXISTS resource_entity (
            entity_key VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            type VARCHAR NOT NULL,
            position map_position NOT NULL,
            bbox GEOMETRY
        );
    """)
    
    con.execute("""
        CREATE TABLE IF NOT EXISTS map_entity (
            entity_key VARCHAR PRIMARY KEY,
            position map_position NOT NULL,
            entity_name placeable_entity NOT NULL,
            bbox GEOMETRY NOT NULL,
            electric_network_id INTEGER
        );
    """)
    
    # Note: entity_status table is defined but not used for persistence.
    # Status is loaded on-the-fly from status files into temp_entity_status table.
    # Use entity_status_latest view to query current status.
    con.execute("""
        CREATE TABLE IF NOT EXISTS entity_status (
            entity_key VARCHAR PRIMARY KEY,
            tick INTEGER NOT NULL,
            status status NOT NULL,
            FOREIGN KEY (entity_key) REFERENCES map_entity(entity_key)
        );
    """)
    
    # Component tables
    con.execute("""
        CREATE TABLE IF NOT EXISTS inserter (
            entity_key VARCHAR PRIMARY KEY,
            direction direction NOT NULL,
            output STRUCT(position map_position, entity_key VARCHAR),
            input STRUCT(position map_position, entity_key VARCHAR),
            FOREIGN KEY (entity_key) REFERENCES map_entity(entity_key)
        );
    """)
    
    con.execute("""
        CREATE TABLE IF NOT EXISTS transport_belt (
            entity_key VARCHAR PRIMARY KEY,
            direction direction NOT NULL,
            output STRUCT(entity_key VARCHAR),
            input STRUCT(entity_key VARCHAR)[],
            FOREIGN KEY (entity_key) REFERENCES map_entity(entity_key)
        );
    """)
    
    con.execute("""
        CREATE TABLE IF NOT EXISTS electric_pole (
            entity_key VARCHAR PRIMARY KEY,
            supply_area GEOMETRY,
            connected_poles VARCHAR[],
            FOREIGN KEY (entity_key) REFERENCES map_entity(entity_key)
        );
    """)
    
    con.execute("""
        CREATE TABLE IF NOT EXISTS mining_drill (
            entity_key VARCHAR PRIMARY KEY,
            direction direction NOT NULL,
            mining_area GEOMETRY,
            output STRUCT(position map_position, entity_key VARCHAR),
            FOREIGN KEY (entity_key) REFERENCES map_entity(entity_key)
        );
    """)
    
    con.execute("""
        CREATE TABLE IF NOT EXISTS pumpjack (
            entity_key VARCHAR PRIMARY KEY,
            output STRUCT(position map_position, entity_key VARCHAR)[],
            FOREIGN KEY (entity_key) REFERENCES map_entity(entity_key)
        );
    """)
    
    con.execute("""
        CREATE TABLE IF NOT EXISTS assemblers (
            entity_key VARCHAR PRIMARY KEY,
            recipe recipe,
            FOREIGN KEY (entity_key) REFERENCES map_entity(entity_key)
        );
    """)
    
    # Patch tables
    con.execute("""
        CREATE TABLE IF NOT EXISTS water_patch (
            patch_id INTEGER PRIMARY KEY,
            geom GEOMETRY,
            tile_count INTEGER,
            centroid POINT_2D,
            tiles VARCHAR[]
        );
    """)
    
    con.execute("""
        CREATE TABLE IF NOT EXISTS resource_patch (
            patch_id INTEGER PRIMARY KEY,
            resource_name resource_tile NOT NULL,
            geom GEOMETRY,
            tile_count INTEGER,
            total_amount INTEGER,
            centroid POINT_2D,
            tiles VARCHAR[]
        );
    """)
    
    # Belt network tables
    con.execute("""
        CREATE TABLE IF NOT EXISTS belt_line (
            line_id INTEGER PRIMARY KEY,
            geom GEOMETRY,
            line_segments GEOMETRY,
            belts VARCHAR[]
        );
    """)
    
    con.execute("""
        CREATE TABLE IF NOT EXISTS belt_line_segment (
            segment_id INTEGER PRIMARY KEY,
            line_id INTEGER,
            segment_order INTEGER,
            geom GEOMETRY,
            line GEOMETRY,
            belts VARCHAR[],
            upstream_segments INTEGER[],
            downstream_segments INTEGER[],
            start_entity VARCHAR,
            end_entity VARCHAR,
            FOREIGN KEY (line_id) REFERENCES belt_line(line_id),
            FOREIGN KEY (start_entity) REFERENCES map_entity(entity_key),
            FOREIGN KEY (end_entity) REFERENCES map_entity(entity_key)
        );
    """)
    
    # Create indexes
    # Note: Cannot index on STRUCT types (position), only on scalar types or GEOMETRY with RTREE
    
    # Index on scalar columns
    con.execute("CREATE INDEX IF NOT EXISTS idx_resource_tile_name ON resource_tile(name);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_map_entity_name ON map_entity(entity_name);")
    
    # Spatial indexes on GEOMETRY columns using RTREE
    con.execute("CREATE INDEX IF NOT EXISTS idx_resource_entity_bbox ON resource_entity USING RTREE (bbox);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_map_entity_bbox ON map_entity USING RTREE (bbox);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_electric_pole_supply_area ON electric_pole USING RTREE (supply_area);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_mining_drill_mining_area ON mining_drill USING RTREE (mining_area);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_water_patch_geom ON water_patch USING RTREE (geom);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_resource_patch_geom ON resource_patch USING RTREE (geom);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_belt_line_geom ON belt_line USING RTREE (geom);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_belt_line_segment_geom ON belt_line_segment USING RTREE (geom);")


def connect(db_path: Optional[Path] = None) -> duckdb.DuckDBPyConnection:
    """
    Connect to the FactoryVerse DuckDB database, creating it if needed.

    Args:
        db_path: Optional explicit path to the DuckDB database file. If not
                 provided, DEFAULT_DB_FILENAME is created in CWD.
    """
    if db_path is None:
        db_path = Path(DEFAULT_DB_FILENAME)
    else:
        db_path = Path(db_path)

    con = duckdb.connect(str(db_path))
    return con


def init_schema(con: duckdb.DuckDBPyConnection, dump_file: str = "factorio-data-dump.json", prototype_api_file: Optional[str] = None) -> None:
    """
    Initialize the schema. This is a wrapper around create_schema for backward compatibility.
    
    Args:
        con: DuckDB connection
        dump_file: Path to Factorio prototype data dump JSON file
        prototype_api_file: Optional path to prototype-api.json file for defines
    """
    create_schema(con, dump_file, prototype_api_file)


__all__ = [
    "DEFAULT_DB_FILENAME",
    "connect",
    "create_schema",
    "init_schema",
]
