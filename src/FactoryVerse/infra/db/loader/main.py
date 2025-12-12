"""
Main entry point for loading snapshot data into DuckDB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb

from .base_loader import load_base_tables
from .component_loader import load_component_tables
from .derived_loader import load_derived_tables
from ..duckdb_schema import create_schema, connect


def load_all(
    snapshot_dir: Path,
    db_path: Optional[Path] = None,
    dump_file: str = "factorio-data-dump.json",
    prototype_api_file: Optional[str] = None,
    recreate_schema: bool = False,
) -> duckdb.DuckDBPyConnection:
    """
    Load all snapshot data into DuckDB.
    
    Args:
        snapshot_dir: Path to snapshot directory (e.g., script-output/factoryverse/snapshots)
        db_path: Optional path to DuckDB database file. If None, uses default.
        dump_file: Path to Factorio prototype data dump JSON file
        recreate_schema: If True, drop and recreate schema. If False, only create if missing.
    
    Returns:
        DuckDB connection
    """
    # Connect to database
    con = connect(db_path)
    
    # Create schema
    if recreate_schema:
        # Drop all tables (in reverse dependency order)
        tables = [
            "belt_line_segment",
            "belt_line",
            "resource_patch",
            "water_patch",
            "assemblers",
            "pumpjack",
            "mining_drill",
            "electric_pole",
            "transport_belt",
            "inserter",
            "entity_status",
            "map_entity",
            "resource_entity",
            "resource_tile",
            "water_tile",
        ]
        for table in tables:
            try:
                con.execute(f"DROP TABLE IF EXISTS {table};")
            except:
                pass
        
        # Drop types
        types = ["recipe", "resource_entity", "resource_tile", "placeable_entity", "direction", "status", "chunk_id", "map_position"]
        for type_name in types:
            try:
                con.execute(f"DROP TYPE IF EXISTS {type_name};")
            except:
                pass
    
    create_schema(con, dump_file, prototype_api_file)
    
    # Load data
    print("=" * 60)
    print("Loading base tables...")
    print("=" * 60)
    load_base_tables(con, snapshot_dir)
    
    print("\n" + "=" * 60)
    print("Loading component tables...")
    print("=" * 60)
    load_component_tables(con, snapshot_dir)
    
    print("\n" + "=" * 60)
    print("Loading derived tables...")
    print("=" * 60)
    load_derived_tables(con, snapshot_dir, dump_file)
    
    print("\n" + "=" * 60)
    print("Loading complete!")
    print("=" * 60)
    
    return con


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python -m src.FactoryVerse.infra.db.loader.main <snapshot_dir> [db_path] [dump_file]")
        sys.exit(1)
    
    snapshot_dir = Path(sys.argv[1])
    db_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    dump_file = sys.argv[3] if len(sys.argv) > 3 else "factorio-data-dump.json"
    
    load_all(snapshot_dir, db_path, dump_file, recreate_schema=True)

