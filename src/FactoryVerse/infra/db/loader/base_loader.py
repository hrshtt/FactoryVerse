"""
Load base tables: water_tile, resource_tile, resource_entity, map_entity.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List

import duckdb


def load_water_tiles(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """Load water tiles from water_init.jsonl files.
    
    This loads ALL water tiles from ALL chunks globally into the water_tile table.
    """
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


def load_map_entities(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """Load map entities from entities_init.jsonl files."""
    entity_files = list(snapshot_dir.rglob("entities_init.jsonl"))
    
    if not entity_files:
        return
    
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
    for entity_file in entity_files:
        with open(entity_file, "r") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    entity_name = data["name"]
                    
                    # Filter out entities not in our placeable_entity ENUM
                    if valid_entities and entity_name not in valid_entities:
                        skipped_count += 1
                        continue
                    
                    entity_key = data["key"]
                    bbox = data.get("bounding_box", {})
                    
                    # Store bounding box coordinates for GEOMETRY construction
                    if bbox:
                        min_x = float(bbox.get("min_x", data["position"]["x"]))
                        min_y = float(bbox.get("min_y", data["position"]["y"]))
                        max_x = float(bbox.get("max_x", data["position"]["x"]))
                        max_y = float(bbox.get("max_y", data["position"]["y"]))
                        bbox_coords = (min_x, min_y, max_x, max_y)
                    else:
                        # Fallback to point
                        pos = data["position"]
                        min_x = min_y = float(pos['x'])
                        max_x = max_y = float(pos['y'])
                        bbox_coords = (min_x, min_y, max_x, max_y)
                    
                    entity_data.append({
                        "entity_key": entity_key,
                        "position": {"x": float(data["position"]["x"]), "y": float(data["position"]["y"])},
                        "entity_name": entity_name,
                        "bbox": bbox_coords,
                        "electric_network_id": data.get("electric_network_id"),
                    })
    
    if skipped_count > 0:
        print(f"  Skipped {skipped_count} entities not in placeable_entity ENUM")
    
    if entity_data:
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


def load_base_tables(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """
    Load all base tables from snapshot directory.
    
    Args:
        con: DuckDB connection
        snapshot_dir: Path to snapshot directory (e.g., script-output/factoryverse/snapshots)
    """
    snapshot_dir = Path(snapshot_dir)
    
    print("Loading water tiles...")
    load_water_tiles(con, snapshot_dir)
    
    print("Loading resource tiles...")
    load_resource_tiles(con, snapshot_dir)
    
    print("Loading resource entities...")
    load_resource_entities(con, snapshot_dir)
    
    print("Loading map entities...")
    load_map_entities(con, snapshot_dir)
    
    print("Base tables loaded successfully.")

