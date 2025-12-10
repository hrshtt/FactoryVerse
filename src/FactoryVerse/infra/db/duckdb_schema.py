"""
DuckDB schema and initialization helpers for FactoryVerse map view + analytics.

This module is deliberately focused on **DDL and connection setup**. Ingestion
from snapshot files (entities/resources/power/production) is handled by
higher-level services that call into DuckDB using this schema.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb


DEFAULT_DB_FILENAME = "factoryverse-map.duckdb"


DDL_STATEMENTS = [
    # Core: enable spatial extension
    "INSTALL spatial;",
    "LOAD spatial;",
    # JSON for analytics statistics
    "INSTALL json;",
    "LOAD json;",
    # --- Base spatial layers -------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS water_layer (
        water_key    VARCHAR PRIMARY KEY,
        tile_name    VARCHAR NOT NULL,
        map_position GEOMETRY NOT NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_water_map_position
        ON water_layer USING RTREE (map_position);
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_layer (
        resource_key  VARCHAR PRIMARY KEY,
        resource_name VARCHAR NOT NULL,
        resource_type VARCHAR NOT NULL,
        map_position  GEOMETRY NOT NULL,
        yield         BIGINT NOT NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_resource_map_position
        ON resource_layer USING RTREE (map_position);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_resource_name
        ON resource_layer(resource_name);
    """,
    # Rocks / trees (non-grid resource entities)
    """
    CREATE TABLE IF NOT EXISTS resource_entities (
        entity_key   VARCHAR PRIMARY KEY,
        resource_name VARCHAR NOT NULL,
        resource_type VARCHAR NOT NULL,
        map_position  GEOMETRY NOT NULL,
        bounding_box  GEOMETRY NOT NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_resource_entities_pos
        ON resource_entities USING RTREE (map_position);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_resource_entities_bbox
        ON resource_entities USING RTREE (bounding_box);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_resource_entities_name
        ON resource_entities(resource_name);
    """,
    # --- Entity layer + components -------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS entity_layer (
        entity_key         VARCHAR PRIMARY KEY,
        entity_name        VARCHAR NOT NULL,
        entity_type        VARCHAR NOT NULL,
        force_name         VARCHAR,
        map_position       GEOMETRY NOT NULL,
        bounding_box       GEOMETRY NOT NULL,
        direction          SMALLINT,
        direction_name     VARCHAR,
        orientation        DOUBLE,
        electric_network_id INTEGER,
        recipe             VARCHAR
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_entity_position
        ON entity_layer USING RTREE (map_position);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_entity_bbox
        ON entity_layer USING RTREE (bounding_box);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_entity_name
        ON entity_layer(entity_name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_entity_type
        ON entity_layer(entity_type);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_entity_force
        ON entity_layer(force_name);
    """,
    # Transport belts (component mixin)
    """
    CREATE TABLE IF NOT EXISTS component_transport_belt (
        entity_key  VARCHAR PRIMARY KEY REFERENCES entity_layer(entity_key),
        entity_name VARCHAR NOT NULL,
        -- Nested belt state stored as JSON; typed views can be layered on top.
        belt_data   JSON
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_belt_name ON component_transport_belt(entity_name);",
    # Inserters
    """
    CREATE TABLE IF NOT EXISTS component_inserter (
        entity_key          VARCHAR PRIMARY KEY REFERENCES entity_layer(entity_key),
        entity_name         VARCHAR NOT NULL,
        electric_network_id INTEGER,
        -- Inserter pickup/drop positions & targets stored as JSON.
        inserter_data       JSON
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_inserter_name ON component_inserter(entity_name);",
    "CREATE INDEX IF NOT EXISTS idx_inserter_electric ON component_inserter(electric_network_id);",
    # Assemblers
    """
    CREATE TABLE IF NOT EXISTS component_assembler (
        entity_key          VARCHAR PRIMARY KEY REFERENCES entity_layer(entity_key),
        entity_name         VARCHAR NOT NULL,
        electric_network_id INTEGER
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_assembler_name ON component_assembler(entity_name);",
    "CREATE INDEX IF NOT EXISTS idx_assembler_electric ON component_assembler(electric_network_id);",
    # Furnaces
    """
    CREATE TABLE IF NOT EXISTS component_furnace (
        entity_key          VARCHAR PRIMARY KEY REFERENCES entity_layer(entity_key),
        entity_name         VARCHAR NOT NULL,
        electric_network_id INTEGER
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_furnace_name ON component_furnace(entity_name);",
    "CREATE INDEX IF NOT EXISTS idx_furnace_electric ON component_furnace(electric_network_id);",
    # Boilers
    """
    CREATE TABLE IF NOT EXISTS component_boiler (
        entity_key          VARCHAR PRIMARY KEY REFERENCES entity_layer(entity_key),
        entity_name         VARCHAR NOT NULL,
        electric_network_id INTEGER,
        energy_source_type  VARCHAR
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_boiler_name ON component_boiler(entity_name);",
    "CREATE INDEX IF NOT EXISTS idx_boiler_electric ON component_boiler(electric_network_id);",
    # Electric poles (spatial supply area)
    """
    CREATE TABLE IF NOT EXISTS component_electric_pole (
        entity_key          VARCHAR PRIMARY KEY REFERENCES entity_layer(entity_key),
        entity_name         VARCHAR NOT NULL,
        electric_network_id INTEGER NOT NULL,
        -- Neighbour pole keys as JSON array.
        connected_poles     JSON,
        supply_area         GEOMETRY
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_pole_network ON component_electric_pole(electric_network_id);",
    "CREATE INDEX IF NOT EXISTS idx_pole_name ON component_electric_pole(entity_name);",
    """
    CREATE INDEX IF NOT EXISTS idx_pole_supply_area
        ON component_electric_pole USING RTREE (supply_area);
    """,
    # Mining drills (spatial mining area)
    """
    CREATE TABLE IF NOT EXISTS component_mining_drill (
        entity_key          VARCHAR PRIMARY KEY REFERENCES entity_layer(entity_key),
        entity_name         VARCHAR NOT NULL,
        electric_network_id INTEGER,
        mining_area         GEOMETRY,
        resource_filter     VARCHAR
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_drill_name ON component_mining_drill(entity_name);",
    "CREATE INDEX IF NOT EXISTS idx_drill_electric ON component_mining_drill(electric_network_id);",
    """
    CREATE INDEX IF NOT EXISTS idx_drill_mining_area
        ON component_mining_drill USING RTREE (mining_area);
    """,
    # --- Analytics: power + production --------------------------------------
    """
    CREATE TABLE IF NOT EXISTS power_statistics (
        tick    BIGINT PRIMARY KEY,
        input   JSON,
        output  JSON,
        storage JSON
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_production_statistics (
        agent_id   BIGINT NOT NULL,
        tick       BIGINT NOT NULL,
        statistics JSON,
        PRIMARY KEY (agent_id, tick)
    );
    """,
]


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


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Apply all DDL statements to ensure schema exists."""
    for stmt in DDL_STATEMENTS:
        con.execute(stmt)


__all__ = [
    "DEFAULT_DB_FILENAME",
    "DDL_STATEMENTS",
    "connect",
    "init_schema",
]


