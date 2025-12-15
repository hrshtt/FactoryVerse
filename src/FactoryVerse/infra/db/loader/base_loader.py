"""
Load base tables: water_tile, resource_tile, resource_entity, map_entity, ghosts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import duckdb

from .utils import normalize_snapshot_dir, load_jsonl_file, iter_chunk_dirs


def load_water_tiles(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """Load water tiles from water_init.jsonl files.
    
    This loads ALL water tiles from ALL chunks globally into the water_tile table.
    """
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    
    # Clear existing water tiles to ensure we have fresh data
    con.execute("DELETE FROM water_tile;")
    
    water_files = list(snapshot_dir.rglob("water_init.jsonl"))
    
    if not water_files:
        return
    
    print(f"  Found {len(water_files)} water_init.jsonl files across all chunks")
    
    # Collect all water tiles from ALL chunks
    water_data = []
    for water_file in water_files:
        with open(water_file, "r") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    entity_key = f"water:{data['x']},{data['y']}"
                    water_data.append({
                        "entity_key": entity_key,
                        "type": "water-tile",
                        "position": {"x": float(data["x"]), "y": float(data["y"])},
                    })
    
    if water_data:
        print(f"  Loading {len(water_data)} water tiles into water_tile table (global, across all chunks)")
        con.executemany(
            """
            INSERT INTO water_tile (entity_key, type, position)
            VALUES (?, ?, ?)
            """,
            [
                (
                    w["entity_key"],
                    w["type"],
                    json.dumps(w["position"]),
                )
                for w in water_data
            ],
        )


def load_resource_tiles(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """Load resource tiles from resources_init.jsonl files."""
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    resource_files = list(snapshot_dir.rglob("resources_init.jsonl"))
    
    if not resource_files:
        return
    
    resource_data = []
    for resource_file in resource_files:
        with open(resource_file, "r") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    entity_key = f"{data['kind']}:{data['x']},{data['y']}"
                    resource_data.append({
                        "entity_key": entity_key,
                        "name": data["kind"],
                        "position": {"x": float(data["x"]), "y": float(data["y"])},
                        "amount": data.get("amount", 0),
                    })
    
    if resource_data:
        con.executemany(
            """
            INSERT OR REPLACE INTO resource_tile (entity_key, name, position, amount)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    r["entity_key"],
                    r["name"],
                    json.dumps(r["position"]),
                    r["amount"],
                )
                for r in resource_data
            ],
        )


def load_resource_entities(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """Load resource entities (trees, rocks) from trees_rocks_init.jsonl files."""
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    entity_files = list(snapshot_dir.rglob("trees_rocks_init.jsonl"))
    
    if not entity_files:
        return
    
    entity_data = []
    for entity_file in entity_files:
        with open(entity_file, "r") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    entity_key = data.get("key") or f"{data['name']}:{data['position']['x']},{data['position']['y']}"
                    bbox = data.get("bounding_box", {})
                    
                    # Store bounding box coordinates for BOX_2D construction
                    bbox_coords = None
                    if bbox:
                        min_x = float(bbox.get("min_x", data["position"]["x"]))
                        min_y = float(bbox.get("min_y", data["position"]["y"]))
                        max_x = float(bbox.get("max_x", data["position"]["x"]))
                        max_y = float(bbox.get("max_y", data["position"]["y"]))
                        bbox_coords = (min_x, min_y, max_x, max_y)
                    
                    entity_data.append({
                        "entity_key": entity_key,
                        "name": data["name"],
                        "type": data.get("type", "unknown"),
                        "position": {"x": float(data["position"]["x"]), "y": float(data["position"]["y"])},
                        "bbox": bbox_coords,
                    })
    
    if entity_data:
        for e in entity_data:
            if e["bbox"]:
                # Use ST_MakeEnvelope to create GEOMETRY (POLYGON)
                min_x, min_y, max_x, max_y = e["bbox"]
                con.execute(
                    """
                    INSERT OR REPLACE INTO resource_entity (entity_key, name, type, position, bbox)
                    VALUES (?, ?, ?, ?, ST_MakeEnvelope(?, ?, ?, ?))
                    """,
                    [
                        e["entity_key"],
                        e["name"],
                        e["type"],
                        json.dumps(e["position"]),
                        min_x,
                        min_y,
                        max_x,
                        max_y,
                    ],
                )
            else:
                con.execute(
                    """
                    INSERT OR REPLACE INTO resource_entity (entity_key, name, type, position)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        e["entity_key"],
                        e["name"],
                        e["type"],
                        json.dumps(e["position"]),
                    ],
                )


def _process_entity_data(
    data: Dict[str, Any],
    entity_data: List[Dict[str, Any]],
    valid_entities: Optional[set],
) -> int:
    """
    Process a single entity data dict and add to entity_data list.
    
    Returns:
        Number of skipped entities (0 or 1)
    """
    entity_name = data.get("name")
    if not entity_name:
        return 0
    
    # Filter out entities not in our placeable_entity ENUM
    if valid_entities and entity_name not in valid_entities:
        return 1
    
    entity_key = data.get("key")
    if not entity_key:
        return 0
    
    bbox = data.get("bounding_box", {})
    pos = data.get("position", {})
    px = float(pos.get("x", 0.0))
    py = float(pos.get("y", 0.0))
    
    # Store bounding box coordinates for GEOMETRY construction
    if bbox:
        min_x = float(bbox.get("min_x", px))
        min_y = float(bbox.get("min_y", py))
        max_x = float(bbox.get("max_x", px))
        max_y = float(bbox.get("max_y", py))
        bbox_coords = (min_x, min_y, max_x, max_y)
    else:
        # Fallback to point
        min_x = min_y = px
        max_x = max_y = py
        bbox_coords = (min_x, min_y, max_x, max_y)
    
    entity_data.append({
        "entity_key": entity_key,
        "position": {"x": px, "y": py},
        "entity_name": entity_name,
        "bbox": bbox_coords,
        "electric_network_id": data.get("electric_network_id"),
    })
    return 0


def load_map_entities(
    con: duckdb.DuckDBPyConnection, 
    snapshot_dir: Path,
    replay_updates: bool = True,
) -> None:
    """
    Load map entities from entities_init.jsonl files.
    
    Optionally replays entities_updates.jsonl to compute current state.
    
    Args:
        con: DuckDB connection
        snapshot_dir: Path to snapshot directory
        replay_updates: If True, replay entities_updates.jsonl operations log
    """
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    
    # Get valid placeable entity names from the ENUM
    try:
        valid_entities = set(con.execute("""
            SELECT unnest(enum_range(NULL::placeable_entity))
        """).fetchall())
        valid_entities = {row[0] for row in valid_entities}
    except:
        # If we can't query the ENUM, we'll filter later
        valid_entities = None
    
    entity_data = []
    skipped_count = 0
    
    # Load initial state from all chunks
    for chunk_x, chunk_y, chunk_dir in iter_chunk_dirs(snapshot_dir):
        init_file = chunk_dir / "entities_init.jsonl"
        if init_file.exists():
            for entry in load_jsonl_file(init_file):
                skipped_count += _process_entity_data(entry, entity_data, valid_entities)
        
        # Replay operations log if requested
        if replay_updates:
            updates_file = chunk_dir / "entities_updates.jsonl"
            if updates_file.exists():
                for op in load_jsonl_file(updates_file):
                    op_type = op.get("op")
                    if op_type == "upsert":
                        entity_data_entry = op.get("entity")
                        if entity_data_entry:
                            skipped_count += _process_entity_data(
                                entity_data_entry, entity_data, valid_entities
                            )
                    elif op_type == "remove":
                        entity_key = op.get("key")
                        if entity_key:
                            # Remove from entity_data list
                            entity_data[:] = [e for e in entity_data if e["entity_key"] != entity_key]
    
    if skipped_count > 0:
        print(f"  Skipped {skipped_count} entities not in placeable_entity ENUM")
    
    if entity_data:
        # Clear existing entities
        con.execute("DELETE FROM map_entity;")
        
        for e in entity_data:
            # Use ST_MakeEnvelope to create GEOMETRY (POLYGON)
            min_x, min_y, max_x, max_y = e["bbox"]
            con.execute(
                """
                INSERT OR REPLACE INTO map_entity (entity_key, position, entity_name, bbox, electric_network_id)
                VALUES (?, ?, ?, ST_MakeEnvelope(?, ?, ?, ?), ?)
                """,
                [
                    e["entity_key"],
                    json.dumps(e["position"]),
                    e["entity_name"],
                    min_x,
                    min_y,
                    max_x,
                    max_y,
                    e["electric_network_id"],
                ],
            )


def load_ghosts(
    con: duckdb.DuckDBPyConnection,
    snapshot_dir: Path,
    replay_updates: bool = True,
) -> None:
    """
    Load ghosts from ghosts-init.jsonl file.
    
    Optionally replays ghosts-updates.jsonl to compute current state.
    
    Args:
        con: DuckDB connection
        snapshot_dir: Path to snapshot directory
        replay_updates: If True, replay ghosts-updates.jsonl operations log
    """
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    
    # Check if ghost table exists (may not be in schema)
    try:
        con.execute("SELECT 1 FROM ghost_layer LIMIT 1;")
    except:
        # Table doesn't exist, skip ghost loading
        return
    
    con.execute("DELETE FROM ghost_layer;")
    
    ghosts_by_key: Dict[str, Tuple] = {}
    
    # Load initial state from top-level ghosts-init.jsonl
    init_file = snapshot_dir / "ghosts-init.jsonl"
    if init_file.exists():
        for entry in load_jsonl_file(init_file):
            ghost_name = entry.get("ghost_name") or "unknown"
            pos = entry.get("position") or {}
            px = float(pos.get("x", 0.0))
            py = float(pos.get("y", 0.0))
            
            ghost_key = entry.get("key") or f"{ghost_name}:{px}:{py}"
            
            chunk = entry.get("chunk") or {}
            chunk_x = chunk.get("x") if chunk else None
            chunk_y = chunk.get("y") if chunk else None
            
            ghosts_by_key[ghost_key] = (
                ghost_key,
                ghost_name,
                entry.get("force"),
                px,
                py,
                entry.get("direction"),
                entry.get("direction_name"),
                chunk_x,
                chunk_y,
            )
    
    # Replay operations log if requested
    if replay_updates:
        updates_file = snapshot_dir / "ghosts-updates.jsonl"
        if updates_file.exists():
            for op in load_jsonl_file(updates_file):
                op_type = op.get("op")
                if op_type == "upsert":
                    ghost_data = op.get("ghost")
                    if ghost_data:
                        ghost_name = ghost_data.get("ghost_name") or "unknown"
                        pos = ghost_data.get("position") or {}
                        px = float(pos.get("x", 0.0))
                        py = float(pos.get("y", 0.0))
                        ghost_key = ghost_data.get("key") or f"{ghost_name}:{px}:{py}"
                        chunk = ghost_data.get("chunk") or {}
                        chunk_x = chunk.get("x") if chunk else None
                        chunk_y = chunk.get("y") if chunk else None
                        ghosts_by_key[ghost_key] = (
                            ghost_key,
                            ghost_name,
                            ghost_data.get("force"),
                            px,
                            py,
                            ghost_data.get("direction"),
                            ghost_data.get("direction_name"),
                            chunk_x,
                            chunk_y,
                        )
                elif op_type == "remove":
                    ghost_key = op.get("key")
                    if ghost_key:
                        ghosts_by_key.pop(ghost_key, None)
    
    # Insert into database
    if ghosts_by_key:
        con.executemany(
            """
            INSERT INTO ghost_layer (
                ghost_key, ghost_name, force_name,
                map_position,
                direction, direction_name,
                chunk_x, chunk_y
            )
            VALUES (
                ?, ?, ?,
                ST_Point(?, ?),
                ?, ?,
                ?, ?
            )
            """,
            list(ghosts_by_key.values()),
        )


def load_base_tables(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """
    Load all base tables from snapshot directory.
    
    Args:
        con: DuckDB connection
        snapshot_dir: Path to snapshot directory (will be normalized)
    """
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    
    print("Loading water tiles...")
    load_water_tiles(con, snapshot_dir)
    
    print("Loading resource tiles...")
    load_resource_tiles(con, snapshot_dir)
    
    print("Loading resource entities...")
    load_resource_entities(con, snapshot_dir)
    
    print("Loading map entities...")
    load_map_entities(con, snapshot_dir)
    
    print("Base tables loaded successfully.")

