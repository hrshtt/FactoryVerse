"""Database connection and schema management.

Single responsibility: DuckDB connection lifecycle and schema creation.
Does NOT load data or handle queries - those are separate modules.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, List

import duckdb

logger = logging.getLogger(__name__)


class SnapshotDatabase:
    """Manages DuckDB connection and schema for snapshot data.

    Responsibilities:
    - Create/connect to database
    - Initialize schema (tables, indexes, types)
    - Reset data
    - Install extensions

    Does NOT:
    - Load data (see loader.py)
    - Execute queries (see query.py)
    - Handle sync (see sync.py)
    """

    def __init__(self, db_path: Optional[Path] = None):
        """Create or connect to database.

        Args:
            db_path: Path for persistent DB. None = in-memory.
        """
        self._path = db_path
        self._connection: Optional[duckdb.DuckDBPyConnection] = None
        self._schema_created = False

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Get active connection, creating if needed."""
        if self._connection is None:
            self._connection = self._create_connection()
        return self._connection

    @property
    def is_connected(self) -> bool:
        """True if connection is active."""
        return self._connection is not None

    def _create_connection(self) -> duckdb.DuckDBPyConnection:
        """Create connection with extensions loaded."""
        path = str(self._path) if self._path else ":memory:"
        logger.info(f"Connecting to DuckDB: {path}")

        con = duckdb.connect(path)

        # Install and load extensions
        try:
            con.execute("INSTALL spatial;")
            con.execute("LOAD spatial;")
        except Exception:
            pass  # Already installed

        try:
            con.execute("INSTALL json;")
            con.execute("LOAD json;")
        except Exception:
            pass  # Already installed

        return con

    def ensure_schema(self) -> None:
        """Create schema if not exists.

        Idempotent - safe to call multiple times.
        """
        if self._schema_created:
            return

        con = self.connection
        self._create_types(con)
        self._create_tables(con)
        self._create_indexes(con)
        self._schema_created = True
        logger.info("Schema created successfully")

    def _create_types(self, con: duckdb.DuckDBPyConnection) -> None:
        """Create custom types."""
        # Use simple VARCHAR for flexibility - avoid ENUM complexity
        # Struct types for positions
        self._exec_safe(
            con, "CREATE TYPE IF NOT EXISTS map_position AS STRUCT(x DOUBLE, y DOUBLE);"
        )
        self._exec_safe(
            con, "CREATE TYPE IF NOT EXISTS chunk_id AS STRUCT(x INTEGER, y INTEGER);"
        )

    def _create_tables(self, con: duckdb.DuckDBPyConnection) -> None:
        """Create all tables."""
        # Core entity table
        con.execute("""
            CREATE TABLE IF NOT EXISTS map_entity (
                entity_key VARCHAR PRIMARY KEY,
                entity_name VARCHAR NOT NULL,
                position_x DOUBLE NOT NULL,
                position_y DOUBLE NOT NULL,
                chunk_x INTEGER NOT NULL,
                chunk_y INTEGER NOT NULL,
                direction VARCHAR,
                bbox_min_x DOUBLE,
                bbox_min_y DOUBLE,
                bbox_max_x DOUBLE,
                bbox_max_y DOUBLE,
                electric_network_id INTEGER,
                -- Builder metadata (who placed this entity)
                agent_id INTEGER,
                player_id INTEGER,
                label VARCHAR,
                placed_tick INTEGER,
                -- Raw entity data for full reconstruction
                raw_data VARCHAR
            );
        """)

        # Ghost table (entities with is_ghost=true behavior)
        con.execute("""
            CREATE TABLE IF NOT EXISTS ghost (
                entity_key VARCHAR PRIMARY KEY,
                ghost_name VARCHAR NOT NULL,
                position_x DOUBLE NOT NULL,
                position_y DOUBLE NOT NULL,
                chunk_x INTEGER NOT NULL,
                chunk_y INTEGER NOT NULL,
                direction VARCHAR,
                placed_tick INTEGER,
                placed_by VARCHAR,
                label VARCHAR,
                raw_data VARCHAR
            );
        """)

        # Resource tiles (ores)
        con.execute("""
            CREATE TABLE IF NOT EXISTS resource_tile (
                entity_key VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                position_x DOUBLE NOT NULL,
                position_y DOUBLE NOT NULL,
                chunk_x INTEGER NOT NULL,
                chunk_y INTEGER NOT NULL,
                amount INTEGER
            );
        """)

        # Water tiles
        con.execute("""
            CREATE TABLE IF NOT EXISTS water_tile (
                entity_key VARCHAR PRIMARY KEY,
                position_x DOUBLE NOT NULL,
                position_y DOUBLE NOT NULL,
                chunk_x INTEGER NOT NULL,
                chunk_y INTEGER NOT NULL
            );
        """)

        # Resource entities (trees, rocks)
        con.execute("""
            CREATE TABLE IF NOT EXISTS resource_entity (
                entity_key VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                entity_type VARCHAR NOT NULL,
                position_x DOUBLE NOT NULL,
                position_y DOUBLE NOT NULL,
                chunk_x INTEGER NOT NULL,
                chunk_y INTEGER NOT NULL,
                raw_data VARCHAR
            );
        """)

        # Sync state table (for tracking sequence)
        con.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                key VARCHAR PRIMARY KEY,
                value INTEGER NOT NULL
            );
        """)

        # Component tables (inserter, belt, drill, etc.)
        con.execute("""
            CREATE TABLE IF NOT EXISTS inserter (
                entity_key VARCHAR PRIMARY KEY,
                direction VARCHAR NOT NULL,
                pickup_position_x DOUBLE,
                pickup_position_y DOUBLE,
                drop_position_x DOUBLE,
                drop_position_y DOUBLE,
                FOREIGN KEY (entity_key) REFERENCES map_entity(entity_key)
            );
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS transport_belt (
                entity_key VARCHAR PRIMARY KEY,
                direction VARCHAR NOT NULL,
                belt_speed DOUBLE,
                FOREIGN KEY (entity_key) REFERENCES map_entity(entity_key)
            );
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS mining_drill (
                entity_key VARCHAR PRIMARY KEY,
                direction VARCHAR NOT NULL,
                mining_target VARCHAR,
                FOREIGN KEY (entity_key) REFERENCES map_entity(entity_key)
            );
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS assembler (
                entity_key VARCHAR PRIMARY KEY,
                recipe VARCHAR,
                crafting_speed DOUBLE,
                FOREIGN KEY (entity_key) REFERENCES map_entity(entity_key)
            );
        """)

    def _create_indexes(self, con: duckdb.DuckDBPyConnection) -> None:
        """Create indexes for common queries."""
        # Entity indexes
        self._exec_safe(
            con,
            "CREATE INDEX IF NOT EXISTS idx_map_entity_name ON map_entity(entity_name);",
        )
        self._exec_safe(
            con,
            "CREATE INDEX IF NOT EXISTS idx_map_entity_chunk ON map_entity(chunk_x, chunk_y);",
        )
        self._exec_safe(
            con,
            "CREATE INDEX IF NOT EXISTS idx_map_entity_pos ON map_entity(position_x, position_y);",
        )

        # Ghost indexes
        self._exec_safe(
            con, "CREATE INDEX IF NOT EXISTS idx_ghost_name ON ghost(ghost_name);"
        )
        self._exec_safe(
            con,
            "CREATE INDEX IF NOT EXISTS idx_ghost_chunk ON ghost(chunk_x, chunk_y);",
        )

        # Resource indexes
        self._exec_safe(
            con,
            "CREATE INDEX IF NOT EXISTS idx_resource_tile_name ON resource_tile(name);",
        )
        self._exec_safe(
            con,
            "CREATE INDEX IF NOT EXISTS idx_resource_tile_chunk ON resource_tile(chunk_x, chunk_y);",
        )
        self._exec_safe(
            con,
            "CREATE INDEX IF NOT EXISTS idx_resource_entity_chunk ON resource_entity(chunk_x, chunk_y);",
        )

    def _exec_safe(self, con: duckdb.DuckDBPyConnection, sql: str) -> None:
        """Execute SQL, ignoring errors (for IF NOT EXISTS patterns)."""
        try:
            con.execute(sql)
        except Exception as e:
            logger.debug(f"Safe exec ignored error: {e}")

    def reset(self) -> None:
        """Clear all data, keep schema.

        Use this for rebuild operations.
        """
        con = self.connection
        tables = [
            "map_entity",
            "ghost",
            "resource_tile",
            "water_tile",
            "resource_entity",
            "sync_state",
            "inserter",
            "transport_belt",
            "mining_drill",
            "assembler",
        ]
        for table in tables:
            try:
                con.execute(f"DELETE FROM {table};")
            except Exception:
                pass  # Table may not exist

        logger.info("Database reset complete")

    def get_last_sequence(self) -> int:
        """Get last processed sequence from sync_state table."""
        try:
            result = self.connection.execute(
                "SELECT value FROM sync_state WHERE key = 'last_sequence'"
            ).fetchone()
            return result[0] if result else 0
        except Exception:
            return 0

    def set_last_sequence(self, sequence: int) -> None:
        """Update last processed sequence in sync_state table."""
        self.connection.execute(
            """
            INSERT OR REPLACE INTO sync_state (key, value) 
            VALUES ('last_sequence', ?)
            """,
            [sequence],
        )

    def close(self) -> None:
        """Close connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
            self._schema_created = False
            logger.info("Database connection closed")


__all__ = ["SnapshotDatabase"]
