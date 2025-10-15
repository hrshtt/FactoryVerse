"""
PostgreSQL snapshot loader for Factorio snapshots.

Goals
-----
- Ingest raw JSON snapshots into stable staging tables (raw_*).
- Keep it maintainable & DRY: centralized schema, versioned loaders, small helpers.

Usage (example)
---------------
from FactoryVerse.services.duckdb.load_raw_snapshots import (
    connect_db, ensure_schema, load_snapshot_dir
)

con = connect_db()  # uses FACTORYVERSE_PG_DSN or a default DSN
ensure_schema(con)
load_snapshot_dir(con, "/path/to/snaps/")
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple, Sequence

import psycopg2  # type: ignore
from psycopg2.extensions import connection as PGConnection  # type: ignore
from psycopg2.extras import execute_values  # type: ignore

# Alias for typing consistency
Connection = PGConnection  # type: ignore

# -----------------------------
# Constants & helpers
# -----------------------------

PG_USER = os.environ.get("PG_USER", "factoryverse")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "factoryverse")
PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = os.environ.get("PG_PORT", "5432")
PG_DB = os.environ.get("PG_DB", "factoryverse")
DEFAULT_PG_DSN = f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DB}"

print(DEFAULT_PG_DSN)

# Known snapshot schema versions → loader function keys
SCHEMA_BELTS_V2 = "snapshot.belts.v2"
SCHEMA_ENTITIES_V3 = "snapshot.entities.v3"
SCHEMA_RESOURCES_V1 = "snapshot.resources.v1"
SCHEMA_CRUDE_V1 = "snapshot.crude.v1"
SCHEMA_WATER_V1 = "snapshot.water.v1"

BELT_LIKE_NAMES = {
    "transport-belt",
    "underground-belt",
    "splitter",
    "fast-transport-belt",
    "express-transport-belt",
}

# If you add more entity types later (assemblers, refineries, etc.),
# these views/macros will automatically become richer.

# -----------------------------
# Public API
# -----------------------------

def connect_db(dsn: str = DEFAULT_PG_DSN) -> Connection:
    """Open a PostgreSQL connection (autocommit)."""
    con: Connection = psycopg2.connect(dsn)
    # For DDL/DML simplicity in this loader
    con.autocommit = True
    return con


def clear_raw_tables(con: Connection) -> None:
    """Clear all existing data from raw tables."""
    with con.cursor() as cur:
        # Clear all raw tables in reverse dependency order
        tables_to_clear = [
            "raw_entity_inventory",
            "raw_entity_burner", 
            "raw_entity_crafting",
            "raw_entity_electric",
            "raw_entity_inserter",
            "raw_entity_fluids",
            "raw_entities",
            "raw_belts",
            "raw_resource_tiles",
            "raw_resource_patches",
            "raw_crude_tiles", 
            "raw_crude_patches",
            "raw_water_tiles",
            "raw_water_patches",
        ]
        
        for table in tables_to_clear:
            cur.execute(f"DELETE FROM {table};")
            print(f"Cleared table: {table}")


def ensure_schema(con: Connection) -> None:
    """Create raw tables (idempotent) in PostgreSQL."""
    with con.cursor() as cur:
        # Enable PostGIS extension
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        # raw_belts
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_belts (
                tick                BIGINT,
                unit_number         BIGINT,
                name                VARCHAR,
                type                VARCHAR,
                pos_x               INTEGER,
                pos_y               INTEGER,
                direction           INTEGER,
                direction_name      VARCHAR,
                item_lines          JSONB,           -- JSON payload: per-lane items
                neigh_inputs        INTEGER[],        -- upstream unit_numbers
                neigh_outputs       INTEGER[],        -- downstream unit_numbers
                chunk_x             INTEGER,
                chunk_y             INTEGER
            );
            """
        )

    # raw_entities (base footprint) + auxiliary per-subsystem tables
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_entities (
                tick                BIGINT,
                unit_number         BIGINT,
                name                VARCHAR,
                type                VARCHAR,
                force               VARCHAR,
                pos_x               INTEGER,
                pos_y               INTEGER,
                direction           INTEGER,
                direction_name      VARCHAR,
                orientation         DOUBLE PRECISION,
                orientation_name    VARCHAR,
                status              INTEGER,
                status_name         VARCHAR,
                bbox_min_x          DOUBLE PRECISION,
                bbox_min_y          DOUBLE PRECISION,
                bbox_max_x          DOUBLE PRECISION,
                bbox_max_y          DOUBLE PRECISION,
                sel_min_x           DOUBLE PRECISION,
                sel_min_y           DOUBLE PRECISION,
                sel_max_x           DOUBLE PRECISION,
                sel_max_y           DOUBLE PRECISION,
                chunk_x             INTEGER,
                chunk_y             INTEGER
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_entity_fluids (
                tick            BIGINT,
                unit_number     BIGINT,
                fluids          JSONB,     -- list of fluid boxes (name, amount, capacity, temperature)
                chunk_x         INTEGER,
                chunk_y         INTEGER
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_entity_inserter (
                tick                BIGINT,
                unit_number         BIGINT,   -- inserter id
                pickup_x            INTEGER,
                pickup_y            INTEGER,
                drop_x              INTEGER,
                drop_y              INTEGER,
                pickup_target_unit  BIGINT,
                drop_target_unit    BIGINT,
                chunk_x             INTEGER,
                chunk_y             INTEGER
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_entity_electric (
                tick                BIGINT,
                unit_number         BIGINT,
                electric_network_id BIGINT,
                buffer_size         DOUBLE PRECISION,
                energy              DOUBLE PRECISION,
                chunk_x             INTEGER,
                chunk_y             INTEGER
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_entity_crafting (
                tick                BIGINT,
                unit_number         BIGINT,
                recipe              VARCHAR,
                crafting_progress   DOUBLE PRECISION,
                chunk_x             INTEGER,
                chunk_y             INTEGER
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_entity_burner (
                tick            BIGINT,
                unit_number     BIGINT,
                burner_json     JSONB,     -- fuel inventories, etc.
                chunk_x         INTEGER,
                chunk_y         INTEGER
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_entity_inventory (
                tick            BIGINT,
                unit_number     BIGINT,
                inventories     JSONB,
                chunk_x         INTEGER,
                chunk_y         INTEGER
            );
            """
        )

    # resources (solid)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_resource_patches (
                tick            BIGINT,
                patch_id        VARCHAR,
                resource_name   VARCHAR,
                tiles           INTEGER,
                total_amount    BIGINT,
                centroid_x      DOUBLE PRECISION,
                centroid_y      DOUBLE PRECISION,
                bbox_min_x      DOUBLE PRECISION,
                bbox_min_y      DOUBLE PRECISION,
                bbox_max_x      DOUBLE PRECISION,
                bbox_max_y      DOUBLE PRECISION
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_resource_tiles (
                tick            BIGINT,
                patch_id        VARCHAR,
                resource_name   VARCHAR,
                tile_x          INTEGER,
                tile_y          INTEGER,
                len             INTEGER,
                tile_count      INTEGER,
                sum_amount      BIGINT
            );
            """
        )

    # crude (oil)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_crude_patches (
                tick            BIGINT,
                patch_id        VARCHAR,
                tiles           INTEGER,
                wells           INTEGER,
                total_amount    BIGINT,
                centroid_x      DOUBLE PRECISION,
                centroid_y      DOUBLE PRECISION,
                bbox_min_x      DOUBLE PRECISION,
                bbox_min_y      DOUBLE PRECISION,
                bbox_max_x      DOUBLE PRECISION,
                bbox_max_y      DOUBLE PRECISION
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_crude_tiles (
                tick            BIGINT,
                patch_id        VARCHAR,
                resource_name   VARCHAR,
                tile_x          INTEGER,
                tile_y          INTEGER,
                pos_x           INTEGER,
                pos_y           INTEGER,
                amount          BIGINT
            );
            """
        )

    # water
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_water_patches (
                tick            BIGINT,
                patch_id        VARCHAR,
                tiles           INTEGER,
                centroid_x      DOUBLE PRECISION,
                centroid_y      DOUBLE PRECISION,
                bbox_min_x      DOUBLE PRECISION,
                bbox_min_y      DOUBLE PRECISION,
                bbox_max_x      DOUBLE PRECISION,
                bbox_max_y      DOUBLE PRECISION
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_water_tiles (
                tick            BIGINT,
                patch_id        VARCHAR,
                tile_x          INTEGER,
                tile_y          INTEGER,
                len             INTEGER,
                tile_count      INTEGER
            );
            """
        )


# -----------------------------
# Ingestion (versioned loaders)
# -----------------------------

def _listify(x: Any) -> List[int]:
    """Normalize neighbour fields: {}, None → []."""
    if x is None:
        return []
    if isinstance(x, list):
        return [int(v) for v in x]
    # some dumps use empty dict for empty list
    if isinstance(x, dict) and not x:
        return []
    # fall back: single int
    if isinstance(x, (int, float)):
        return [int(x)]
    return []


def _execute_values_insert(
    con: Connection,
    table: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    jsonb_cols: Optional[Sequence[str]] = None,
) -> None:
    if not rows:
        return
    jsonb_set = set(jsonb_cols or [])
    placeholders = ["%s::jsonb" if col in jsonb_set else "%s" for col in columns]
    template = "(" + ", ".join(placeholders) + ")"
    with con.cursor() as cur:
        execute_values(
            cur,
            f"INSERT INTO {table} (" + ", ".join(columns) + ") VALUES %s",
            rows,
            template=template,
        )


def _load_belts_v2(con: Connection, path: str, meta: Dict[str, Any], data: Dict[str, Any]) -> None:
    rows = data.get("rows", [])
    if not rows:
        return
    tick = int(meta.get("tick"))

    rows_out: List[Tuple[Any, ...]] = []
    for r in rows:
        bn = r.get("belt_neighbours", {}) or {}
        inputs = _listify(bn.get("inputs"))
        outputs = _listify(bn.get("outputs"))
        pos = r.get("position", {}) or {}
        chunk = r.get("chunk", {}) or {}
        rows_out.append(
            (
                tick,
                int(r.get("unit_number")),
                r.get("name"),
                r.get("type"),
                int(math.floor(float(pos.get("x")))),
                int(math.floor(float(pos.get("y")))),
                int(r.get("direction", 0)),
                r.get("direction_name"),
                json.dumps(r.get("item_lines", [])),
                inputs,
                outputs,
                int(chunk.get("x", 0)),
                int(chunk.get("y", 0)),
            )
        )

    columns = [
        "tick",
        "unit_number",
        "name",
        "type",
        "pos_x",
        "pos_y",
        "direction",
        "direction_name",
        "item_lines",
        "neigh_inputs",
        "neigh_outputs",
        "chunk_x",
        "chunk_y",
    ]
    _execute_values_insert(con, "raw_belts", columns, rows_out, jsonb_cols=["item_lines"])


def _load_entities_v3(con: Connection, path: str, meta: Dict[str, Any], data: Dict[str, Any]) -> None:
    tick = int(meta.get("tick"))

    def _entity_rows():
        rows = data.get("entity_rows", [])
        for r in rows:
            pos = r.get("position", {}) or {}
            bbox = r.get("bounding_box", {}) or {}
            sel = r.get("selection_box", {}) or {}
            chunk = r.get("chunk", {}) or {}
            yield {
                "tick": tick,
                "unit_number": int(r.get("unit_number")),
                "name": r.get("name"),
                "type": r.get("type"),
                "force": r.get("force"),
                "pos_x": int(math.floor(float(pos.get("x", 0.0)))),
                "pos_y": int(math.floor(float(pos.get("y", 0.0)))),
                "direction": int(r.get("direction", 0)),
                "direction_name": r.get("direction_name"),
                "orientation": float(r.get("orientation", 0.0)),
                "orientation_name": r.get("orientation_name"),
                "status": int(r.get("status", 0)),
                "status_name": r.get("status_name"),
                "bbox_min_x": float(bbox.get("min_x", 0.0)),
                "bbox_min_y": float(bbox.get("min_y", 0.0)),
                "bbox_max_x": float(bbox.get("max_x", 0.0)),
                "bbox_max_y": float(bbox.get("max_y", 0.0)),
                "sel_min_x": float(sel.get("min_x", 0.0)),
                "sel_min_y": float(sel.get("min_y", 0.0)),
                "sel_max_x": float(sel.get("max_x", 0.0)),
                "sel_max_y": float(sel.get("max_y", 0.0)),
                "chunk_x": int(chunk.get("x", 0)),
                "chunk_y": int(chunk.get("y", 0)),
            }

    def _fluids_rows():
        rows = data.get("fluids_rows", [])
        for r in rows:
            chunk = r.get("chunk", {}) or {}
            yield {
                "tick": tick,
                "unit_number": int(r.get("unit_number")),
                "fluids": json.dumps(r.get("fluids", [])),
                "chunk_x": int(chunk.get("x", 0)),
                "chunk_y": int(chunk.get("y", 0)),
            }

    def _inserter_rows():
        rows = data.get("inserter_rows", [])
        for r in rows:
            ins = r.get("inserter", {}) or {}
            pick = ins.get("pickup_position", {}) or {}
            drop = ins.get("drop_position", {}) or {}
            chunk = r.get("chunk", {}) or {}
            yield {
                "tick": tick,
                "unit_number": int(r.get("unit_number")),
                "pickup_x": int(math.floor(float(pick.get("x", 0.0)))),
                "pickup_y": int(math.floor(float(pick.get("y", 0.0)))),
                "drop_x": int(math.floor(float(drop.get("x", 0.0)))),
                "drop_y": int(math.floor(float(drop.get("y", 0.0)))),
                "pickup_target_unit": int(ins.get("pickup_target_unit")) if ins.get("pickup_target_unit") is not None else None,
                "drop_target_unit": int(ins.get("drop_target_unit")) if ins.get("drop_target_unit") is not None else None,
                "chunk_x": int(chunk.get("x", 0)),
                "chunk_y": int(chunk.get("y", 0)),
            }

    def _electric_rows():
        rows = data.get("electric_rows", [])
        for r in rows:
            chunk = r.get("chunk", {}) or {}
            yield {
                "tick": tick,
                "unit_number": int(r.get("unit_number")),
                "electric_network_id": int(r.get("electric_network_id", 0)),
                "buffer_size": float(r.get("electric_buffer_size", 0.0)),
                "energy": float(r.get("energy", 0.0)),
                "chunk_x": int(chunk.get("x", 0)),
                "chunk_y": int(chunk.get("y", 0)),
            }

    def _crafting_rows():
        rows = data.get("crafting_rows", [])
        for r in rows:
            chunk = r.get("chunk", {}) or {}
            yield {
                "tick": tick,
                "unit_number": int(r.get("unit_number")),
                "recipe": r.get("recipe"),
                "crafting_progress": float(r.get("crafting_progress", 0.0)),
                "chunk_x": int(chunk.get("x", 0)),
                "chunk_y": int(chunk.get("y", 0)),
            }

    def _burner_rows():
        rows = data.get("burner_rows", [])
        for r in rows:
            chunk = r.get("chunk", {}) or {}
            yield {
                "tick": tick,
                "unit_number": int(r.get("unit_number")),
                "burner_json": json.dumps(r.get("burner", {})),
                "chunk_x": int(chunk.get("x", 0)),
                "chunk_y": int(chunk.get("y", 0)),
            }

    def _inventory_rows():
        rows = data.get("inventory_rows", [])
        for r in rows:
            chunk = r.get("chunk", {}) or {}
            yield {
                "tick": tick,
                "unit_number": int(r.get("unit_number")),
                "inventories": json.dumps(r.get("inventories", {})),
                "chunk_x": int(chunk.get("x", 0)),
                "chunk_y": int(chunk.get("y", 0)),
            }

    # bulk insert helpers
    def _insert_rows(table: str, columns: Sequence[str], rows_iter: Iterable[Dict[str, Any]], jsonb_cols: Optional[Sequence[str]] = None):
        buf: List[Tuple[Any, ...]] = []
        for r in rows_iter:
            buf.append(tuple(r[c] for c in columns))
        _execute_values_insert(con, table, columns, buf, jsonb_cols=jsonb_cols)

    _insert_rows(
        "raw_entities",
        [
            "tick",
            "unit_number",
            "name",
            "type",
            "force",
            "pos_x",
            "pos_y",
            "direction",
            "direction_name",
            "orientation",
            "orientation_name",
            "status",
            "status_name",
            "bbox_min_x",
            "bbox_min_y",
            "bbox_max_x",
            "bbox_max_y",
            "sel_min_x",
            "sel_min_y",
            "sel_max_x",
            "sel_max_y",
            "chunk_x",
            "chunk_y",
        ],
        _entity_rows(),
    )

    _insert_rows(
        "raw_entity_fluids",
        ["tick", "unit_number", "fluids", "chunk_x", "chunk_y"],
        _fluids_rows(),
        jsonb_cols=["fluids"],
    )

    _insert_rows(
        "raw_entity_inserter",
        [
            "tick",
            "unit_number",
            "pickup_x",
            "pickup_y",
            "drop_x",
            "drop_y",
            "pickup_target_unit",
            "drop_target_unit",
            "chunk_x",
            "chunk_y",
        ],
        _inserter_rows(),
    )

    _insert_rows(
        "raw_entity_electric",
        [
            "tick",
            "unit_number",
            "electric_network_id",
            "buffer_size",
            "energy",
            "chunk_x",
            "chunk_y",
        ],
        _electric_rows(),
    )

    _insert_rows(
        "raw_entity_crafting",
        [
            "tick",
            "unit_number",
            "recipe",
            "crafting_progress",
            "chunk_x",
            "chunk_y",
        ],
        _crafting_rows(),
    )

    _insert_rows(
        "raw_entity_burner",
        ["tick", "unit_number", "burner_json", "chunk_x", "chunk_y"],
        _burner_rows(),
        jsonb_cols=["burner_json"],
    )

    _insert_rows(
        "raw_entity_inventory",
        ["tick", "unit_number", "inventories", "chunk_x", "chunk_y"],
        _inventory_rows(),
        jsonb_cols=["inventories"],
    )


def _load_resources_v1(con: Connection, path: str, meta: Dict[str, Any], data: Dict[str, Any]) -> None:
    tick = int(meta.get("tick"))

    patches = data.get("patch", [])
    if patches:
        rows_out: List[Tuple[Any, ...]] = []
        for p in patches:
            bbox = p.get("bbox", {}) or {}
            centroid = p.get("centroid", {}) or {}
            rows_out.append(
                (
                    tick,
                    p.get("patch_id"),
                    p.get("resource_name"),
                    int(p.get("tiles", 0)),
                    int(p.get("total_amount", 0)),
                    float(centroid.get("x", 0.0)),
                    float(centroid.get("y", 0.0)),
                    float(bbox.get("min_x", 0.0)),
                    float(bbox.get("min_y", 0.0)),
                    float(bbox.get("max_x", 0.0)),
                    float(bbox.get("max_y", 0.0)),
                )
            )
        _execute_values_insert(
            con,
            "raw_resource_patches",
            [
                "tick",
                "patch_id",
                "resource_name",
                "tiles",
                "total_amount",
                "centroid_x",
                "centroid_y",
                "bbox_min_x",
                "bbox_min_y",
                "bbox_max_x",
                "bbox_max_y",
            ],
            rows_out,
        )

    rows = data.get("rows", [])
    if rows:
        rows_out = []
        for r in rows:
            rows_out.append(
                (
                    tick,
                    r.get("patch_id"),
                    r.get("resource_name"),
                    int(r.get("x")),
                    int(r.get("y")),
                    int(r.get("len", 0)),
                    int(r.get("tile_count", 0)),
                    int(r.get("sum_amount", 0)),
                )
            )
        _execute_values_insert(
            con,
            "raw_resource_tiles",
            [
                "tick",
                "patch_id",
                "resource_name",
                "tile_x",
                "tile_y",
                "len",
                "tile_count",
                "sum_amount",
            ],
            rows_out,
        )


def _load_crude_v1(con: Connection, path: str, meta: Dict[str, Any], data: Dict[str, Any]) -> None:
    tick = int(meta.get("tick"))

    patches = data.get("patch", [])
    if patches:
        rows_out: List[Tuple[Any, ...]] = []
        for p in patches:
            bbox = p.get("bbox", {}) or {}
            centroid = p.get("centroid", {}) or {}
            rows_out.append(
                (
                    tick,
                    p.get("patch_id"),
                    int(p.get("tiles", 0)),
                    int(p.get("wells", 0)),
                    int(p.get("total_amount", 0)),
                    float(centroid.get("x", 0.0)),
                    float(centroid.get("y", 0.0)),
                    float(bbox.get("min_x", 0.0)),
                    float(bbox.get("min_y", 0.0)),
                    float(bbox.get("max_x", 0.0)),
                    float(bbox.get("max_y", 0.0)),
                )
            )
        _execute_values_insert(
            con,
            "raw_crude_patches",
            [
                "tick",
                "patch_id",
                "tiles",
                "wells",
                "total_amount",
                "centroid_x",
                "centroid_y",
                "bbox_min_x",
                "bbox_min_y",
                "bbox_max_x",
                "bbox_max_y",
            ],
            rows_out,
        )

    rows = data.get("rows", [])
    if rows:
        rows_out = []
        for r in rows:
            tile = r.get("tile", {}) or {}
            pos = r.get("position", {}) or {}
            rows_out.append(
                (
                    tick,
                    r.get("patch_id"),
                    r.get("resource_name"),
                    int(tile.get("x", 0)),
                    int(tile.get("y", 0)),
                    int(math.floor(float(pos.get("x", 0.0)))),
                    int(math.floor(float(pos.get("y", 0.0)))),
                    int(r.get("amount", 0)),
                )
            )
        _execute_values_insert(
            con,
            "raw_crude_tiles",
            [
                "tick",
                "patch_id",
                "resource_name",
                "tile_x",
                "tile_y",
                "pos_x",
                "pos_y",
                "amount",
            ],
            rows_out,
        )


def _load_water_v1(con: Connection, path: str, meta: Dict[str, Any], data: Dict[str, Any]) -> None:
    tick = int(meta.get("tick"))

    patches = data.get("patch", [])
    if patches:
        rows_out: List[Tuple[Any, ...]] = []
        for p in patches:
            bbox = p.get("bbox", {}) or {}
            centroid = p.get("centroid", {}) or {}
            rows_out.append(
                (
                    tick,
                    p.get("patch_id"),
                    int(p.get("tiles", 0)),
                    float(centroid.get("x", 0.0)),
                    float(centroid.get("y", 0.0)),
                    float(bbox.get("min_x", 0.0)),
                    float(bbox.get("min_y", 0.0)),
                    float(bbox.get("max_x", 0.0)),
                    float(bbox.get("max_y", 0.0)),
                )
            )
        _execute_values_insert(
            con,
            "raw_water_patches",
            [
                "tick",
                "patch_id",
                "tiles",
                "centroid_x",
                "centroid_y",
                "bbox_min_x",
                "bbox_min_y",
                "bbox_max_x",
                "bbox_max_y",
            ],
            rows_out,
        )

    rows = data.get("rows", [])
    if rows:
        rows_out = []
        for r in rows:
            rows_out.append(
                (
                    tick,
                    r.get("patch_id"),
                    int(r.get("x", 0)),
                    int(r.get("y", 0)),
                    int(r.get("len", 0)),
                    int(r.get("tile_count", 0)),
                )
            )
        _execute_values_insert(
            con,
            "raw_water_tiles",
            [
                "tick",
                "patch_id",
                "tile_x",
                "tile_y",
                "len",
                "tile_count",
            ],
            rows_out,
        )


# Dispatch table
_LOADER_BY_VERSION = {
    SCHEMA_BELTS_V2: _load_belts_v2,
    SCHEMA_ENTITIES_V3: _load_entities_v3,
    SCHEMA_RESOURCES_V1: _load_resources_v1,
    SCHEMA_CRUDE_V1: _load_crude_v1,
    SCHEMA_WATER_V1: _load_water_v1,
}


def load_snapshot_file(con: Connection, path: str) -> Optional[str]:
    """Load a single JSON snapshot. Returns the schema_version used or None."""
    with open(path, "r") as f:
        payload = json.load(f)

    meta = payload.get("meta", {})
    data = payload.get("data", {})
    version = meta.get("schema_version")

    fn = _LOADER_BY_VERSION.get(version)
    if not fn:
        raise ValueError(f"Unsupported schema_version: {version} in {path}")

    fn(con, path, meta, data)
    return str(version)


def load_snapshot_dir(con: Connection, directory: str, clear_existing: bool = True) -> List[Tuple[str, str]]:
    """Load all *.json snapshots from a directory. Returns list of (file, version)."""
    if clear_existing:
        print("Clearing existing data from raw tables...")
        clear_raw_tables(con)
        print("Existing data cleared.")
    
    loaded: List[Tuple[str, str]] = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        version = load_snapshot_file(con, path)
        if version:
            loaded.append((name, version))
    return loaded



# -----------------------------
# CLI helper (optional)
# -----------------------------
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Load Factorio snapshot JSONs into PostgreSQL raw tables.")
    ap.add_argument("snapshot_dir", help="Directory of *.json snapshots")
    ap.add_argument("--dsn", dest="dsn", default=DEFAULT_PG_DSN, help="PostgreSQL DSN (default uses PG_* env: user, password, host, port, db)")
    ap.add_argument("--no-clear", dest="no_clear", action="store_true", help="Skip clearing existing data before loading")
    args = ap.parse_args()

    con = connect_db(args.dsn)
    ensure_schema(con)
    loaded = load_snapshot_dir(con, args.snapshot_dir, clear_existing=not args.no_clear)
    print(f"Loaded {len(loaded)} snapshots into PostgreSQL")
