"""
Helpers to load Factorio snapshot files into the DuckDB map/analytics schema.

File Structure (JSONL-based):
  chunks/{x}/{y}/
  ├── resources_init.jsonl      # Ore tiles (written once per chunk)
  ├── water_init.jsonl          # Water tiles (written once per chunk)
  ├── trees_rocks_init.jsonl    # Trees and rocks (written once per chunk)
  ├── entities_init.jsonl       # ALL player-placed entities (snapshot)
  └── entities_updates.jsonl    # Append-only operations log
  
  Top-level:
  ├── ghosts-init.jsonl         # ALL ghosts (top-level, not chunk-wise)
  └── ghosts-updates.jsonl     # Append-only operations log

Operations Log Format (entities_updates.jsonl):
  {"op": "upsert", "tick": 12345, "entity": {...full entity data...}}
  {"op": "remove", "tick": 12346, "key": "inserter@5,10", "position": {...}, "name": "inserter"}

Operations Log Format (ghosts-updates.jsonl):
  {"op": "upsert", "tick": 12345, "ghost": {...full ghost data...}}
  {"op": "remove", "tick": 12346, "key": "inserter@5,10", "position": {...}, "ghost_name": "inserter"}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import duckdb


# ---------------------------------------------------------------------------
# File I/O Helpers
# ---------------------------------------------------------------------------


def _load_jsonl_file(file_path: Path) -> List[Dict[str, Any]]:
    """Load a JSONL file, returning list of parsed JSON objects."""
    if not file_path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with file_path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # Best-effort; skip bad lines
                continue
    return out


def _iter_chunk_dirs(snapshots_root: Path) -> Iterable[Tuple[int, int, Path]]:
    """
    Yield (chunk_x, chunk_y, chunk_dir) for all chunk directories.
    Directory structure: snapshots_root/{chunk_x}/{chunk_y}/
    """
    if not snapshots_root.exists():
        return

    for chunk_x_dir in snapshots_root.iterdir():
        if not chunk_x_dir.is_dir():
            continue
        try:
            chunk_x = int(chunk_x_dir.name)
        except ValueError:
            continue

        for chunk_y_dir in chunk_x_dir.iterdir():
            if not chunk_y_dir.is_dir():
                continue
            try:
                chunk_y = int(chunk_y_dir.name)
            except ValueError:
                continue

            yield chunk_x, chunk_y, chunk_y_dir


# ---------------------------------------------------------------------------
# Resource tiles (ores/stone/coal/oil) and water tiles
# ---------------------------------------------------------------------------


def load_resource_and_water_layers(
    con: duckdb.DuckDBPyConnection, script_output_dir: Path
) -> None:
    """
    Load all resource tiles and water tiles into `resource_layer` and `water_layer`.

    Files:
      - resources_init.jsonl: Ore tiles
      - water_init.jsonl: Water tiles
    """
    snapshots_root = script_output_dir / "factoryverse" / "snapshots"

    con.execute("DELETE FROM resource_layer;")
    con.execute("DELETE FROM water_layer;")

    resource_rows_by_key: Dict[str, Tuple[str, str, str, float, float, int]] = {}
    water_rows_by_key: Dict[str, Tuple[str, str, float, float]] = {}

    for chunk_x, chunk_y, chunk_dir in _iter_chunk_dirs(snapshots_root):
        # Resources (ores)
        resources_file = chunk_dir / "resources_init.jsonl"
        if resources_file.exists():
            for entry in _load_jsonl_file(resources_file):
                kind = entry.get("kind")
                if not kind:
                    continue
                x = float(entry.get("x", 0))
                y = float(entry.get("y", 0))
                amount = int(entry.get("amount", 0))
                cx = x + 0.5
                cy = y + 0.5
                resource_key = f"{kind}:{int(x)}:{int(y)}"
                resource_rows_by_key[resource_key] = (
                    resource_key,
                    kind,
                    kind,
                    cx,
                    cy,
                    amount,
                )

        # Water tiles
        water_file = chunk_dir / "water_init.jsonl"
        if water_file.exists():
            for entry in _load_jsonl_file(water_file):
                kind = entry.get("kind") or "water"
                x = float(entry.get("x", 0))
                y = float(entry.get("y", 0))
                cx = x + 0.5
                cy = y + 0.5
                water_key = f"{kind}:{int(x)}:{int(y)}"
                water_rows_by_key[water_key] = (water_key, kind, cx, cy)

    if resource_rows_by_key:
        con.executemany(
            """
            INSERT INTO resource_layer (resource_key, resource_name, resource_type,
                                        map_position, yield)
            VALUES (?, ?, ?, ST_Point(?, ?), ?)
            """,
            list(resource_rows_by_key.values()),
        )

    if water_rows_by_key:
        con.executemany(
            """
            INSERT INTO water_layer (water_key, tile_name, map_position)
            VALUES (?, ?, ST_Point(?, ?))
            """,
            list(water_rows_by_key.values()),
        )


# ---------------------------------------------------------------------------
# Resource entities: trees and rocks
# ---------------------------------------------------------------------------


def load_resource_entities(
    con: duckdb.DuckDBPyConnection, script_output_dir: Path
) -> None:
    """
    Load trees and rocks into `resource_entities`.

    File: trees_rocks_init.jsonl
    """
    snapshots_root = script_output_dir / "factoryverse" / "snapshots"

    con.execute("DELETE FROM resource_entities;")

    rows_by_key: Dict[
        str, Tuple[str, str, str, float, float, float, float, float, float]
    ] = {}

    for chunk_x, chunk_y, chunk_dir in _iter_chunk_dirs(snapshots_root):
        trees_rocks_file = chunk_dir / "trees_rocks_init.jsonl"
        if not trees_rocks_file.exists():
            continue

        for entry in _load_jsonl_file(trees_rocks_file):
            name = entry.get("name")
            etype = entry.get("type")
            pos = entry.get("position") or {}
            bbox = entry.get("bounding_box") or {}

            if not name or not etype or not pos or not bbox:
                continue

            px = float(pos.get("x", 0.0))
            py = float(pos.get("y", 0.0))
            min_x = float(bbox.get("min_x", px))
            min_y = float(bbox.get("min_y", py))
            max_x = float(bbox.get("max_x", px))
            max_y = float(bbox.get("max_y", py))

            entity_key = f"{name}:{px}:{py}"
            rows_by_key[entity_key] = (
                entity_key,
                name,
                etype,
                px,
                py,
                min_x,
                min_y,
                max_x,
                max_y,
            )

    if rows_by_key:
        con.executemany(
            """
            INSERT INTO resource_entities (
                entity_key, resource_name, resource_type,
                map_position, bounding_box
            )
            VALUES (
                ?, ?, ?,
                ST_Point(?, ?),
                ST_MakeEnvelope(?, ?, ?, ?)
            )
            """,
            list(rows_by_key.values()),
        )


# ---------------------------------------------------------------------------
# Entities + components
# ---------------------------------------------------------------------------


def _process_entity_data(
    data: Dict[str, Any],
    entities_by_key: Dict[str, Tuple],
    belts_by_key: Dict[str, Tuple],
    inserters_by_key: Dict[str, Tuple],
) -> None:
    """
    Process a single entity data dict and add to the appropriate dictionaries.
    """
    name = data.get("name") or "unknown"
    etype = data.get("type") or "unknown"
    pos = data.get("position") or {}
    px = float(pos.get("x", 0.0))
    py = float(pos.get("y", 0.0))

    bbox = data.get("bounding_box")
    if bbox:
        min_x = float(bbox.get("min_x", px))
        min_y = float(bbox.get("min_y", py))
        max_x = float(bbox.get("max_x", px))
        max_y = float(bbox.get("max_y", py))
    else:
        # Fallback 1x1 box centered on tile
        min_x = px - 0.5
        min_y = py - 0.5
        max_x = px + 0.5
        max_y = py + 0.5

    entity_key = data.get("key") or f"{name}:{px}:{py}"

    entities_by_key[entity_key] = (
        entity_key,
        name,
        etype,
        data.get("force"),
        px,
        py,
        min_x,
        min_y,
        max_x,
        max_y,
        data.get("direction"),
        data.get("direction_name"),
        data.get("orientation"),
        data.get("electric_network_id"),
        data.get("recipe"),
    )

    # Belts
    if "belt_data" in data:
        belts_by_key[entity_key] = (
            entity_key,
            name,
            json.dumps(data.get("belt_data") or {}),
        )

    # Inserters
    if "inserter" in data:
        inserters_by_key[entity_key] = (
            entity_key,
            name,
            data.get("electric_network_id"),
            json.dumps(data.get("inserter") or {}),
        )


def _replay_operations_log(
    updates_file: Path,
    entities_by_key: Dict[str, Tuple],
    belts_by_key: Dict[str, Tuple],
    inserters_by_key: Dict[str, Tuple],
) -> None:
    """
    Replay the operations log (entities_updates.jsonl) to compute current state.

    Operations format:
      {"op": "upsert", "tick": 12345, "entity": {...}}
      {"op": "remove", "tick": 12346, "key": "inserter@5,10", ...}
    """
    if not updates_file.exists():
        return

    for op in _load_jsonl_file(updates_file):
        op_type = op.get("op")

        if op_type == "upsert":
            entity_data = op.get("entity")
            if entity_data:
                _process_entity_data(
                    entity_data, entities_by_key, belts_by_key, inserters_by_key
                )

        elif op_type == "remove":
            entity_key = op.get("key")
            if entity_key:
                entities_by_key.pop(entity_key, None)
                belts_by_key.pop(entity_key, None)
                inserters_by_key.pop(entity_key, None)


def load_entity_snapshots(
    con: duckdb.DuckDBPyConnection, script_output_dir: Path
) -> None:
    """
    Load all entity snapshots into `entity_layer` and component tables.

    Files per chunk:
      - entities_init.jsonl: Initial snapshot of all entities
      - entities_updates.jsonl: Append-only operations log (upsert/remove)

    The init file is loaded first, then the updates log is replayed to compute
    the current state.
    """
    snapshots_root = script_output_dir / "factoryverse" / "snapshots"

    con.execute("DELETE FROM component_transport_belt;")
    con.execute("DELETE FROM component_inserter;")
    con.execute("DELETE FROM component_assembler;")
    con.execute("DELETE FROM component_furnace;")
    con.execute("DELETE FROM component_boiler;")
    con.execute("DELETE FROM component_electric_pole;")
    con.execute("DELETE FROM component_mining_drill;")
    con.execute("DELETE FROM entity_layer;")

    entities_by_key: Dict[str, Tuple] = {}
    belts_by_key: Dict[str, Tuple] = {}
    inserters_by_key: Dict[str, Tuple] = {}

    for chunk_x, chunk_y, chunk_dir in _iter_chunk_dirs(snapshots_root):
        init_file = chunk_dir / "entities_init.jsonl"
        updates_file = chunk_dir / "entities_updates.jsonl"

        # Load initial state
        if init_file.exists():
            for entry in _load_jsonl_file(init_file):
                _process_entity_data(
                    entry, entities_by_key, belts_by_key, inserters_by_key
                )

        # Replay operations log
        _replay_operations_log(
            updates_file, entities_by_key, belts_by_key, inserters_by_key
        )

    # Insert into database
    if entities_by_key:
        con.executemany(
            """
            INSERT INTO entity_layer (
                entity_key, entity_name, entity_type, force_name,
                map_position, bounding_box,
                direction, direction_name, orientation,
                electric_network_id, recipe
            )
            VALUES (
                ?, ?, ?, ?,
                ST_Point(?, ?),
                ST_MakeEnvelope(?, ?, ?, ?),
                ?, ?, ?,
                ?, ?
            )
            """,
            list(entities_by_key.values()),
        )

    if belts_by_key:
        con.executemany(
            """
            INSERT INTO component_transport_belt (entity_key, entity_name, belt_data)
            VALUES (?, ?, ?)
            """,
            list(belts_by_key.values()),
        )

    if inserters_by_key:
        con.executemany(
            """
            INSERT INTO component_inserter (
                entity_key, entity_name, electric_network_id, inserter_data
            )
            VALUES (?, ?, ?, ?)
            """,
            list(inserters_by_key.values()),
        )


# ---------------------------------------------------------------------------
# Ghosts
# ---------------------------------------------------------------------------


def _process_ghost_data(
    data: Dict[str, Any],
    ghosts_by_key: Dict[str, Tuple],
) -> None:
    """
    Process a single ghost data dict and add to the ghosts dictionary.
    """
    ghost_name = data.get("ghost_name") or "unknown"
    pos = data.get("position") or {}
    px = float(pos.get("x", 0.0))
    py = float(pos.get("y", 0.0))

    ghost_key = data.get("key") or f"{ghost_name}:{px}:{py}"

    chunk = data.get("chunk") or {}
    chunk_x = chunk.get("x") if chunk else None
    chunk_y = chunk.get("y") if chunk else None

    ghosts_by_key[ghost_key] = (
        ghost_key,
        ghost_name,
        data.get("force"),
        px,
        py,
        data.get("direction"),
        data.get("direction_name"),
        chunk_x,
        chunk_y,
    )


def _replay_ghost_operations_log(
    updates_file: Path,
    ghosts_by_key: Dict[str, Tuple],
) -> None:
    """
    Replay the ghost operations log (ghosts-updates.jsonl) to compute current state.

    Operations format:
      {"op": "upsert", "tick": 12345, "ghost": {...}}
      {"op": "remove", "tick": 12346, "key": "inserter@5,10", ...}
    """
    if not updates_file.exists():
        return

    for op in _load_jsonl_file(updates_file):
        op_type = op.get("op")

        if op_type == "upsert":
            ghost_data = op.get("ghost")
            if ghost_data:
                _process_ghost_data(ghost_data, ghosts_by_key)

        elif op_type == "remove":
            ghost_key = op.get("key")
            if ghost_key:
                ghosts_by_key.pop(ghost_key, None)


def load_ghost_snapshots(
    con: duckdb.DuckDBPyConnection, script_output_dir: Path
) -> None:
    """
    Load all ghost snapshots into `ghost_layer`.

    Files (top-level, not chunk-wise):
      - ghosts-init.jsonl: Initial snapshot of all ghosts
      - ghosts-updates.jsonl: Append-only operations log (upsert/remove)

    The init file is loaded first, then the updates log is replayed to compute
    the current state.
    """
    snapshots_root = script_output_dir / "factoryverse" / "snapshots"

    con.execute("DELETE FROM ghost_layer;")

    ghosts_by_key: Dict[str, Tuple] = {}

    # Load initial state from top-level ghosts-init.jsonl
    init_file = snapshots_root / "ghosts-init.jsonl"
    if init_file.exists():
        for entry in _load_jsonl_file(init_file):
            _process_ghost_data(entry, ghosts_by_key)

    # Replay operations log from top-level ghosts-updates.jsonl
    updates_file = snapshots_root / "ghosts-updates.jsonl"
    _replay_ghost_operations_log(updates_file, ghosts_by_key)

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


# ---------------------------------------------------------------------------
# Analytics: power + agent production
# ---------------------------------------------------------------------------


def load_power_statistics(
    con: duckdb.DuckDBPyConnection, script_output_dir: Path
) -> None:
    """Load global power statistics."""
    power_file = (
        script_output_dir / "factoryverse" / "snapshots" / "global_power_statistics.jsonl"
    )
    con.execute("DELETE FROM power_statistics;")

    entries = _load_jsonl_file(power_file)
    rows: List[Tuple[int, str, str, str]] = []
    for entry in entries:
        stats = entry.get("statistics") or {}
        tick = int(entry.get("tick", 0))
        rows.append(
            (
                tick,
                json.dumps(stats.get("input", {})),
                json.dumps(stats.get("output", {})),
                json.dumps(stats.get("storage", {})),
            )
        )

    if rows:
        con.executemany(
            """
            INSERT INTO power_statistics (tick, input, output, storage)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )


def load_agent_production_statistics(
    con: duckdb.DuckDBPyConnection, script_output_dir: Path
) -> None:
    """Load per-agent production statistics."""
    base = script_output_dir / "factoryverse" / "snapshots"
    con.execute("DELETE FROM agent_production_statistics;")

    rows = []
    for path in base.glob("*/production_statistics.jsonl"):
        try:
            agent_id = int(path.parent.name)
        except ValueError:
            continue
        entries = _load_jsonl_file(path)
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


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def load_all(
    con: duckdb.DuckDBPyConnection,
    script_output_dir: Path,
) -> None:
    """Load everything into the schema in one shot."""
    load_resource_and_water_layers(con, script_output_dir)
    load_resource_entities(con, script_output_dir)
    load_entity_snapshots(con, script_output_dir)
    load_ghost_snapshots(con, script_output_dir)
    load_power_statistics(con, script_output_dir)
    load_agent_production_statistics(con, script_output_dir)


__all__ = [
    "load_resource_and_water_layers",
    "load_resource_entities",
    "load_entity_snapshots",
    "load_ghost_snapshots",
    "load_power_statistics",
    "load_agent_production_statistics",
    "load_all",
]
