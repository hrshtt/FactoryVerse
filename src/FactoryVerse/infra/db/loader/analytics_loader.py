"""
Load analytics tables: power statistics, agent production statistics.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from .utils import normalize_snapshot_dir, load_jsonl_file


def load_power_statistics(
    con: duckdb.DuckDBPyConnection, snapshot_dir: Path
) -> None:
    """
    Load global power statistics.
    
    Args:
        con: DuckDB connection
        snapshot_dir: Path to snapshot directory (will be normalized)
    """
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    power_file = snapshot_dir / "global_power_statistics.jsonl"
    
    # Check if table exists (may not be in schema)
    try:
        con.execute("DELETE FROM power_statistics;")
    except:
        # Table doesn't exist, skip
        return
    
    entries = load_jsonl_file(power_file)
    if not entries:
        return
    
    rows = []
    for entry in entries:
        stats = entry.get("statistics") or {}
        tick = int(entry.get("tick", 0))
        rows.append((
            tick,
            json.dumps(stats.get("input", {})),
            json.dumps(stats.get("output", {})),
            json.dumps(stats.get("storage", {})),
        ))
    
    if rows:
        con.executemany(
            """
            INSERT INTO power_statistics (tick, input, output, storage)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )


def load_agent_production_statistics(
    con: duckdb.DuckDBPyConnection, snapshot_dir: Path
) -> None:
    """
    Load per-agent production statistics.
    
    Args:
        con: DuckDB connection
        snapshot_dir: Path to snapshot directory (will be normalized)
    """
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    
    # Check if table exists (may not be in schema)
    try:
        con.execute("DELETE FROM agent_production_statistics;")
    except:
        # Table doesn't exist, skip
        return
    
    rows = []
    for path in snapshot_dir.glob("*/production_statistics.jsonl"):
        try:
            agent_id = int(path.parent.name)
        except ValueError:
            continue
        entries = load_jsonl_file(path)
        for entry in entries:
            tick = int(entry.get("tick", 0))
            stats = entry.get("statistics") or {}
            rows.append((agent_id, tick, json.dumps(stats)))
    
    if rows:
        con.executemany(
            """
            INSERT INTO agent_production_statistics (agent_id, tick, statistics)
            VALUES (?, ?, ?)
            """,
            rows,
        )


def load_analytics(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """
    Load all analytics tables.
    
    Args:
        con: DuckDB connection
        snapshot_dir: Path to snapshot directory (will be normalized)
    """
    load_power_statistics(con, snapshot_dir)
    load_agent_production_statistics(con, snapshot_dir)

