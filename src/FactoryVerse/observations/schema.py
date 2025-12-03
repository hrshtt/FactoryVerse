"""Database schema definitions for MapView.

Defines all spatial tables, state tables, and materialized views
for multi-scale spatial queries.
"""

import duckdb
from typing import Optional


def create_spatial_tables(db: duckdb.DuckDBPyConnection):
    """Create all spatial tables (rows in space)."""
    
    # Point entities (assemblers, inserters, furnaces, etc.)
    db.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            unit_number BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            position GEOMETRY NOT NULL,
            direction INTEGER,
            recipe TEXT,
            power_network_id BIGINT,
            chunk_x INTEGER NOT NULL,
            chunk_y INTEGER NOT NULL,
            tick BIGINT,
            -- Denormalized coordinates for simple queries (computed on insert)
            position_x REAL,
            position_y REAL,
            -- Full entity data for complex queries
            data JSON
        )
    """)
    
    # Belt network (linestring - spatial lines)
    db.execute("""
        CREATE TABLE IF NOT EXISTS belts (
            unit_number BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            line GEOMETRY NOT NULL,
            direction INTEGER,
            chunk_x INTEGER NOT NULL,
            chunk_y INTEGER NOT NULL,
            tick BIGINT,
            -- Connection info for network analysis
            upstream_units TEXT,  -- JSON array of unit numbers
            downstream_units TEXT,  -- JSON array of unit numbers
            data JSON
        )
    """)
    
    # Pipe network (linestring - spatial lines)
    db.execute("""
        CREATE TABLE IF NOT EXISTS pipes (
            unit_number BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            line GEOMETRY NOT NULL,
            chunk_x INTEGER NOT NULL,
            chunk_y INTEGER NOT NULL,
            tick BIGINT,
            -- Connection info
            connected_units TEXT,  -- JSON array of unit numbers
            data JSON
        )
    """)
    
    # Resources (points)
    db.execute("""
        CREATE TABLE IF NOT EXISTS resources (
            id BIGINT PRIMARY KEY,
            kind TEXT NOT NULL,
            position GEOMETRY NOT NULL,
            amount REAL NOT NULL,
            chunk_x INTEGER NOT NULL,
            chunk_y INTEGER NOT NULL,
            tick BIGINT,
            -- Denormalized coordinates (computed on insert)
            x INTEGER,
            y INTEGER
        )
    """)
    
    # Water (polygons for tile coverage)
    db.execute("""
        CREATE TABLE IF NOT EXISTS water (
            id BIGINT PRIMARY KEY,
            tile GEOMETRY NOT NULL,
            chunk_x INTEGER NOT NULL,
            chunk_y INTEGER NOT NULL,
            tick BIGINT,
            -- Denormalized center point (computed on insert)
            x INTEGER,
            y INTEGER
        )
    """)
    
    # Trees (with bounding box)
    db.execute("""
        CREATE TABLE IF NOT EXISTS trees (
            id BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            position GEOMETRY NOT NULL,
            bbox GEOMETRY NOT NULL,
            chunk_x INTEGER NOT NULL,
            chunk_y INTEGER NOT NULL,
            tick BIGINT,
            -- Denormalized coordinates (computed on insert)
            position_x REAL,
            position_y REAL
        )
    """)
    
    # Create indexes
    # Note: DuckDB's spatial extension may automatically index GEOMETRY columns
    # We create regular indexes for chunk coordinates and types for fast filtering
    db.execute("CREATE INDEX IF NOT EXISTS idx_entities_chunk ON entities(chunk_x, chunk_y)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_entities_position_coords ON entities(position_x, position_y)")
    
    db.execute("CREATE INDEX IF NOT EXISTS idx_belts_chunk ON belts(chunk_x, chunk_y)")
    
    db.execute("CREATE INDEX IF NOT EXISTS idx_pipes_chunk ON pipes(chunk_x, chunk_y)")
    
    db.execute("CREATE INDEX IF NOT EXISTS idx_resources_chunk ON resources(chunk_x, chunk_y)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_resources_coords ON resources(x, y)")
    
    db.execute("CREATE INDEX IF NOT EXISTS idx_water_chunk ON water(chunk_x, chunk_y)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_water_coords ON water(x, y)")
    
    db.execute("CREATE INDEX IF NOT EXISTS idx_trees_chunk ON trees(chunk_x, chunk_y)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_trees_position_coords ON trees(position_x, position_y)")


def create_state_tables(db: duckdb.DuckDBPyConnection):
    """Create entity-specific state tables."""
    
    # Assembler state
    db.execute("""
        CREATE TABLE IF NOT EXISTS assembler_state (
            unit_number BIGINT PRIMARY KEY,
            status TEXT,
            status_reason TEXT,
            recipe TEXT,
            crafting_progress REAL,
            productivity_bonus REAL,
            speed_bonus REAL,
            tick BIGINT,
            FOREIGN KEY (unit_number) REFERENCES entities(unit_number)
        )
    """)
    
    # Belt throughput/state
    db.execute("""
        CREATE TABLE IF NOT EXISTS belt_state (
            unit_number BIGINT PRIMARY KEY,
            throughput REAL,
            saturation REAL,
            items_on_belt JSON,
            tick BIGINT,
            FOREIGN KEY (unit_number) REFERENCES belts(unit_number)
        )
    """)
    
    # Pipe flow/state
    db.execute("""
        CREATE TABLE IF NOT EXISTS pipe_state (
            unit_number BIGINT PRIMARY KEY,
            fluid_contents JSON,
            flow_rate REAL,
            pressure REAL,
            tick BIGINT,
            FOREIGN KEY (unit_number) REFERENCES pipes(unit_number)
        )
    """)
    
    # Power connection
    db.execute("""
        CREATE TABLE IF NOT EXISTS entity_power (
            unit_number BIGINT PRIMARY KEY,
            power_network_id BIGINT,
            consumption REAL,
            satisfaction REAL,
            tick BIGINT,
            FOREIGN KEY (unit_number) REFERENCES entities(unit_number)
        )
    """)
    
    # Indexes for state tables
    db.execute("CREATE INDEX IF NOT EXISTS idx_assembler_status ON assembler_state(status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_entity_power_network ON entity_power(power_network_id)")


def create_time_tables(db: duckdb.DuckDBPyConnection):
    """Create time-based tables (rows in time)."""
    
    # Power network statistics (time series)
    db.execute("""
        CREATE TABLE IF NOT EXISTS power_stats (
            tick BIGINT,
            network_id BIGINT,
            production REAL,
            consumption REAL,
            satisfaction REAL,
            accumulator_charge REAL,
            PRIMARY KEY (tick, network_id)
        )
    """)
    
    # Index for time queries
    db.execute("CREATE INDEX IF NOT EXISTS idx_power_stats_tick ON power_stats(tick)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_power_stats_network ON power_stats(network_id)")


def create_materialized_views(db: duckdb.DuckDBPyConnection):
    """Create materialized views for multi-scale aggregations."""
    
    # Area status (zoomed-out view)
    db.execute("""
        CREATE OR REPLACE VIEW area_status AS
        SELECT 
            ST_MakeEnvelope(
                FLOOR(e.position_x / 32) * 32,
                FLOOR(e.position_y / 32) * 32,
                (FLOOR(e.position_x / 32) + 1) * 32,
                (FLOOR(e.position_y / 32) + 1) * 32
            ) as area,
            COUNT(*) FILTER (WHERE a.status = 'output_full') as output_full_count,
            COUNT(*) FILTER (WHERE a.status = 'no_power') as no_power_count,
            COUNT(*) FILTER (WHERE a.status = 'no_ingredients') as no_ingredients_count,
            COUNT(*) FILTER (WHERE a.status = 'working') as working_count,
            AVG(bs.throughput) as avg_belt_throughput,
            SUM(ep.consumption) as total_power_consumption,
            AVG(ep.satisfaction) as avg_power_satisfaction
        FROM entities e
        LEFT JOIN assembler_state a ON e.unit_number = a.unit_number
        LEFT JOIN belt_state bs ON e.unit_number = bs.unit_number
        LEFT JOIN entity_power ep ON e.unit_number = ep.unit_number
        GROUP BY area
    """)
    
    # Supply chain connections (for RCA)
    db.execute("""
        CREATE OR REPLACE VIEW supply_chain AS
        SELECT 
            e1.unit_number as from_entity,
            e2.unit_number as to_entity,
            ST_Distance(e1.position, e2.position) as distance,
            b.line as connection_path,
            b.unit_number as belt_unit
        FROM entities e1
        JOIN belts b ON JSON_EXTRACT(b.upstream_units, '$') LIKE '%' || e1.unit_number || '%'
        JOIN entities e2 ON JSON_EXTRACT(b.downstream_units, '$') LIKE '%' || e2.unit_number || '%'
    """)


def create_all_schema(db: duckdb.DuckDBPyConnection):
    """Create all tables and views."""
    # Install and load spatial extension deterministically before using GEOMETRY types
    try:
        db.execute("INSTALL spatial;")
        db.execute("LOAD spatial;")
    except Exception as e:
        # If loading spatial fails, surface the error clearly
        raise RuntimeError(f"Failed to load DuckDB spatial extension: {e}") from e

    create_spatial_tables(db)
    create_state_tables(db)
    create_time_tables(db)
    create_materialized_views(db)

