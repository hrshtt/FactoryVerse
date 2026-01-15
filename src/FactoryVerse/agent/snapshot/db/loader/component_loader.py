"""
Load component tables: inserter, transport_belt, mining_drill, assemblers, pumpjack.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional, Set, Tuple

import duckdb

from .utils import normalize_snapshot_dir, load_jsonl_file, iter_chunk_dirs


def load_inserters(
    con: duckdb.DuckDBPyConnection, 
    snapshot_dir: Path,
    replay_updates: bool = True,
) -> None:
    """
    Load inserters from entities-init.jsonl files.
    
    Optionally replays entities-updates.jsonl to compute current state.
    """
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    entity_files = list(snapshot_dir.rglob("entities-init.jsonl"))
    
    # Get valid placeable entity names from the ENUM
    try:
        valid_entities = set(con.execute("""
            SELECT unnest(enum_range(NULL::placeable_entity))
        """).fetchall())
        valid_entities = {row[0] for row in valid_entities}
    except:
        valid_entities = None
    
    inserter_data: Dict[Tuple[str, float, float], Dict[str, Any]] = {}
    
    def process_inserter_entity(data: Dict[str, Any]) -> None:
        """Process a single entity and add to inserter_data if it's an inserter."""
        # Filter out entities not in our placeable_entity ENUM
        if valid_entities and data.get("name") not in valid_entities:
            return
        if data.get("type") == "inserter" and "inserter" in data:
            inserter_info = data["inserter"]
            direction_name = data.get("direction_name", "north")
            pos = data.get("position", {})
            entity_name = data.get("name", "")
            px = float(pos.get("x", 0))
            py = float(pos.get("y", 0))
            
            if not entity_name or (px == 0 and py == 0):
                return
            
            # Build output struct with composite key
            drop_target = inserter_info.get("drop_target")
            output_struct = None
            if drop_target:
                drop_pos = drop_target.get("position", {})
                drop_name = drop_target.get("name", "")
                if drop_pos and drop_name:
                    output_struct = {
                        "position": {"x": float(drop_pos.get("x", 0)), "y": float(drop_pos.get("y", 0))},
                        "entity_name": drop_name,
                        "position_x": float(drop_pos.get("x", 0)),
                        "position_y": float(drop_pos.get("y", 0)),
                    }
            
            # Build input struct with composite key
            pickup_target = inserter_info.get("pickup_target")
            input_struct = None
            if pickup_target:
                pickup_pos = pickup_target.get("position", {})
                pickup_name = pickup_target.get("name", "")
                if pickup_pos and pickup_name:
                    input_struct = {
                        "position": {"x": float(pickup_pos.get("x", 0)), "y": float(pickup_pos.get("y", 0))},
                        "entity_name": pickup_name,
                        "position_x": float(pickup_pos.get("x", 0)),
                        "position_y": float(pickup_pos.get("y", 0)),
                    }
            
            # Use composite key as dictionary key
            composite_key = (entity_name, px, py)
            inserter_data[composite_key] = {
                "entity_name": entity_name,
                "position_x": px,
                "position_y": py,
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
            updates_file = chunk_dir / "entities-updates.jsonl"
            if updates_file.exists():
                for op in load_jsonl_file(updates_file):
                    op_type = op.get("op")
                    if op_type == "upsert":
                        entity_data = op.get("entity")
                        if entity_data:
                            process_inserter_entity(entity_data)
                    elif op_type == "remove":
                        entity_name = op.get("name", "")
                        position = op.get("position", {})
                        if entity_name and position:
                            px = float(position.get("x", 0))
                            py = float(position.get("y", 0))
                            composite_key = (entity_name, px, py)
                            inserter_data.pop(composite_key, None)
                    elif op_type == "rotated":
                        entity_name = op.get("name", "")
                        position = op.get("position", {})
                        direction = op.get("direction")
                        if entity_name and position and direction is not None:
                            px = float(position.get("x", 0))
                            py = float(position.get("y", 0))
                            composite_key = (entity_name, px, py)
                            if composite_key in inserter_data:
                                # Update direction in inserter_data
                                inserter_data[composite_key]["direction"] = direction
    
    if inserter_data:
        for i in inserter_data.values():
            # Cast string to ENUM type explicitly
            con.execute(
                """
                INSERT OR REPLACE INTO inserter (entity_name, position_x, position_y, direction, output, input)
                VALUES (?, ?, ?, ?::direction, ?, ?)
                """,
                [
                    i["entity_name"],
                    i["position_x"],
                    i["position_y"],
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
    Load transport belts from entities-init.jsonl files.
    
    Optionally replays entities-updates.jsonl to compute current state.
    """
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    entity_files = list(snapshot_dir.rglob("entities-init.jsonl"))
    
    # Get valid placeable entity names from the ENUM
    try:
        valid_entities = set(con.execute("""
            SELECT unnest(enum_range(NULL::placeable_entity))
        """).fetchall())
        valid_entities = {row[0] for row in valid_entities}
    except:
        valid_entities = None
    
    belt_data: Dict[Tuple[str, float, float], Dict[str, Any]] = {}
    
    def process_belt_entity(data: Dict[str, Any]) -> None:
        """Process a single entity and add to belt_data if it's a transport belt."""
        # Filter out entities not in our placeable_entity ENUM
        if valid_entities and data.get("name") not in valid_entities:
            return
        if data.get("type") == "transport-belt" and "belt_data" in data:
            belt_info = data["belt_data"]
            neighbours = belt_info.get("belt_neighbours", {})
            direction_name = data.get("direction_name", "north")
            pos = data.get("position", {})
            entity_name = data.get("name", "")
            px = float(pos.get("x", 0))
            py = float(pos.get("y", 0))
            
            if not entity_name or (px == 0 and py == 0):
                return
            
            # Output is a single struct with composite key
            outputs = neighbours.get("outputs", [])
            output_struct = None
            if outputs and len(outputs) > 0:
                output = outputs[0]
                if isinstance(output, dict) and output.get("name") and output.get("position"):
                    out_pos = output.get("position", {})
                    output_struct = {
                        "entity_name": output.get("name", ""),
                        "position_x": float(out_pos.get("x", 0)),
                        "position_y": float(out_pos.get("y", 0)),
                    }
            
            # Input is an array of structs with composite keys
            inputs = neighbours.get("inputs", [])
            input_array = []
            for inp in inputs:
                if isinstance(inp, dict) and inp.get("name") and inp.get("position"):
                    inp_pos = inp.get("position", {})
                    input_array.append({
                        "entity_name": inp.get("name", ""),
                        "position_x": float(inp_pos.get("x", 0)),
                        "position_y": float(inp_pos.get("y", 0)),
                    })
            
            # Use composite key as dictionary key
            composite_key = (entity_name, px, py)
            belt_data[composite_key] = {
                "entity_name": entity_name,
                "position_x": px,
                "position_y": py,
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
            updates_file = chunk_dir / "entities-updates.jsonl"
            if updates_file.exists():
                for op in load_jsonl_file(updates_file):
                    op_type = op.get("op")
                    if op_type == "upsert":
                        entity_data = op.get("entity")
                        if entity_data:
                            process_belt_entity(entity_data)
                    elif op_type == "remove":
                        entity_name = op.get("name", "")
                        position = op.get("position", {})
                        if entity_name and position:
                            px = float(position.get("x", 0))
                            py = float(position.get("y", 0))
                            composite_key = (entity_name, px, py)
                            belt_data.pop(composite_key, None)
                    elif op_type == "rotated":
                        entity_name = op.get("name", "")
                        position = op.get("position", {})
                        direction = op.get("direction")
                        direction_name = op.get("direction_name")
                        if entity_name and position and direction is not None:
                            px = float(position.get("x", 0))
                            py = float(position.get("y", 0))
                            composite_key = (entity_name, px, py)
                            if composite_key in belt_data:
                                # Update direction in belt_data
                                belt_data[composite_key]["direction"] = direction_name.upper() if direction_name else None
    
    if belt_data:
        for b in belt_data.values():
            # Cast string to ENUM type explicitly
            con.execute(
                """
                INSERT OR REPLACE INTO transport_belt (entity_name, position_x, position_y, direction, output, input)
                VALUES (?, ?, ?, ?::direction, ?, ?)
                """,
                [
                    b["entity_name"],
                    b["position_x"],
                    b["position_y"],
                    b["direction"],
                    json.dumps(b["output"]) if b["output"] else None,
                    json.dumps(b["input"]) if b["input"] else None,
                ],
            )


def load_mining_drills(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """Load mining drills from entities-init.jsonl files."""
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    entity_files = list(snapshot_dir.rglob("entities-init.jsonl"))
    
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
                        pos = data.get("position", {})
                        entity_name = data.get("name", "")
                        px = float(pos.get("x", 0))
                        py = float(pos.get("y", 0))
                        
                        if not entity_name or (px == 0 and py == 0):
                            continue
                        
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
                            "entity_name": entity_name,
                            "position_x": px,
                            "position_y": py,
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
                INSERT OR REPLACE INTO mining_drill (entity_name, position_x, position_y, direction, mining_area, output)
                VALUES (?, ?, ?, ?::direction, ST_MakeEnvelope(?, ?, ?, ?), ?)
                """,
                [
                    d["entity_name"],
                    d["position_x"],
                    d["position_y"],
                    d["direction"],
                    min_x,
                    min_y,
                    max_x,
                    max_y,
                    json.dumps(d["output"]) if d["output"] else None,
                ],
            )


def load_assemblers(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """Load assemblers from entities-init.jsonl files."""
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    entity_files = list(snapshot_dir.rglob("entities-init.jsonl"))
    
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
                        pos = data.get("position", {})
                        entity_name = data.get("name", "")
                        px = float(pos.get("x", 0))
                        py = float(pos.get("y", 0))
                        
                        if not entity_name or (px == 0 and py == 0):
                            continue
                        
                        # Filter out recipes not in our recipe ENUM
                        if recipe and valid_recipes and recipe not in valid_recipes:
                            skipped_recipes += 1
                            continue
                        assembler_data.append({
                            "entity_name": entity_name,
                            "position_x": px,
                            "position_y": py,
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
                    INSERT OR REPLACE INTO assemblers (entity_name, position_x, position_y, recipe)
                    VALUES (?, ?, ?, ?::recipe)
                    """,
                    [
                        a["entity_name"],
                        a["position_x"],
                        a["position_y"],
                        a["recipe"],
                    ],
                )
            else:
                con.execute(
                    """
                    INSERT OR REPLACE INTO assemblers (entity_name, position_x, position_y, recipe)
                    VALUES (?, ?, ?, NULL)
                    """,
                    [a["entity_name"], a["position_x"], a["position_y"]],
                )


def load_pumpjacks(con: duckdb.DuckDBPyConnection, snapshot_dir: Path) -> None:
    """Load pumpjacks from entities-init.jsonl files."""
    snapshot_dir = normalize_snapshot_dir(snapshot_dir)
    entity_files = list(snapshot_dir.rglob("entities-init.jsonl"))
    
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
                        pos = data.get("position", {})
                        entity_name = data.get("name", "")
                        px = float(pos.get("x", 0))
                        py = float(pos.get("y", 0))
                        
                        if not entity_name or (px == 0 and py == 0):
                            continue
                        
                        # TODO: Extract output positions from prototype
                        # For now, just create entry
                        pumpjack_data.append({
                            "entity_name": entity_name,
                            "position_x": px,
                            "position_y": py,
                            "output": [],
                        })
    
    if pumpjack_data:
        for p in pumpjack_data:
            con.execute(
                """
                INSERT OR REPLACE INTO pumpjack (entity_name, position_x, position_y, output)
                VALUES (?, ?, ?, ?)
                """,
                [
                    p["entity_name"],
                    p["position_x"],
                    p["position_y"],
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
        replay_updates: If True, replay entities-updates.jsonl operations log
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

