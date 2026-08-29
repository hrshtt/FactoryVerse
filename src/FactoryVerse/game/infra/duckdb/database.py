"""Database connection and schema management.

Single responsibility: DuckDB connection lifecycle and schema creation.
Does NOT load data or handle queries - those are separate modules.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import duckdb

from .schema_definitions import (
    ANALYTICS_TABLES,
    COMPONENT_TABLES,
    CORE_TABLES,
    TABLE_BY_NAME,
)

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
        """Create all tables from schema definitions."""
        from .schema_definitions import TableDefinition

        def _generate_create_table_sql(table: TableDefinition) -> str:
            """Generate CREATE TABLE SQL from a TableDefinition."""
            column_defs = []
            for col in table.columns:
                col_def = f"{col.name} {col.type}"
                if not col.nullable:
                    col_def += " NOT NULL"
                if col.default:
                    col_def += f" DEFAULT {col.default}"
                column_defs.append(col_def)

            # Add primary key constraint
            if table.primary_key:
                pk_cols = ", ".join(table.primary_key)
                column_defs.append(f"PRIMARY KEY ({pk_cols})")

            # Add foreign key constraints
            if table.foreign_keys:
                # Group foreign keys by target table
                # All FKs in the list should reference the same table
                fk_table = table.foreign_keys[0][1]  # Get target table name
                ref_table = TABLE_BY_NAME.get(fk_table)
                
                if ref_table and ref_table.primary_key:
                    # Build mapping from referenced column to local column
                    ref_to_local = {ref_col: local_col for local_col, _, ref_col in table.foreign_keys}
                    # Order columns to match the referenced primary key order
                    local_cols = [ref_to_local[ref_pk_col] for ref_pk_col in ref_table.primary_key if ref_pk_col in ref_to_local]
                    ref_cols = [ref_pk_col for ref_pk_col in ref_table.primary_key if ref_pk_col in ref_to_local]
                    
                    if local_cols:
                        local_cols_str = ", ".join(local_cols)
                        ref_cols_str = ", ".join(ref_cols)
                        fk_def = f"FOREIGN KEY ({local_cols_str}) REFERENCES {fk_table}({ref_cols_str})"
                        column_defs.append(fk_def)
                else:
                    # Fallback: single column FK
                    col_name, _, ref_col = table.foreign_keys[0]
                    fk_def = f"FOREIGN KEY ({col_name}) REFERENCES {fk_table}({ref_col})"
                    column_defs.append(fk_def)

            columns_sql = ",\n                ".join(column_defs)
            return f"""CREATE TABLE IF NOT EXISTS {table.name} (
                {columns_sql}
            );"""

        # Every created group has a boot/live writer. Agent analytics are
        # replayed by SnapshotLoader and reduced live by SyncService.
        all_tables = CORE_TABLES + COMPONENT_TABLES + ANALYTICS_TABLES

        # Also create sync_state table (not in schema_definitions, but needed)
        con.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                key VARCHAR PRIMARY KEY,
                value INTEGER NOT NULL
            );
        """)

        for table in all_tables:
            sql = _generate_create_table_sql(table)
            con.execute(sql)

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
        # Get table names from schema definitions
        tables = [
            table.name
            for table in CORE_TABLES + COMPONENT_TABLES + ANALYTICS_TABLES
        ] + ["sync_state"]
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
