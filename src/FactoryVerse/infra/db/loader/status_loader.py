"""
Status loader for entity status files.

Status files are written every 60 ticks and contain compressed status data:
Format: [entity_enum, status_enum, pos_x_int, pos_y_int] per line
- entity_enum: Index into ENTITY_NAME_ENUM (manually created in Entities.lua)
- status_enum: Index into defines.entity_status (from Factorio API)
- pos_x_int, pos_y_int: Position * 2 (since positions are multiples of 0.5)

Status is loaded on-the-fly and not persisted in DuckDB.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
from collections import defaultdict

import duckdb


# Entity name enum from Entities.lua - must match exactly
ENTITY_NAME_ENUM = {
    "accumulator": 0,
    "assembling-machine-1": 1,
    "assembling-machine-2": 2,
    "assembling-machine-3": 3,
    "beacon": 4,
    "big-electric-pole": 5,
    "blue-chest": 6,
    "boiler": 7,
    "bulk-inserter": 8,
    "burner-generator": 9,
    "burner-inserter": 10,
    "burner-mining-drill": 11,
    "centrifuge": 12,
    "chemical-plant": 13,
    "electric-furnace": 14,
    "electric-mining-drill": 15,
    "express-splitter": 16,
    "express-transport-belt": 17,
    "express-underground-belt": 18,
    "fast-inserter": 19,
    "fast-splitter": 20,
    "fast-transport-belt": 21,
    "fast-underground-belt": 22,
    "gate": 23,
    "heat-exchanger": 24,
    "heat-interface": 25,
    "heat-pipe": 26,
    "inserter": 27,
    "iron-chest": 28,
    "lab": 29,
    "lane-splitter": 30,
    "long-handed-inserter": 31,
    "medium-electric-pole": 32,
    "nuclear-reactor": 33,
    "offshore-pump": 34,
    "oil-refinery": 35,
    "pipe": 36,
    "pipe-to-ground": 37,
    "pump": 38,
    "pumpjack": 39,
    "radar": 40,
    "red-chest": 41,
    "rocket-silo": 42,
    "small-electric-pole": 43,
    "solar-panel": 44,
    "splitter": 45,
    "steam-engine": 46,
    "steam-turbine": 47,
    "steel-chest": 48,
    "steel-furnace": 49,
    "stone-furnace": 50,
    "stone-wall": 51,
    "substation": 52,
    "transport-belt": 53,
    "underground-belt": 54,
    "wooden-chest": 55,
}

# Reverse mapping: enum value -> entity name
ENTITY_ENUM_TO_NAME = {v: k for k, v in ENTITY_NAME_ENUM.items()}


def _get_status_enum_from_db(con: duckdb.DuckDBPyConnection) -> List[str]:
    """Get status enum values from DuckDB."""
    try:
        status_enum = con.execute("""
            SELECT unnest(enum_range(NULL::status))
        """).fetchall()
        return [row[0] for row in status_enum]
    except:
        return []


def _decode_status_record(
    record: List[int],
    entity_enum_to_name: Dict[int, str],
    status_enum: List[str],
) -> Optional[Tuple[str, int, str, float, float]]:
    """
    Decode a status record from compressed format.
    
    Args:
        record: [entity_enum, status_enum, pos_x_int, pos_y_int]
        entity_enum_to_name: Mapping from enum value to entity name
        status_enum: List of status names (indexed by enum value)
    
    Returns:
        (entity_key, tick, status_name, x, y) or None if invalid
    """
    if len(record) != 4:
        return None
    
    entity_enum_val, status_enum_val, pos_x_int, pos_y_int = record
    
    # Convert entity enum to name
    entity_name = entity_enum_to_name.get(entity_enum_val)
    if not entity_name:
        return None
    
    # Convert status enum to name
    if status_enum_val < 0 or status_enum_val >= len(status_enum):
        return None
    status_name = status_enum[status_enum_val]
    
    # Convert position back from integer (divide by 2)
    x = float(pos_x_int) / 2.0
    y = float(pos_y_int) / 2.0
    
    # Generate entity_key: (entity_name:x,y)
    entity_key = f"({entity_name}:{x},{y})"
    
    return (entity_key, status_name, x, y)


def load_status_file(
    con: duckdb.DuckDBPyConnection,
    status_file: Path,
    tick: Optional[int] = None,
) -> int:
    """
    Load a single status file into DuckDB (temporary table).
    
    Args:
        con: DuckDB connection
        status_file: Path to status JSONL file
        tick: Optional tick value (extracted from filename if not provided)
    
    Returns:
        Number of records loaded
    """
    # Extract tick from filename if not provided
    if tick is None:
        # Filename format: status-{tick}.jsonl
        try:
            tick = int(status_file.stem.split("-")[-1])
        except:
            tick = 0
    
    # Get status enum from DB
    status_enum = _get_status_enum_from_db(con)
    if not status_enum:
        return 0
    
    # Read and decode status records
    status_records = []
    with open(status_file, "r") as f:
        for line in f:
            if line.strip():
                try:
                    record = json.loads(line)
                    decoded = _decode_status_record(
                        record,
                        ENTITY_ENUM_TO_NAME,
                        status_enum,
                    )
                    if decoded:
                        entity_key, status_name, x, y = decoded
                        status_records.append({
                            "entity_key": entity_key,
                            "tick": tick,
                            "status": status_name,
                            "x": x,
                            "y": y,
                        })
                except:
                    continue
    
    if not status_records:
        return 0
    
    # Load into temporary table (replaces any existing temp data)
    # Use a temp table that gets replaced on each load
    con.execute("DROP TABLE IF EXISTS temp_entity_status;")
    con.execute("""
        CREATE TEMPORARY TABLE temp_entity_status (
            entity_key VARCHAR,
            tick INTEGER,
            status status,
            x DOUBLE,
            y DOUBLE
        );
    """)
    
    for record in status_records:
        con.execute(
            """
            INSERT INTO temp_entity_status (entity_key, tick, status, x, y)
            VALUES (?, ?, ?::status, ?, ?)
            """,
            [
                record["entity_key"],
                record["tick"],
                record["status"],
                record["x"],
                record["y"],
            ],
        )
    
    return len(status_records)


def get_latest_status_file(status_dir: Path) -> Optional[Tuple[Path, int]]:
    """
    Get the latest status file from the status directory.
    
    Args:
        status_dir: Path to status directory
    
    Returns:
        (file_path, tick) or None if no files found
    """
    status_dir = Path(status_dir)
    if not status_dir.exists():
        return None
    
    # Find all status files
    status_files = list(status_dir.glob("status-*.jsonl"))
    if not status_files:
        return None
    
    # Sort by tick (extracted from filename)
    def get_tick(file_path: Path) -> int:
        try:
            return int(file_path.stem.split("-")[-1])
        except:
            return 0
    
    status_files.sort(key=get_tick, reverse=True)
    latest_file = status_files[0]
    tick = get_tick(latest_file)
    
    return (latest_file, tick)


def create_status_view(con: duckdb.DuckDBPyConnection) -> None:
    """
    Create a view that references the temporary status table.
    This view will always show the latest loaded status.
    Can be joined with map_entity for full entity information.
    """
    # Create view that joins with map_entity for full context
    con.execute("""
        CREATE OR REPLACE VIEW entity_status_latest AS
        SELECT 
            es.entity_key,
            es.tick,
            es.status,
            es.x,
            es.y,
            me.entity_name,
            me.position as entity_position,
            me.bbox as entity_bbox,
            me.electric_network_id
        FROM temp_entity_status es
        LEFT JOIN map_entity me ON es.entity_key = me.entity_key;
    """)
    
    # Also create a simpler view without joins for faster queries
    con.execute("""
        CREATE OR REPLACE VIEW entity_status_raw AS
        SELECT 
            entity_key,
            tick,
            status,
            x,
            y
        FROM temp_entity_status;
    """)


def load_latest_status(con: duckdb.DuckDBPyConnection, status_dir: Path) -> int:
    """
    Load the latest status file and create/update the view.
    
    Args:
        con: DuckDB connection
        status_dir: Path to status directory
    
    Returns:
        Number of records loaded
    """
    result = get_latest_status_file(status_dir)
    if not result:
        return 0
    
    latest_file, tick = result
    count = load_status_file(con, latest_file, tick)
    
    # Create/update view
    create_status_view(con)
    
    return count


class StatusSubscriber:
    """
    Subscribe to entity status changes.
    Can filter by entity names and/or status values.
    """
    
    def __init__(self, con: duckdb.DuckDBPyConnection, status_dir: Path):
        self.con = con
        self.status_dir = Path(status_dir)
        self.entity_filters: Set[str] = set()
        self.status_filters: Set[str] = set()
        self.last_tick: int = 0
    
    def subscribe_entities(self, entity_names: List[str]) -> None:
        """Subscribe to specific entity names."""
        self.entity_filters.update(entity_names)
    
    def subscribe_statuses(self, status_names: List[str]) -> None:
        """Subscribe to specific status values."""
        self.status_filters.update(status_names)
    
    def get_updates(self) -> List[Dict]:
        """
        Get status updates since last call.
        Returns filtered results based on subscriptions.
        """
        # Load latest status
        count = load_latest_status(self.con, self.status_dir)
        if count == 0:
            return []
        
        # Build query with filters
        conditions = []
        params = []
        
        if self.entity_filters:
            # Extract entity names from entity_key format: (entity_name:x,y)
            entity_patterns = [f"entity_key LIKE '({name}:%'" for name in self.entity_filters]
            conditions.append(f"({' OR '.join(entity_patterns)})")
        
        if self.status_filters:
            status_list = list(self.status_filters)
            conditions.append(f"status IN ({', '.join(['?'] * len(status_list))})")
            params.extend(status_list)
        
        # Only get records newer than last_tick
        conditions.append("tick > ?")
        params.append(self.last_tick)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        query = f"""
            SELECT entity_key, tick, status, x, y
            FROM entity_status_latest
            WHERE {where_clause}
            ORDER BY tick
        """
        
        results = self.con.execute(query, params).fetchall()
        
        # Update last_tick
        if results:
            self.last_tick = max(row[1] for row in results)
        
        # Convert to dicts
        return [
            {
                "entity_key": row[0],
                "tick": row[1],
                "status": row[2],
                "x": row[3],
                "y": row[4],
            }
            for row in results
        ]

