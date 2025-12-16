"""
Load component tables: inserter, transport_belt, mining_drill, assemblers, pumpjack.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional, Set

import duckdb

from .utils import normalize_snapshot_dir, load_jsonl_file, iter_chunk_dirs


def load_inserters(
    con: duckdb.DuckDBPyConnection, 
    snapshot_dir: Path,
    replay_updates: bool = True,
) -> None:
    """
    Load inserters from entities_init.jsonl files.
    
    Optionally replays entities_updates.jsonl to compute current state.
    """
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    entity_files = list(snapshot_dir.rglob("entities_init.jsonl"))
    
    # Get valid placeable entity names from the ENUM
    try:
        valid_entities = set(con.execute("""
            SELECT unnest(enum_range(NULL::placeable_entity))
        """).fetchall())
        valid_entities = {row[0] for row in valid_entities}
    except:
        valid_entities = None
    
    inserter_data: Dict[str, Dict[str, Any]] = {}
    
    def process_inserter_entity(data: Dict[str, Any]) -> None:
        """Process a single entity and add to inserter_data if it's an inserter."""
        # Filter out entities not in our placeable_entity ENUM
        if valid_entities and data.get("name") not in valid_entities:
            return
        if data.get("type") == "inserter" and "inserter" in data:
            inserter_info = data["inserter"]
            direction_name = data.get("direction_name", "north")
            
            # Build output struct
            drop_pos = inserter_info.get("drop_position", {})
            output_struct = None
            if drop_pos:
                output_struct = {
                    "position": {"x": drop_pos.get("x", 0), "y": drop_pos.get("y", 0)},
                    "entity_key": inserter_info.get("drop_target_key"),
                }
            
            # Build input struct
            pickup_pos = inserter_info.get("pickup_position", {})
            input_struct = None
            if pickup_pos:
                input_struct = {
                    "position": {"x": pickup_pos.get("x", 0), "y": pickup_pos.get("y", 0)},
                    "entity_key": inserter_info.get("pickup_target_key"),
                }
            
            entity_key = data.get("key")
            if entity_key:
                inserter_data[entity_key] = {
                    "entity_key": entity_key,
                    "direction": direction_name.upper(),  # Convert to uppercase to match ENUM
                    "output": output_struct,
                    "input": input_struct,
                }
    
    # Load initial state
    for entity_file in entity_files:
        for entry in load_jsonl_file(entity_file):
            process_inserter_entity(entry)
    
    # Replay operations log if requested
    if replay_updates:
        for chunk_x, chunk_y, chunk_dir in iter_chunk_dirs(snapshot_dir):
            updates_file = chunk_dir / "entities_updates.jsonl"
            if updates_file.exists():
                for op in load_jsonl_file(updates_file):
                    op_type = op.get("op")
                    if op_type == "upsert":
                        entity_data = op.get("entity")
                        if entity_data:
                            process_inserter_entity(entity_data)
                    elif op_type == "remove":
                        entity_key = op.get("key")
                        if entity_key:
                            inserter_data.pop(entity_key, None)
    
    if inserter_data:
        for i in inserter_data.values():
            # Cast string to ENUM type explicitly
            con.execute(
                """
                INSERT OR REPLACE INTO inserter (entity_key, direction, output, input)
                VALUES (?, ?::direction, ?, ?)
                """,
                [
                    i["entity_key"],
                    i["direction"],
                    json.dumps(i["output"]) if i["output"] else None,
                    json.dumps(i["input"]) if i["input"] else None,
                ],
            )


def load_transport_belts(
    con: duckdb.DuckDBPyConnection, 
    snapshot_dir: Path,
    replay_updates: bool = True,
) -> None:
    """
    Load transport belts from entities_init.jsonl files.
    
    Optionally replays entities_updates.jsonl to compute current state.
    """
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    entity_files = list(snapshot_dir.rglob("entities_init.jsonl"))
    
    # Get valid placeable entity names from the ENUM
    try:
        valid_entities = set(con.execute("""
            SELECT unnest(enum_range(NULL::placeable_entity))
        """).fetchall())
        valid_entities = {row[0] for row in valid_entities}
    except:
        valid_entities = None
    
    belt_data: Dict[str, Dict[str, Any]] = {}
    
    def process_belt_entity(data: Dict[str, Any]) -> None:
        """Process a single entity and add to belt_data if it's a transport belt."""
        # Filter out entities not in our placeable_entity ENUM
        if valid_entities and data.get("name") not in valid_entities:
            return
        if data.get("type") == "transport-belt" and "belt_data" in data:
            belt_info = data["belt_data"]
            neighbours = belt_info.get("belt_neighbours", {})
            direction_name = data.get("direction_name", "north")
            
            # Output is a single struct
            outputs = neighbours.get("outputs", [])
            output_struct = None
            if outputs:
                output_struct = {"entity_key": outputs[0]}
            
            # Input is an array of structs
            inputs = neighbours.get("inputs", [])
            input_array = [{"entity_key": inp} for inp in inputs] if inputs else []
            
            entity_key = data.get("key")
            if entity_key:
                belt_data[entity_key] = {
                    "entity_key": entity_key,
                    "direction": direction_name.upper(),  # Convert to uppercase to match ENUM
                    "output": output_struct,
                    "input": input_array,
                }
    
    # Load initial state
    for entity_file in entity_files:
        for entry in load_jsonl_file(entity_file):
            process_belt_entity(entry)
    
    # Replay operations log if requested
    if replay_updates:
        for chunk_x, chunk_y, chunk_dir in iter_chunk_dirs(snapshot_dir):
            updates_file = chunk_dir / "entities_updates.jsonl"
            if updates_file.exists():
                for op in load_jsonl_file(updates_file):
                    op_type = op.get("op")
                    if op_type == "upsert":
                        entity_data = op.get("entity")
                        if entity_data:
                            process_belt_entity(entity_data)
                    elif op_type == "remove":
                        entity_key = op.get("key")
                        if entity_key:
                            belt_data.pop(entity_key, None)
    
    if belt_data:
        for b in belt_data.values():
            # Cast string to ENUM type explicitly
            con.execute(
                """
                INSERT OR REPLACE INTO transport_belt (entity_key, direction, output, input)
                VALUES (?, ?::direction, ?, ?)
                """,
                [
                    b["entity_key"],
                    b["direction"],
                    json.dumps(b["output"]) if b["output"] else None,
                    json.dumps(b["input"]) if b["input"] else None,
                ],
            )


def load_mining_drills(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """Load mining drills from entities_init.jsonl files."""
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    entity_files = list(snapshot_dir.rglob("entities_init.jsonl"))
    
    # Get valid placeable entity names from the ENUM
    try:
        valid_entities = set(con.execute("""
            SELECT unnest(enum_range(NULL::placeable_entity))
        """).fetchall())
        valid_entities = {row[0] for row in valid_entities}
    except:
        valid_entities = None
    
    drill_data = []
    for entity_file in entity_files:
        with open(entity_file, "r") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    # Filter out entities not in our placeable_entity ENUM
                    if valid_entities and data.get("name") not in valid_entities:
                        continue
                    if data.get("type") == "mining-drill" and "mining_area" in data:
                        mining_area = data["mining_area"]
                        direction_name = data.get("direction_name", "north")
                        
                        # Store mining area coordinates for BOX_2D construction
                        left_top = mining_area.get("left_top", {})
                        right_bottom = mining_area.get("right_bottom", {})
                        min_x = float(left_top.get('x', 0))
                        min_y = float(left_top.get('y', 0))
                        max_x = float(right_bottom.get('x', 0))
                        max_y = float(right_bottom.get('y', 0))
                        
                        # Output position (derived from prototype, but we can get from inserter data if available)
                        output_struct = None
                        # TODO: Get actual output position from prototype
                        
                        drill_data.append({
                            "entity_key": data["key"],
                            "direction": direction_name.upper(),  # Convert to uppercase to match ENUM
                            "mining_area": (min_x, min_y, max_x, max_y),
                            "output": output_struct,
                        })
    
    if drill_data:
        for d in drill_data:
            # Use ST_MakeEnvelope to create GEOMETRY (POLYGON)
            min_x, min_y, max_x, max_y = d["mining_area"]
            # Cast string to ENUM type explicitly
            con.execute(
                """
                INSERT OR REPLACE INTO mining_drill (entity_key, direction, mining_area, output)
                VALUES (?, ?::direction, ST_MakeEnvelope(?, ?, ?, ?), ?)
                """,
                [
                    d["entity_key"],
                    d["direction"],
                    min_x,
                    min_y,
                    max_x,
                    max_y,
                    json.dumps(d["output"]) if d["output"] else None,
                ],
            )


def load_assemblers(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """Load assemblers from entities_init.jsonl files."""
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    entity_files = list(snapshot_dir.rglob("entities_init.jsonl"))
    
    # Get valid placeable entity names from the ENUM
    try:
        valid_entities = set(con.execute("""
            SELECT unnest(enum_range(NULL::placeable_entity))
        """).fetchall())
        valid_entities = {row[0] for row in valid_entities}
    except:
        valid_entities = None
    
    # Get valid recipe names from the ENUM
    try:
        valid_recipes = set(con.execute("""
            SELECT unnest(enum_range(NULL::recipe))
        """).fetchall())
        valid_recipes = {row[0] for row in valid_recipes}
    except:
        valid_recipes = None
    
    assembler_data = []
    skipped_recipes = 0
    for entity_file in entity_files:
        with open(entity_file, "r") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    # Filter out entities not in our placeable_entity ENUM
                    if valid_entities and data.get("name") not in valid_entities:
                        continue
                    # Assembling machines can have recipes
                    if data.get("type") in ("assembling-machine", "furnace") and "recipe" in data:
                        recipe = data.get("recipe")
                        # Filter out recipes not in our recipe ENUM
                        if recipe and valid_recipes and recipe not in valid_recipes:
                            skipped_recipes += 1
                            continue
                        assembler_data.append({
                            "entity_key": data["key"],
                            "recipe": recipe,
                        })
    
    if skipped_recipes > 0:
        print(f"  Skipped {skipped_recipes} recipes not in recipe ENUM")
    
    if assembler_data:
        for a in assembler_data:
            # Cast recipe to ENUM type explicitly
            if a["recipe"]:
                con.execute(
                    """
                    INSERT OR REPLACE INTO assemblers (entity_key, recipe)
                    VALUES (?, ?::recipe)
                    """,
                    [
                        a["entity_key"],
                        a["recipe"],
                    ],
                )
            else:
                con.execute(
                    """
                    INSERT OR REPLACE INTO assemblers (entity_key, recipe)
                    VALUES (?, NULL)
                    """,
                    [a["entity_key"]],
                )


def load_pumpjacks(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """Load pumpjacks from entities_init.jsonl files."""
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    entity_files = list(snapshot_dir.rglob("entities_init.jsonl"))
    
    # Get valid placeable entity names from the ENUM
    try:
        valid_entities = set(con.execute("""
            SELECT unnest(enum_range(NULL::placeable_entity))
        """).fetchall())
        valid_entities = {row[0] for row in valid_entities}
    except:
        valid_entities = None
    
    pumpjack_data = []
    for entity_file in entity_files:
        with open(entity_file, "r") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    # Filter out entities not in our placeable_entity ENUM
                    if valid_entities and data.get("name") not in valid_entities:
                        continue
                    if data.get("name") == "pumpjack":
                        # TODO: Extract output positions from prototype
                        # For now, just create entry
                        pumpjack_data.append({
                            "entity_key": data["key"],
                            "output": [],
                        })
    
    if pumpjack_data:
        for p in pumpjack_data:
            con.execute(
                """
                INSERT OR REPLACE INTO pumpjack (entity_key, output)
                VALUES (?, ?)
                """,
                [
                    p["entity_key"],
                    json.dumps(p["output"]),
                ],
            )


def load_component_tables(
    con: duckdb.DuckDBPyConnection, 
    snapshot_dir: Path,
    replay_updates: bool = True,
) -> None:
    """
    Load all component tables from snapshot directory.
    
    Args:
        con: DuckDB connection
        snapshot_dir: Path to snapshot directory (will be normalized)
        replay_updates: If True, replay entities_updates.jsonl operations log
    """
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    
    print("Loading inserters...")
    load_inserters(con, snapshot_dir, replay_updates)
    
    print("Loading transport belts...")
    load_transport_belts(con, snapshot_dir, replay_updates)
    
    print("Loading mining drills...")
    load_mining_drills(con, snapshot_dir)
    
    print("Loading assemblers...")
    load_assemblers(con, snapshot_dir)
    
    print("Loading pumpjacks...")
    load_pumpjacks(con, snapshot_dir)
    
    print("Component tables loaded successfully.")

