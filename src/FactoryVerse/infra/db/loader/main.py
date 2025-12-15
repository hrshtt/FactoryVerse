"""
Main entry point for loading snapshot data into DuckDB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb

from .base_loader import load_base_tables, load_ghosts
from .component_loader import load_component_tables
from .derived_loader import load_derived_tables
from .analytics_loader import load_analytics
from ..duckdb_schema import create_schema
from .utils import normalize_snapshot_dir


def load_all(
    con: duckdb.DuckDBPyConnection,
    snapshot_dir: Path,
    dump_file: str = "factorio-data-dump.json",
    prototype_api_file: Optional[str] = None,
    *,
    include_base: bool = True,
    include_components: bool = True,
    include_derived: bool = True,
    include_ghosts: bool = True,
    include_analytics: bool = True,
    replay_updates: bool = True,
) -> None:
    """
    Load all snapshot data into DuckDB.
    
    Args:
        con: DuckDB connection (can be in-memory or file-based)
        snapshot_dir: Path to snapshot directory or script-output root
        dump_file: Path to Factorio prototype data dump JSON file
        prototype_api_file: Optional path to prototype-api.json file
        include_base: Load base tables (water, resources, entities)
        include_components: Load component tables (inserters, belts, etc.)
        include_derived: Load derived tables (patches, belt networks)
        include_ghosts: Load ghost tables
        include_analytics: Load analytics tables (power, agent stats)
        replay_updates: If True, replay operations logs (entities_updates.jsonl, ghosts-updates.jsonl)
    """
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    
    # Ensure schema exists
    create_schema(con, dump_file, prototype_api_file)
    
    if include_base:
        print("=" * 60)
        print("Loading base tables...")
        print("=" * 60)
        load_base_tables(con, snapshot_dir)
    
    if include_ghosts:
        print("\n" + "=" * 60)
        print("Loading ghosts...")
        print("=" * 60)
        load_ghosts(con, snapshot_dir, replay_updates=replay_updates)
    
    if include_components:
        print("\n" + "=" * 60)
        print("Loading component tables...")
        print("=" * 60)
        load_component_tables(con, snapshot_dir, replay_updates=replay_updates)
    
    if include_derived:
        print("\n" + "=" * 60)
        print("Loading derived tables...")
        print("=" * 60)
        load_derived_tables(con, snapshot_dir, dump_file)
    
    if include_analytics:
        print("\n" + "=" * 60)
        print("Loading analytics...")
        print("=" * 60)
        load_analytics(con, snapshot_dir)
    
    print("\n" + "=" * 60)
    print("Loading complete!")
    print("=" * 60)


# Convenience function for file-based DB
def load_all_to_file(
    snapshot_dir: Path,
    db_path: Optional[Path] = None,
    dump_file: str = "factorio-data-dump.json",
    prototype_api_file: Optional[str] = None,
    **kwargs,
) -> duckdb.DuckDBPyConnection:
    """
    Convenience function that creates a file-based connection and loads data.
    
    For in-memory DBs, use load_all() directly with duckdb.connect(":memory:").
    
    Args:
        snapshot_dir: Path to snapshot directory or script-output root
        db_path: Optional path to DuckDB database file. If None, uses default.
        dump_file: Path to Factorio prototype data dump JSON file
        prototype_api_file: Optional path to prototype-api.json file
        **kwargs: Additional arguments passed to load_all()
    
    Returns:
        DuckDB connection
    """
    from ..duckdb_schema import connect
    
    con = connect(db_path)
    load_all(con, snapshot_dir, dump_file, prototype_api_file, **kwargs)
    return con


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python -m src.FactoryVerse.infra.db.loader.main <snapshot_dir> [db_path] [dump_file]")
        sys.exit(1)
    
    snapshot_dir = Path(sys.argv[1])
    db_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    dump_file = sys.argv[3] if len(sys.argv) > 3 else "factorio-data-dump.json"
    
    load_all_to_file(snapshot_dir, db_path, dump_file)
