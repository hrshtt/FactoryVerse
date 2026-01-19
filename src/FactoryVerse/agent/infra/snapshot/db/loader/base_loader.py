"""
Load base tables: water_tile, resource_tile, resource_entity, map_entity, ghosts.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import duckdb

from .utils import normalize_snapshot_dir, load_jsonl_file, iter_chunk_dirs


def load_water_tiles(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """Load water tiles from water-init.jsonl files.
    
    This loads ALL water tiles from ALL chunks globally into the water_tile table.
    """
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    
    # Clear existing water tiles to ensure we have fresh data
    con.execute("DELETE FROM water_tile;")
    
    water_files = list(snapshot_dir.rglob("water-init.jsonl"))
    
    if not water_files:
        return
    
    print(f"  Found {len(water_files)} water-init.jsonl files across all chunks")
    
    # Collect all water tiles from ALL chunks
    water_data = []
    for water_file in water_files:
        with open(water_file, "r") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    water_data.append({
                        "position_x": float(data["x"]),
                        "position_y": float(data["y"]),
                        "type": "water-tile",
                        "position": {"x": float(data["x"]), "y": float(data["y"])},
                    })
    
    if water_data:
        print(f"  Loading {len(water_data)} water tiles into water_tile table (global, across all chunks)")
        con.executemany(
            """
            INSERT INTO water_tile (position_x, position_y, type, position)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    w["position_x"],
                    w["position_y"],
                    w["type"],
                    json.dumps(w["position"]),
                )
                for w in water_data
            ],
        )


def load_resource_tiles(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """Load resource tiles from resources-init.jsonl files."""
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    resource_files = list(snapshot_dir.rglob("resources-init.jsonl"))
    
    if not resource_files:
        return
    
    resource_data = []
    for resource_file in resource_files:
        with open(resource_file, "r") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    resource_data.append({
                        "name": data["kind"],
                        "position_x": float(data["x"]),
                        "position_y": float(data["y"]),
                        "position": {"x": float(data["x"]), "y": float(data["y"])},
                        "amount": data.get("amount", 0),
                    })
    
    if resource_data:
        con.executemany(
            """
            INSERT OR REPLACE INTO resource_tile (name, position_x, position_y, position, amount)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    r["name"],
                    r["position_x"],
                    r["position_y"],
                    json.dumps(r["position"]),
                    r["amount"],
                )
                for r in resource_data
            ],
        )


def load_resource_entities(con: duckdb.DuckDBPyConnection, snapshot_dir: Path, replay_updates: bool = True) -> None:
    """Load resource entities (trees, rocks) from trees_rocks-init.jsonl files.
    
    Optionally replays trees_rocks-updates.jsonl to compute current state.
    
    Args:
        con: DuckDB connection
        snapshot_dir: Path to snapshot directory
        replay_updates: If True, replay trees_rocks-updates.jsonl operations log
    """
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    entity_files = list(snapshot_dir.rglob("trees_rocks-init.jsonl"))
    
    if not entity_files:
        return
    
    entity_data = []
    for entity_file in entity_files:
        with open(entity_file, "r") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    bbox = data.get("bounding_box", {})
                    pos = data.get("position", {})
                    px = float(pos.get("x", 0))
                    py = float(pos.get("y", 0))
                    
                    # Store bounding box coordinates for BOX_2D construction
                    bbox_coords = None
                    if bbox:
                        min_x = float(bbox.get("min_x", px))
                        min_y = float(bbox.get("min_y", py))
                        max_x = float(bbox.get("max_x", px))
                        max_y = float(bbox.get("max_y", py))
                        bbox_coords = (min_x, min_y, max_x, max_y)
                    
                    entity_data.append({
                        "name": data["name"],
                        "position_x": px,
                        "position_y": py,
                        "type": data.get("type", "unknown"),
                        "position": {"x": px, "y": py},
                        "bbox": bbox_coords,
                    })
    
    if entity_data:
        for e in entity_data:
            if e["bbox"]:
                # Use ST_MakeEnvelope to create GEOMETRY (POLYGON)
                min_x, min_y, max_x, max_y = e["bbox"]
                con.execute(
                    """
                    INSERT OR REPLACE INTO resource_entity (name, position_x, position_y, type, position, bbox)
                    VALUES (?, ?, ?, ?, ?, ST_MakeEnvelope(?, ?, ?, ?))
                    """,
                    [
                        e["name"],
                        e["position_x"],
                        e["position_y"],
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
                    INSERT OR REPLACE INTO resource_entity (name, position_x, position_y, type, position)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        e["name"],
                        e["position_x"],
                        e["position_y"],
                        e["type"],
                        json.dumps(e["position"]),
                    ],
                )
    
    # Replay updates log (trees_rocks-updates.jsonl) if requested
    if replay_updates:
        update_files = list(snapshot_dir.rglob("trees_rocks-updates.jsonl"))
        for update_file in update_files:
            with open(update_file, "r") as f:
                for line in f:
                    if line.strip():
                        operation = json.loads(line)
                        op = operation.get("op")
                        if op == "remove":
                            # Remove the entity from the database using composite key
                            entity_name = operation.get("name", "")
                            position = operation.get("position", {})
                            if entity_name and position:
                                con.execute(
                                    "DELETE FROM resource_entity WHERE name = ? AND position_x = ? AND position_y = ?",
                                    [entity_name, float(position.get("x", 0)), float(position.get("y", 0))]
                                )


def _compute_footprint_tiles(
    px: float,
    py: float,
    tile_width: int,
    tile_height: int,
    direction: Optional[int] = None,
) -> List[Tuple[int, int]]:
    """
    Compute the tiles occupied by an entity's footprint.

    Args:
        px, py: Entity center position
        tile_width, tile_height: Entity dimensions in tiles
        direction: Entity direction (0=N, 4=E, 8=S, 12=W)

    Returns:
        List of (tile_x, tile_y) tuples
    """
    # For asymmetric entities facing EAST/WEST, swap dimensions
    effective_width = tile_width
    effective_height = tile_height
    if direction is not None and direction in (4, 12):  # EAST=4, WEST=12
        if tile_width != tile_height:
            effective_width, effective_height = tile_height, tile_width

    half_w = effective_width / 2
    half_h = effective_height / 2

    min_x = math.floor(px - half_w)
    max_x = math.floor(px + half_w - 0.001)
    min_y = math.floor(py - half_h)
    max_y = math.floor(py + half_h - 0.001)

    return [
        (x, y)
        for x in range(min_x, max_x + 1)
        for y in range(min_y, max_y + 1)
    ]


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

    pos = data.get("position", {})
    px = float(pos.get("x", 0.0))
    py = float(pos.get("y", 0.0))

    if not pos or (px == 0.0 and py == 0.0):
        return 0

    # Store bounding box coordinates for GEOMETRY construction
    bbox = data.get("bounding_box", {})
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

    # Anchor tile: tile containing entity center
    tile_x = math.floor(px)
    tile_y = math.floor(py)

    # Get tile dimensions (default to 1x1)
    tile_width = data.get("tile_width", 1)
    tile_height = data.get("tile_height", 1)
    direction = data.get("direction")

    # Footprint tiles: either from serialized data or computed
    footprint_tiles = data.get("footprint_tiles")
    if footprint_tiles:
        # Convert from [{x, y}, ...] to [(x, y), ...]
        footprint_tiles = [(t.get("x", 0), t.get("y", 0)) for t in footprint_tiles]
    else:
        # Compute from position and dimensions
        footprint_tiles = _compute_footprint_tiles(px, py, tile_width, tile_height, direction)

    entity_data.append({
        "entity_name": entity_name,
        "position_x": px,
        "position_y": py,
        "position": {"x": px, "y": py},
        "bbox": bbox_coords,
        "electric_network_id": data.get("electric_network_id"),
        "tile_x": tile_x,
        "tile_y": tile_y,
        "footprint_tiles": footprint_tiles,
    })
    return 0


def load_map_entities(
    con: duckdb.DuckDBPyConnection, 
    snapshot_dir: Path,
    replay_updates: bool = True,
) -> None:
    """
    Load map entities from entities-init.jsonl files.
    
    Optionally replays entities-updates.jsonl to compute current state.
    
    Args:
        con: DuckDB connection
        snapshot_dir: Path to snapshot directory
        replay_updates: If True, replay entities-updates.jsonl operations log
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
        init_file = chunk_dir / "entities-init.jsonl"
        if init_file.exists():
            for entry in load_jsonl_file(init_file):
                skipped_count += _process_entity_data(entry, entity_data, valid_entities)
        
        # Replay operations log if requested
        if replay_updates:
            updates_file = chunk_dir / "entities-updates.jsonl"
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
                        entity_name = op.get("name", "")
                        position = op.get("position", {})
                        if entity_name and position:
                            px = float(position.get("x", 0))
                            py = float(position.get("y", 0))
                            # Remove from entity_data list using composite key
                            entity_data[:] = [
                                e for e in entity_data 
                                if not (e.get("entity_name") == entity_name and 
                                        e.get("position_x") == px and 
                                        e.get("position_y") == py)
                            ]
                    elif op_type == "rotated":
                        entity_name = op.get("name", "")
                        position = op.get("position", {})
                        direction = op.get("direction")
                        if entity_name and position and direction is not None:
                            px = float(position.get("x", 0))
                            py = float(position.get("y", 0))
                            # Update direction in entity_data list using composite key
                            for entity in entity_data:
                                if (entity.get("entity_name") == entity_name and
                                    entity.get("position_x") == px and
                                    entity.get("position_y") == py):
                                    entity["direction"] = direction
                                    entity["direction_name"] = op.get("direction_name")
                                    break
    
    if skipped_count > 0:
        print(f"  Skipped {skipped_count} entities not in placeable_entity ENUM")
    
    if entity_data:
        # Clear existing entities and footprint tiles
        con.execute("DELETE FROM map_entity;")
        con.execute("DELETE FROM footprint_tiles;")

        # Collect all footprint tile entries for batch insert
        footprint_entries = []

        for e in entity_data:
            # Use ST_MakeEnvelope to create GEOMETRY (POLYGON)
            min_x, min_y, max_x, max_y = e["bbox"]
            con.execute(
                """
                INSERT OR REPLACE INTO map_entity (entity_name, position_x, position_y, position, bbox, electric_network_id, tile_x, tile_y)
                VALUES (?, ?, ?, ?, ST_MakeEnvelope(?, ?, ?, ?), ?, ?, ?)
                """,
                [
                    e["entity_name"],
                    e["position_x"],
                    e["position_y"],
                    json.dumps(e["position"]),
                    min_x,
                    min_y,
                    max_x,
                    max_y,
                    e["electric_network_id"],
                    e["tile_x"],
                    e["tile_y"],
                ],
            )

            # Collect footprint tiles for this entity
            for tile_x, tile_y in e.get("footprint_tiles", []):
                footprint_entries.append((
                    tile_x,
                    tile_y,
                    e["entity_name"],
                    e["position_x"],
                    e["position_y"],
                    False,  # is_ghost = False for regular entities
                ))

        # Batch insert footprint tiles
        if footprint_entries:
            con.executemany(
                """
                INSERT OR REPLACE INTO footprint_tiles (tile_x, tile_y, entity_name, entity_position_x, entity_position_y, is_ghost)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                footprint_entries,
            )
            print(f"  Loaded {len(footprint_entries)} footprint tiles")


def _process_ghost_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Process a ghost entry and compute footprint tiles if needed."""
    ghost_name = entry.get("ghost_name") or "unknown"
    pos = entry.get("position") or {}
    px = float(pos.get("x", 0.0))
    py = float(pos.get("y", 0.0))

    chunk = entry.get("chunk") or {}
    chunk_x = chunk.get("x") if chunk else None
    chunk_y = chunk.get("y") if chunk else None

    # Get tile dimensions (default to 1x1)
    tile_width = entry.get("tile_width", 1)
    tile_height = entry.get("tile_height", 1)
    direction = entry.get("direction")

    # Footprint tiles: either from serialized data or computed
    footprint_tiles = entry.get("footprint_tiles")
    if footprint_tiles:
        footprint_tiles = [(t.get("x", 0), t.get("y", 0)) for t in footprint_tiles]
    else:
        footprint_tiles = _compute_footprint_tiles(px, py, tile_width, tile_height, direction)

    return {
        "ghost_name": ghost_name,
        "position_x": px,
        "position_y": py,
        "force": entry.get("force"),
        "direction": direction,
        "direction_name": entry.get("direction_name"),
        "chunk_x": chunk_x,
        "chunk_y": chunk_y,
        "tile_width": tile_width,
        "tile_height": tile_height,
        "footprint_tiles": footprint_tiles,
    }


def load_ghosts(
    con: duckdb.DuckDBPyConnection,
    snapshot_dir: Path,
    replay_updates: bool = True,
) -> None:
    """
    Load ghosts from chunk-wise ghosts-init.jsonl files.

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

    ghosts_by_key: Dict[Tuple[str, float, float], Dict[str, Any]] = {}

    # Load initial state from chunk-wise ghosts-init.jsonl files
    ghost_init_files = list(snapshot_dir.rglob("ghosts-init.jsonl"))
    for init_file in ghost_init_files:
        for entry in load_jsonl_file(init_file):
            ghost_data = _process_ghost_entry(entry)
            composite_key = (ghost_data["ghost_name"], ghost_data["position_x"], ghost_data["position_y"])
            ghosts_by_key[composite_key] = ghost_data

    # Replay operations log if requested (chunk-wise ghosts-updates.jsonl files)
    if replay_updates:
        update_files = list(snapshot_dir.rglob("ghosts-updates.jsonl"))
        for updates_file in update_files:
            for op in load_jsonl_file(updates_file):
                op_type = op.get("op")
                if op_type == "upsert":
                    ghost_entry = op.get("ghost")
                    if ghost_entry:
                        ghost_data = _process_ghost_entry(ghost_entry)
                        composite_key = (ghost_data["ghost_name"], ghost_data["position_x"], ghost_data["position_y"])
                        ghosts_by_key[composite_key] = ghost_data
                elif op_type == "remove":
                    ghost_name = op.get("ghost_name") or op.get("name", "")
                    position = op.get("position", {})
                    if ghost_name and position:
                        px = float(position.get("x", 0))
                        py = float(position.get("y", 0))
                        composite_key = (ghost_name, px, py)
                        ghosts_by_key.pop(composite_key, None)
                elif op_type == "rotated":
                    ghost_name = op.get("ghost_name") or op.get("name", "")
                    position = op.get("position", {})
                    direction = op.get("direction")
                    if ghost_name and position and direction is not None:
                        px = float(position.get("x", 0))
                        py = float(position.get("y", 0))
                        composite_key = (ghost_name, px, py)
                        # Update direction and recompute footprint
                        if composite_key in ghosts_by_key:
                            ghost_data = ghosts_by_key[composite_key]
                            ghost_data["direction"] = direction
                            ghost_data["direction_name"] = op.get("direction_name")
                            # Recompute footprint tiles with new direction
                            ghost_data["footprint_tiles"] = _compute_footprint_tiles(
                                ghost_data["position_x"],
                                ghost_data["position_y"],
                                ghost_data.get("tile_width", 1),
                                ghost_data.get("tile_height", 1),
                                direction,
                            )

    # Insert into database and collect footprint tiles
    ghost_footprint_entries = []

    if ghosts_by_key:
        for ghost_data in ghosts_by_key.values():
            con.execute(
                """
                INSERT INTO ghost_layer (
                    ghost_name, position_x, position_y, force_name,
                    map_position,
                    direction, direction_name,
                    chunk_x, chunk_y
                )
                VALUES (
                    ?, ?, ?, ?,
                    ST_Point(?, ?),
                    ?, ?,
                    ?, ?
                )
                """,
                [
                    ghost_data["ghost_name"],
                    ghost_data["position_x"],
                    ghost_data["position_y"],
                    ghost_data.get("force"),
                    ghost_data["position_x"],
                    ghost_data["position_y"],
                    ghost_data.get("direction"),
                    ghost_data.get("direction_name"),
                    ghost_data.get("chunk_x"),
                    ghost_data.get("chunk_y"),
                ],
            )

            # Collect footprint tiles for this ghost
            for tile_x, tile_y in ghost_data.get("footprint_tiles", []):
                ghost_footprint_entries.append((
                    tile_x,
                    tile_y,
                    ghost_data["ghost_name"],
                    ghost_data["position_x"],
                    ghost_data["position_y"],
                    True,  # is_ghost = True
                ))

        # Insert ghost footprint tiles (using INSERT OR IGNORE to avoid conflicts with entity tiles)
        if ghost_footprint_entries:
            con.executemany(
                """
                INSERT OR IGNORE INTO footprint_tiles (tile_x, tile_y, entity_name, entity_position_x, entity_position_y, is_ghost)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ghost_footprint_entries,
            )
            print(f"  Loaded {len(ghost_footprint_entries)} ghost footprint tiles")


def load_base_tables(con: duckdb.DuckDBPyConnection, snapshot_dir: Path, replay_updates: bool = True) -> None:
    """
    Load all base tables from snapshot directory.
    
    Args:
        con: DuckDB connection
        snapshot_dir: Path to snapshot directory (will be normalized)
        replay_updates: If True, replay operations logs (entities-updates.jsonl, trees_rocks-updates.jsonl)
    """
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    
    print("Loading water tiles...")
    load_water_tiles(con, snapshot_dir)
    
    print("Loading resource tiles...")
    load_resource_tiles(con, snapshot_dir)
    
    print("Loading resource entities...")
    load_resource_entities(con, snapshot_dir, replay_updates=replay_updates)
    
    print("Loading map entities...")
    load_map_entities(con, snapshot_dir, replay_updates=replay_updates)
    
    print("Base tables loaded successfully.")

