"""
Helpers to load Factorio snapshot files into the DuckDB map/analytics schema.

This mirrors the logic prototyped in `duckdb-trials.ipynb`, but writes into the
normalized spatial tables defined in `duckdb_schema.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import duckdb


def _load_jsonl_file(file_path: Path) -> List[Dict[str, Any]]:
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


def _load_json_file(file_path: Path) -> Optional[Dict[str, Any]]:
    if not file_path.exists():
        return None
    with file_path.open("r") as f:
        return json.load(f)


def _iter_chunk_files(base: Path, pattern: str) -> Iterable[Tuple[int, int, Path]]:
    """
    Yield (chunk_x, chunk_y, path) for files under
    factoryverse/snapshots/{chunk_x}/{chunk_y}/... matching pattern.
    """
    for path in base.rglob(pattern):
        m = re.search(r"/([+-]?\d+)/([+-]?\d+)/", str(path))
        if not m:
            continue
        chunk_x, chunk_y = int(m.group(1)), int(m.group(2))
        yield chunk_x, chunk_y, path


# ---------------------------------------------------------------------------
# Resource tiles (ores/stone/coal/oil) and water tiles
# ---------------------------------------------------------------------------


def load_resource_and_water_layers(con: duckdb.DuckDBPyConnection, script_output_dir: Path) -> None:
    """
    Load all resource tiles and water tiles into `resource_layer` and `water_layer`.

    Args:
        con: DuckDB connection with schema initialized.
        script_output_dir: Factorio `script-output` directory containing
            `factoryverse/snapshots`.
    """
    snapshots_root = script_output_dir / "factoryverse" / "snapshots"

    # Clear existing data for full reload semantics
    con.execute("DELETE FROM resource_layer;")
    con.execute("DELETE FROM water_layer;")

    # --- Resource tiles (ores/stone/coal/crude-oil) -------------------------
    tiles_files = list(_iter_chunk_files(snapshots_root, "tiles.jsonl"))
    # Deduplicate by resource_key to handle tiles that appear in multiple chunks.
    resource_rows_by_key: Dict[str, Tuple[str, str, str, float, float, int]] = {}

    for chunk_x, chunk_y, file_path in tiles_files:
        entries = _load_jsonl_file(file_path)
        for entry in entries:
            kind = entry.get("kind")
            if not kind:
                continue
            x = float(entry.get("x", 0))
            y = float(entry.get("y", 0))
            amount = int(entry.get("amount", 0))

            # Tile centers are at (i + 0.5, j + 0.5)
            cx = x + 0.5
            cy = y + 0.5
            resource_key = f"{kind}:{int(x)}:{int(y)}"

            # For now, treat resource_type == resource_name; can be grouped later.
            resource_rows_by_key[resource_key] = (
                resource_key,
                kind,
                kind,
                cx,
                cy,
                amount,
            )

    if resource_rows_by_key:
        con.executemany(
            """
            INSERT INTO resource_layer (resource_key, resource_name, resource_type,
                                        map_position, yield)
            VALUES (?, ?, ?, ST_Point(?, ?), ?)
            """,
            list(resource_rows_by_key.values()),
        )

    # --- Water tiles --------------------------------------------------------
    water_files = list(_iter_chunk_files(snapshots_root, "water-tiles.jsonl"))
    water_rows_by_key: Dict[str, Tuple[str, str, float, float]] = {}

    for chunk_x, chunk_y, file_path in water_files:
        entries = _load_jsonl_file(file_path)
        for entry in entries:
            kind = entry.get("kind") or "water"
            x = float(entry.get("x", 0))
            y = float(entry.get("y", 0))
            cx = x + 0.5
            cy = y + 0.5
            water_key = f"{kind}:{int(x)}:{int(y)}"
            water_rows_by_key[water_key] = (water_key, kind, cx, cy)

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


def load_resource_entities(con: duckdb.DuckDBPyConnection, script_output_dir: Path) -> None:
    """
    Load trees and rocks into `resource_entities` from entities.jsonl.

    Args:
        con: DuckDB connection.
        script_output_dir: Factorio `script-output` directory.
    """
    snapshots_root = script_output_dir / "factoryverse" / "snapshots"

    con.execute("DELETE FROM resource_entities;")

    entity_files = list(_iter_chunk_files(snapshots_root, "entities.jsonl"))
    # Deduplicate by entity_key, because rocks/trees that span chunk boundaries
    # can appear in multiple chunk files.
    rows_by_key: Dict[
        str, Tuple[str, str, str, float, float, float, float, float, float]
    ] = {}

    for chunk_x, chunk_y, file_path in entity_files:
        entries = _load_jsonl_file(file_path)
        for entry in entries:
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


def _iter_entity_snapshot_files(snapshots_root: Path) -> Iterable[Tuple[int, int, str, Path]]:
    """
    Yield (chunk_x, chunk_y, component_type, path) for entity snapshot files:
    .../{chunk_x}/{chunk_y}/{component_type}/{pos_x}_{pos_y}_{entity_name}.json
    """
    for path in snapshots_root.rglob("*.json"):
        # Skip resource files
        if "/resources/" in str(path):
            continue
        m = re.search(
            r"/([+-]?\d+)/([+-]?\d+)/(entities|belts|pipes|poles)/([+-]?\d+)_([+-]?\d+)_",
            str(path),
        )
        if not m:
            continue
        chunk_x, chunk_y = int(m.group(1)), int(m.group(2))
        component_type = m.group(3)
        yield chunk_x, chunk_y, component_type, path


def load_entity_snapshots(con: duckdb.DuckDBPyConnection, script_output_dir: Path) -> None:
    """
    Load all entity snapshot JSON files into `entity_layer` and component tables.

    This is a full reload: it truncates the tables before inserting.
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

    entity_rows = []
    belt_rows = []
    inserter_rows = []

    for chunk_x, chunk_y, component_type, path in _iter_entity_snapshot_files(snapshots_root):
        data = _load_json_file(path)
        if not data:
            continue

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

        entity_rows.append(
            (
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
        )

        # Belts: store Lua belt_data dict as JSON
        if "belt_data" in data:
            belt_rows.append(
                (
                    entity_key,
                    name,
                    json.dumps(data.get("belt_data") or {}),
                )
            )

        # Inserters: store Lua inserter dict as JSON
        if "inserter" in data:
            inserter_rows.append(
                (
                    entity_key,
                    name,
                    data.get("electric_network_id"),
                    json.dumps(data.get("inserter") or {}),
                )
            )

    if entity_rows:
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
            entity_rows,
        )

    if belt_rows:
        con.executemany(
            """
            INSERT INTO component_transport_belt (entity_key, entity_name, belt_data)
            VALUES (?, ?, ?)
            """,
            belt_rows,
        )

    if inserter_rows:
        con.executemany(
            """
            INSERT INTO component_inserter (
                entity_key, entity_name, electric_network_id, inserter_data
            )
            VALUES (?, ?, ?, ?)
            """,
            inserter_rows,
        )


# ---------------------------------------------------------------------------
# Analytics: power + agent production
# ---------------------------------------------------------------------------


def load_power_statistics(con: duckdb.DuckDBPyConnection, script_output_dir: Path) -> None:
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


def load_all(
    con: duckdb.DuckDBPyConnection,
    script_output_dir: Path,
) -> None:
    """
    Convenience helper to load everything into the schema in one shot.
    """
    load_resource_and_water_layers(con, script_output_dir)
    load_resource_entities(con, script_output_dir)
    load_entity_snapshots(con, script_output_dir)
    load_power_statistics(con, script_output_dir)
    load_agent_production_statistics(con, script_output_dir)


__all__ = [
    "load_resource_and_water_layers",
    "load_resource_entities",
    "load_entity_snapshots",
    "load_power_statistics",
    "load_agent_production_statistics",
    "load_all",
]


