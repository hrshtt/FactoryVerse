"""
DuckDB snapshot loader + view/materialization layer for Factorio snapshots.

Goals
-----
- Ingest raw JSON snapshots into stable staging tables (raw_*).
- Create gameplay-sensible views & macros that a text-only LLM can query
  to emulate the Factorio gameplay loop (global dashboards + local queries).
- Keep it maintainable & DRY: centralized schema, versioned loaders, small helpers.

Usage (example)
---------------
from FactoryVerse.services.duckdb.load_snapshots import (
    connect_db, ensure_schema, load_snapshot_dir, create_views_and_macros
)

con = connect_db("factoryverse.duckdb")
ensure_schema(con)
load_snapshot_dir(con, "/path/to/snaps/")
create_views_and_macros(con)

# Done. Use the SQL views/macros from your agent code.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import duckdb  # type: ignore
import pandas as pd

# -----------------------------
# Constants & helpers
# -----------------------------

DEFAULT_DB_PATH = os.environ.get("FACTORYVERSE_DUCKDB", "factoryverse.duckdb")

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

def connect_db(db_path: str = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open or create the DuckDB database."""
    con = duckdb.connect(db_path)
    con.execute("PRAGMA threads=8;")
    return con


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create raw tables (idempotent)."""
    # raw_belts
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_belts (
            tick                BIGINT,
            surface             VARCHAR,
            unit_number         BIGINT,
            name                VARCHAR,
            type                VARCHAR,
            pos_x               DOUBLE,
            pos_y               DOUBLE,
            direction           INTEGER,
            direction_name      VARCHAR,
            item_lines          JSON,            -- JSON payload: per-lane items
            neigh_inputs        INT[],           -- upstream unit_numbers
            neigh_outputs       INT[],           -- downstream unit_numbers
            chunk_x             INTEGER,
            chunk_y             INTEGER
        );
        """
    )

    # raw_entities (base footprint) + auxiliary per-subsystem tables
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_entities (
            tick                BIGINT,
            surface             VARCHAR,
            unit_number         BIGINT,
            name                VARCHAR,
            type                VARCHAR,
            force               VARCHAR,
            pos_x               DOUBLE,
            pos_y               DOUBLE,
            direction           INTEGER,
            direction_name      VARCHAR,
            orientation         DOUBLE,
            orientation_name    VARCHAR,
            status              INTEGER,
            status_name         VARCHAR,
            bbox_min_x          DOUBLE,
            bbox_min_y          DOUBLE,
            bbox_max_x          DOUBLE,
            bbox_max_y          DOUBLE,
            sel_min_x           DOUBLE,
            sel_min_y           DOUBLE,
            sel_max_x           DOUBLE,
            sel_max_y           DOUBLE,
            chunk_x             INTEGER,
            chunk_y             INTEGER
        );
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_entity_fluids (
            tick            BIGINT,
            surface         VARCHAR,
            unit_number     BIGINT,
            fluids          JSON,      -- list of fluid boxes (name, amount, capacity, temperature)
            chunk_x         INTEGER,
            chunk_y         INTEGER
        );
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_entity_inserter (
            tick                BIGINT,
            surface             VARCHAR,
            unit_number         BIGINT,   -- inserter id
            pickup_x            DOUBLE,
            pickup_y            DOUBLE,
            drop_x              DOUBLE,
            drop_y              DOUBLE,
            pickup_target_unit  BIGINT,
            drop_target_unit    BIGINT,
            chunk_x             INTEGER,
            chunk_y             INTEGER
        );
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_entity_electric (
            tick                BIGINT,
            surface             VARCHAR,
            unit_number         BIGINT,
            electric_network_id BIGINT,
            buffer_size         DOUBLE,
            energy              DOUBLE,
            chunk_x             INTEGER,
            chunk_y             INTEGER
        );
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_entity_crafting (
            tick                BIGINT,
            surface             VARCHAR,
            unit_number         BIGINT,
            recipe              VARCHAR,
            crafting_progress   DOUBLE,
            chunk_x             INTEGER,
            chunk_y             INTEGER
        );
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_entity_burner (
            tick            BIGINT,
            surface         VARCHAR,
            unit_number     BIGINT,
            burner_json     JSON,      -- fuel inventories, etc.
            chunk_x         INTEGER,
            chunk_y         INTEGER
        );
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_entity_inventory (
            tick            BIGINT,
            surface         VARCHAR,
            unit_number     BIGINT,
            inventories     JSON,
            chunk_x         INTEGER,
            chunk_y         INTEGER
        );
        """
    )

    # resources (solid)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_resource_patches (
            tick            BIGINT,
            surface         VARCHAR,
            patch_id        VARCHAR,
            resource_name   VARCHAR,
            tiles           INTEGER,
            total_amount    BIGINT,
            centroid_x      DOUBLE,
            centroid_y      DOUBLE,
            bbox_min_x      DOUBLE,
            bbox_min_y      DOUBLE,
            bbox_max_x      DOUBLE,
            bbox_max_y      DOUBLE
        );
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_resource_tiles (
            tick            BIGINT,
            surface         VARCHAR,
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
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_crude_patches (
            tick            BIGINT,
            surface         VARCHAR,
            patch_id        VARCHAR,
            tiles           INTEGER,
            wells           INTEGER,
            total_amount    BIGINT,
            centroid_x      DOUBLE,
            centroid_y      DOUBLE,
            bbox_min_x      DOUBLE,
            bbox_min_y      DOUBLE,
            bbox_max_x      DOUBLE,
            bbox_max_y      DOUBLE
        );
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_crude_tiles (
            tick            BIGINT,
            surface         VARCHAR,
            patch_id        VARCHAR,
            resource_name   VARCHAR,
            tile_x          INTEGER,
            tile_y          INTEGER,
            pos_x           DOUBLE,
            pos_y           DOUBLE,
            amount          BIGINT
        );
        """
    )

    # water
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_water_patches (
            tick            BIGINT,
            surface         VARCHAR,
            patch_id        VARCHAR,
            tiles           INTEGER,
            centroid_x      DOUBLE,
            centroid_y      DOUBLE,
            bbox_min_x      DOUBLE,
            bbox_min_y      DOUBLE,
            bbox_max_x      DOUBLE,
            bbox_max_y      DOUBLE
        );
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_water_tiles (
            tick            BIGINT,
            surface         VARCHAR,
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


def _load_belts_v2(con: duckdb.DuckDBPyConnection, path: str, meta: Dict[str, Any], data: Dict[str, Any]) -> None:
    rows = data.get("rows", [])
    if not rows:
        return
    tick = int(meta.get("tick"))
    surface = str(meta.get("surface"))

    recs: List[Dict[str, Any]] = []
    for r in rows:
        bn = r.get("belt_neighbours", {}) or {}
        inputs = _listify(bn.get("inputs"))
        outputs = _listify(bn.get("outputs"))
        pos = r.get("position", {}) or {}
        chunk = r.get("chunk", {}) or {}
        recs.append(
            {
                "tick": tick,
                "surface": surface,
                "unit_number": int(r.get("unit_number")),
                "name": r.get("name"),
                "type": r.get("type"),
                "pos_x": float(pos.get("x")),
                "pos_y": float(pos.get("y")),
                "direction": int(r.get("direction", 0)),
                "direction_name": r.get("direction_name"),
                # keep item_lines as compact JSON string (DuckDB JSON typed on insert)
                "item_lines": json.dumps(r.get("item_lines", [])),
                "neigh_inputs": inputs,
                "neigh_outputs": outputs,
                "chunk_x": int(chunk.get("x", 0)),
                "chunk_y": int(chunk.get("y", 0)),
            }
        )

    df = pd.DataFrame.from_records(recs)
    con.register("_df_belts", df)
    con.execute(
        """
        INSERT INTO raw_belts
        SELECT
            tick,
            surface,
            unit_number,
            name,
            type,
            pos_x,
            pos_y,
            direction,
            direction_name,
            item_lines::JSON,
            neigh_inputs,
            neigh_outputs,
            chunk_x,
            chunk_y
        FROM _df_belts;
        """
    )
    con.unregister("_df_belts")


def _load_entities_v3(con: duckdb.DuckDBPyConnection, path: str, meta: Dict[str, Any], data: Dict[str, Any]) -> None:
    tick = int(meta.get("tick"))
    surface = str(meta.get("surface"))

    def _entity_rows():
        rows = data.get("entity_rows", [])
        for r in rows:
            pos = r.get("position", {}) or {}
            bbox = r.get("bounding_box", {}) or {}
            sel = r.get("selection_box", {}) or {}
            chunk = r.get("chunk", {}) or {}
            yield {
                "tick": tick,
                "surface": surface,
                "unit_number": int(r.get("unit_number")),
                "name": r.get("name"),
                "type": r.get("type"),
                "force": r.get("force"),
                "pos_x": float(pos.get("x")),
                "pos_y": float(pos.get("y")),
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
                "surface": surface,
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
                "surface": surface,
                "unit_number": int(r.get("unit_number")),
                "pickup_x": float(pick.get("x", 0.0)),
                "pickup_y": float(pick.get("y", 0.0)),
                "drop_x": float(drop.get("x", 0.0)),
                "drop_y": float(drop.get("y", 0.0)),
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
                "surface": surface,
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
                "surface": surface,
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
                "surface": surface,
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
                "surface": surface,
                "unit_number": int(r.get("unit_number")),
                "inventories": json.dumps(r.get("inventories", {})),
                "chunk_x": int(chunk.get("x", 0)),
                "chunk_y": int(chunk.get("y", 0)),
            }

    # bulk insert helpers
    def _insert_df(table: str, rows_iter: Iterable[Dict[str, Any]]):
        lst = list(rows_iter)
        if not lst:
            return
        df = pd.DataFrame.from_records(lst)
        con.register("_df_tmp", df)
        cols = ", ".join(df.columns)
        con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _df_tmp;")
        con.unregister("_df_tmp")

    _insert_df("raw_entities", _entity_rows())
    _insert_df("raw_entity_fluids", _fluids_rows())
    _insert_df("raw_entity_inserter", _inserter_rows())
    _insert_df("raw_entity_electric", _electric_rows())
    _insert_df("raw_entity_crafting", _crafting_rows())
    _insert_df("raw_entity_burner", _burner_rows())
    _insert_df("raw_entity_inventory", _inventory_rows())


def _load_resources_v1(con: duckdb.DuckDBPyConnection, path: str, meta: Dict[str, Any], data: Dict[str, Any]) -> None:
    tick = int(meta.get("tick"))
    surface = str(meta.get("surface"))

    patches = data.get("patch", [])
    if patches:
        recs = []
        for p in patches:
            bbox = p.get("bbox", {}) or {}
            centroid = p.get("centroid", {}) or {}
            recs.append(
                {
                    "tick": tick,
                    "surface": surface,
                    "patch_id": p.get("patch_id"),
                    "resource_name": p.get("resource_name"),
                    "tiles": int(p.get("tiles", 0)),
                    "total_amount": int(p.get("total_amount", 0)),
                    "centroid_x": float(centroid.get("x", 0.0)),
                    "centroid_y": float(centroid.get("y", 0.0)),
                    "bbox_min_x": float(bbox.get("min_x", 0.0)),
                    "bbox_min_y": float(bbox.get("min_y", 0.0)),
                    "bbox_max_x": float(bbox.get("max_x", 0.0)),
                    "bbox_max_y": float(bbox.get("max_y", 0.0)),
                }
            )
        df = pd.DataFrame.from_records(recs)
        con.register("_df_res_p", df)
        con.execute(
            """
            INSERT INTO raw_resource_patches
            SELECT * FROM _df_res_p;
            """
        )
        con.unregister("_df_res_p")

    rows = data.get("rows", [])
    if rows:
        recs = []
        for r in rows:
            recs.append(
                {
                    "tick": tick,
                    "surface": surface,
                    "patch_id": r.get("patch_id"),
                    "resource_name": r.get("resource_name"),
                    "tile_x": int(r.get("x")),
                    "tile_y": int(r.get("y")),
                    "len": int(r.get("len", 0)),
                    "tile_count": int(r.get("tile_count", 0)),
                    "sum_amount": int(r.get("sum_amount", 0)),
                }
            )
        df = pd.DataFrame.from_records(recs)
        con.register("_df_res_r", df)
        con.execute(
            """
            INSERT INTO raw_resource_tiles
            SELECT * FROM _df_res_r;
            """
        )
        con.unregister("_df_res_r")


def _load_crude_v1(con: duckdb.DuckDBPyConnection, path: str, meta: Dict[str, Any], data: Dict[str, Any]) -> None:
    tick = int(meta.get("tick"))
    surface = str(meta.get("surface"))

    patches = data.get("patch", [])
    if patches:
        recs = []
        for p in patches:
            bbox = p.get("bbox", {}) or {}
            centroid = p.get("centroid", {}) or {}
            recs.append(
                {
                    "tick": tick,
                    "surface": surface,
                    "patch_id": p.get("patch_id"),
                    "tiles": int(p.get("tiles", 0)),
                    "wells": int(p.get("wells", 0)),
                    "total_amount": int(p.get("total_amount", 0)),
                    "centroid_x": float(centroid.get("x", 0.0)),
                    "centroid_y": float(centroid.get("y", 0.0)),
                    "bbox_min_x": float(bbox.get("min_x", 0.0)),
                    "bbox_min_y": float(bbox.get("min_y", 0.0)),
                    "bbox_max_x": float(bbox.get("max_x", 0.0)),
                    "bbox_max_y": float(bbox.get("max_y", 0.0)),
                }
            )
        df = pd.DataFrame.from_records(recs)
        con.register("_df_cru_p", df)
        con.execute("INSERT INTO raw_crude_patches SELECT * FROM _df_cru_p;")
        con.unregister("_df_cru_p")

    rows = data.get("rows", [])
    if rows:
        recs = []
        for r in rows:
            tile = r.get("tile", {}) or {}
            pos = r.get("position", {}) or {}
            recs.append(
                {
                    "tick": tick,
                    "surface": surface,
                    "patch_id": r.get("patch_id"),
                    "resource_name": r.get("resource_name"),
                    "tile_x": int(tile.get("x", 0)),
                    "tile_y": int(tile.get("y", 0)),
                    "pos_x": float(pos.get("x", 0.0)),
                    "pos_y": float(pos.get("y", 0.0)),
                    "amount": int(r.get("amount", 0)),
                }
            )
        df = pd.DataFrame.from_records(recs)
        con.register("_df_cru_r", df)
        con.execute("INSERT INTO raw_crude_tiles SELECT * FROM _df_cru_r;")
        con.unregister("_df_cru_r")


def _load_water_v1(con: duckdb.DuckDBPyConnection, path: str, meta: Dict[str, Any], data: Dict[str, Any]) -> None:
    tick = int(meta.get("tick"))
    surface = str(meta.get("surface"))

    patches = data.get("patch", [])
    if patches:
        recs = []
        for p in patches:
            bbox = p.get("bbox", {}) or {}
            centroid = p.get("centroid", {}) or {}
            recs.append(
                {
                    "tick": tick,
                    "surface": surface,
                    "patch_id": p.get("patch_id"),
                    "tiles": int(p.get("tiles", 0)),
                    "centroid_x": float(centroid.get("x", 0.0)),
                    "centroid_y": float(centroid.get("y", 0.0)),
                    "bbox_min_x": float(bbox.get("min_x", 0.0)),
                    "bbox_min_y": float(bbox.get("min_y", 0.0)),
                    "bbox_max_x": float(bbox.get("max_x", 0.0)),
                    "bbox_max_y": float(bbox.get("max_y", 0.0)),
                }
            )
        df = pd.DataFrame.from_records(recs)
        con.register("_df_wat_p", df)
        con.execute("INSERT INTO raw_water_patches SELECT * FROM _df_wat_p;")
        con.unregister("_df_wat_p")

    rows = data.get("rows", [])
    if rows:
        recs = []
        for r in rows:
            recs.append(
                {
                    "tick": tick,
                    "surface": surface,
                    "patch_id": r.get("patch_id"),
                    "tile_x": int(r.get("x", 0)),
                    "tile_y": int(r.get("y", 0)),
                    "len": int(r.get("len", 0)),
                    "tile_count": int(r.get("tile_count", 0)),
                }
            )
        df = pd.DataFrame.from_records(recs)
        con.register("_df_wat_r", df)
        con.execute("INSERT INTO raw_water_tiles SELECT * FROM _df_wat_r;")
        con.unregister("_df_wat_r")


# Dispatch table
_LOADER_BY_VERSION = {
    SCHEMA_BELTS_V2: _load_belts_v2,
    SCHEMA_ENTITIES_V3: _load_entities_v3,
    SCHEMA_RESOURCES_V1: _load_resources_v1,
    SCHEMA_CRUDE_V1: _load_crude_v1,
    SCHEMA_WATER_V1: _load_water_v1,
}


def load_snapshot_file(con: duckdb.DuckDBPyConnection, path: str) -> Optional[str]:
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


def load_snapshot_dir(con: duckdb.DuckDBPyConnection, directory: str) -> List[Tuple[str, str]]:
    """Load all *.json snapshots from a directory. Returns list of (file, version)."""
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
# Views & Macros (LLM-friendly)
# -----------------------------

VIEW_SQL: Dict[str, str] = {}

# 1) Belt flow edges (graph of neighbor links)
VIEW_SQL["view_belt_flow_edges"] = r"""
CREATE OR REPLACE VIEW view_belt_flow_edges AS
WITH edges AS (
    SELECT
        b.tick,
        b.surface,
        b.unit_number AS from_unit,
        u.to_unit AS to_unit,
        b.direction_name AS dir_from,
        b.item_lines AS items
    FROM raw_belts b, UNNEST(b.neigh_outputs) AS u(to_unit)
)
SELECT e.tick,
       e.surface,
       e.from_unit,
       e.to_unit,
       e.items,
       e.dir_from,
       b2.direction_name AS dir_to
FROM edges e
LEFT JOIN raw_belts b2
  ON b2.tick = e.tick AND b2.surface = e.surface AND b2.unit_number = e.to_unit;
"""

# 2) Belt degrees per node (helpers for components/balancer views)
VIEW_SQL["view_belt_degrees"] = r"""
CREATE OR REPLACE VIEW view_belt_degrees AS
WITH outd AS (
  SELECT tick, surface, from_unit AS unit, count(*) AS out_degree
  FROM view_belt_flow_edges GROUP BY 1,2,3
), ind AS (
  SELECT tick, surface, to_unit   AS unit, count(*) AS in_degree
  FROM view_belt_flow_edges GROUP BY 1,2,3
)
SELECT n.tick, n.surface, n.unit_number AS unit,
       COALESCE(ind.in_degree,0) AS in_degree,
       COALESCE(outd.out_degree,0) AS out_degree
FROM raw_belts n
LEFT JOIN ind  ON ind.tick=n.tick AND ind.surface=n.surface AND ind.unit=n.unit_number
LEFT JOIN outd ON outd.tick=n.tick AND outd.surface=n.surface AND outd.unit=n.unit_number;
"""

# 3) Belt connected components (what humans visually "trace")
VIEW_SQL["view_belt_components"] = r"""
CREATE OR REPLACE VIEW view_belt_components AS
WITH RECURSIVE
  undirected AS (
    SELECT tick, surface, from_unit AS a, to_unit AS b FROM view_belt_flow_edges
    UNION ALL
    SELECT tick, surface, to_unit AS a, from_unit AS b FROM view_belt_flow_edges
  ),
  nodes AS (
    SELECT DISTINCT tick, surface, unit_number AS u FROM raw_belts
  ),
  seed AS (
    SELECT tick, surface, u, u AS root FROM nodes
  ),
  spread AS (
    SELECT * FROM seed
    UNION
    SELECT u.tick, u.surface, und.b, s.root
    FROM spread s
    JOIN undirected und ON und.tick=s.tick AND und.surface=s.surface AND und.a=s.u
    JOIN nodes u        ON u.tick=und.tick AND u.surface=und.surface AND u.u=und.b
  ),
  canonical AS (
    SELECT tick, surface, u, MIN(root) AS root
    FROM spread
    GROUP BY 1,2,3
  ),
  comp AS (
    SELECT c.tick, c.surface, c.root AS belt_component_id,
           COUNT(*) AS belt_count,
           COUNT(*) AS length_tiles
    FROM canonical c
    GROUP BY 1,2,3
  ),
  items AS (
    SELECT c.tick, c.surface, c.root AS belt_component_id,
           LIST(b.item_lines) AS items_sample
    FROM canonical c
    JOIN raw_belts b
      ON b.tick=c.tick AND b.surface=c.surface AND b.unit_number=c.u
    GROUP BY 1,2,3
  ),
  ends AS (
    SELECT d.tick, d.surface, c.root AS belt_component_id,
           LIST(d.unit) FILTER (WHERE d.in_degree = 0) AS sources,
           LIST(d.unit) FILTER (WHERE d.out_degree = 0) AS sinks
    FROM canonical c
    JOIN view_belt_degrees d
      ON d.tick=c.tick AND d.surface=c.surface AND d.unit=c.u
    GROUP BY 1,2,3
  )
SELECT comp.tick, comp.surface, comp.belt_component_id,
       comp.belt_count, comp.length_tiles,
       items.items_sample, ends.sources, ends.sinks
FROM comp
JOIN items USING (tick, surface, belt_component_id)
JOIN ends  USING (tick, surface, belt_component_id);
"""

# 4) Resource/Oil/Water summaries (map-level planning)
VIEW_SQL["view_resource_patch_summary"] = r"""
CREATE OR REPLACE VIEW view_resource_patch_summary AS
SELECT tick, surface, patch_id, resource_name,
       tiles, total_amount,
       centroid_x, centroid_y,
       bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y
FROM raw_resource_patches;
"""

VIEW_SQL["view_crude_patch_summary"] = r"""
CREATE OR REPLACE VIEW view_crude_patch_summary AS
SELECT tick, surface, patch_id,
       wells, tiles, total_amount,
       centroid_x, centroid_y,
       bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y
FROM raw_crude_patches;
"""

VIEW_SQL["view_water_access"] = r"""
CREATE OR REPLACE VIEW view_water_access AS
WITH near AS (
  SELECT w.tick, w.surface, w.patch_id,
         MIN( (e.pos_x - w.centroid_x) * (e.pos_x - w.centroid_x)
             + (e.pos_y - w.centroid_y) * (e.pos_y - w.centroid_y) ) AS d2
  FROM raw_water_patches w
  LEFT JOIN raw_entities e
    ON e.tick=w.tick AND e.surface=w.surface
  GROUP BY 1,2,3
)
SELECT w.tick, w.surface, w.patch_id, w.tiles,
       w.centroid_x, w.centroid_y,
       w.bbox_min_x, w.bbox_min_y, w.bbox_max_x, w.bbox_max_y,
       CASE WHEN near.d2 IS NULL THEN NULL ELSE sqrt(near.d2) END AS nearest_entity_distance
FROM raw_water_patches w
LEFT JOIN near
  ON near.tick=w.tick AND near.surface=w.surface AND near.patch_id=w.patch_id;
"""

# 5) Chunk activity heatmap-ish
VIEW_SQL["view_chunk_activity"] = r"""
CREATE OR REPLACE VIEW view_chunk_activity AS
WITH belts AS (
  SELECT tick, surface, chunk_x, chunk_y, COUNT(*) AS belt_count
  FROM raw_belts GROUP BY 1,2,3,4
), ents AS (
  SELECT tick, surface, chunk_x, chunk_y,
         COUNT(*)                                     AS entity_count,
         SUM(CASE WHEN name LIKE '%pipe%' THEN 1 ELSE 0 END) AS pipe_count,
         SUM(CASE WHEN name LIKE '%steam-engine%' THEN 1 ELSE 0 END) AS generator_count
  FROM raw_entities GROUP BY 1,2,3,4
)
SELECT
  COALESCE(belts.tick, ents.tick)     AS tick,
  COALESCE(belts.surface, ents.surface) AS surface,
  COALESCE(belts.chunk_x, ents.chunk_x) AS chunk_x,
  COALESCE(belts.chunk_y, ents.chunk_y) AS chunk_y,
  COALESCE(belts.belt_count, 0) AS belt_count,
  COALESCE(ents.entity_count, 0) AS entity_count,
  COALESCE(ents.pipe_count, 0) AS pipe_count,
  COALESCE(ents.generator_count, 0) AS generator_count
FROM belts
FULL OUTER JOIN ents
  ON belts.tick=ents.tick AND belts.surface=ents.surface
 AND belts.chunk_x=ents.chunk_x AND belts.chunk_y=ents.chunk_y;
"""

# 6) Inserter links (machine IO edges)
VIEW_SQL["view_inserter_links"] = r"""
CREATE OR REPLACE VIEW view_inserter_links AS
SELECT tick, surface,
       unit_number AS inserter_id,
       pickup_target_unit AS from_unit,
       drop_target_unit   AS to_unit,
       pickup_x, pickup_y, drop_x, drop_y
FROM raw_entity_inserter;
"""

# 7) Balancer/junction candidates (where splits/merges happen)
VIEW_SQL["view_balancer_candidates"] = r"""
CREATE OR REPLACE VIEW view_balancer_candidates AS
WITH mix AS (
  -- Extract distinct item names per belt across its lanes
  SELECT b.tick, b.surface, b.unit_number AS unit,
         COUNT(DISTINCT json_extract_string(i.value, '$.name')) AS distinct_item_names
  FROM raw_belts b,
       json_each(b.item_lines) AS l,
       json_each(json_extract(l.value, '$.items')) AS i
  GROUP BY 1,2,3
), d AS (
  SELECT * FROM view_belt_degrees
)
SELECT d.tick, d.surface, d.unit AS junction_unit,
       d.in_degree, d.out_degree,
       CASE WHEN COALESCE(mix.distinct_item_names, 0) > 1 THEN TRUE ELSE FALSE END AS lanes_unbalanced
FROM d
LEFT JOIN mix
  ON mix.tick=d.tick AND mix.surface=d.surface AND mix.unit=d.unit
WHERE d.in_degree > 1 OR d.out_degree > 1;
"""

# Optional: simple machine IO aggregation per target/source
VIEW_SQL["view_machine_io"] = r"""
CREATE OR REPLACE VIEW view_machine_io AS
WITH inbound AS (
  SELECT tick, surface, to_unit   AS unit, LIST(DISTINCT inserter_id) AS inbound_inserters,
         LIST(DISTINCT from_unit) AS pulls_from
  FROM view_inserter_links WHERE to_unit IS NOT NULL
  GROUP BY 1,2,3
), outbound AS (
  SELECT tick, surface, from_unit AS unit, LIST(DISTINCT inserter_id) AS outbound_inserters,
         LIST(DISTINCT to_unit)   AS pushes_to
  FROM view_inserter_links WHERE from_unit IS NOT NULL
  GROUP BY 1,2,3
)
SELECT e.tick, e.surface, e.unit_number AS unit,
       COALESCE(inbound.inbound_inserters,  []) AS inbound_inserters,
       COALESCE(inbound.pulls_from,          []) AS pulls_from,
       COALESCE(outbound.outbound_inserters, []) AS outbound_inserters,
       COALESCE(outbound.pushes_to,          []) AS pushes_to
FROM raw_entities e
LEFT JOIN inbound  ON inbound.tick=e.tick AND inbound.surface=e.surface AND inbound.unit=e.unit_number
LEFT JOIN outbound ON outbound.tick=e.tick AND outbound.surface=e.surface AND outbound.unit=e.unit_number;
"""


MACRO_SQL: Dict[str, str] = {}

# Local thinking primitives as SQL macros
MACRO_SQL["nearest_entities"] = r"""
CREATE OR REPLACE MACRO nearest_entities(px, py, radius, tickv, surf) AS (
  SELECT unit_number, name, type, pos_x, pos_y,
         sqrt((pos_x - px) * (pos_x - px) + (pos_y - py) * (pos_y - py)) AS dist
  FROM raw_entities
  WHERE tick = tickv AND surface = surf
    AND pos_x BETWEEN px - radius AND px + radius
    AND pos_y BETWEEN py - radius AND py + radius
  ORDER BY dist ASC
);
"""

MACRO_SQL["trace_belt"] = r"""
CREATE OR REPLACE MACRO trace_belt(start_unit, tickv, surf, max_steps) AS (
  WITH RECURSIVE walk(step, unit) AS (
    SELECT 0, start_unit
    UNION ALL
    SELECT step + 1, e.to_unit
    FROM view_belt_flow_edges e
    JOIN walk w ON e.tick = tickv AND e.surface = surf AND e.from_unit = w.unit
    WHERE step < max_steps AND e.to_unit IS NOT NULL
  )
  SELECT w.step, w.unit AS unit_number, b.direction_name, b.item_lines
  FROM walk w
  JOIN raw_belts b ON b.tick = tickv AND b.surface = surf AND b.unit_number = w.unit
  ORDER BY w.step
);
"""

MACRO_SQL["trace_belt_backwards"] = r"""
CREATE OR REPLACE MACRO trace_belt_backwards(end_unit, tickv, surf, max_steps) AS (
  WITH RECURSIVE walk(step, unit) AS (
    SELECT 0, end_unit
    UNION ALL
    SELECT step + 1, e.from_unit
    FROM view_belt_flow_edges e
    JOIN walk w ON e.tick = tickv AND e.surface = surf AND e.to_unit = w.unit
    WHERE step < max_steps AND e.from_unit IS NOT NULL
  )
  SELECT w.step, w.unit AS unit_number, b.direction_name, b.item_lines
  FROM walk w
  JOIN raw_belts b ON b.tick = tickv AND b.surface = surf AND b.unit_number = w.unit
  ORDER BY w.step
);
"""

MACRO_SQL["lane_mix"] = r"""
CREATE OR REPLACE MACRO lane_mix(component_id, tickv, surf) AS TABLE (
  WITH members AS (
    SELECT bc.tick, bc.surface, bc.belt_component_id, c.u AS unit
    FROM (
      -- re-expose canonical members from view_belt_components using its aggregation
      SELECT tick, surface, belt_component_id FROM view_belt_components
    ) bc
    JOIN (
      -- rebuild mapping (tick,surface,unit)->root to avoid storing another table
      WITH RECURSIVE undirected AS (
        SELECT tick, surface, from_unit AS a, to_unit AS b FROM view_belt_flow_edges
        UNION ALL
        SELECT tick, surface, to_unit AS a, from_unit AS b FROM view_belt_flow_edges
      ), nodes AS (
        SELECT DISTINCT tick, surface, unit_number AS u FROM raw_belts
      ), seed AS (
        SELECT tick, surface, u, u AS root FROM nodes
      ), spread AS (
        SELECT * FROM seed
        UNION
        SELECT u.tick, u.surface, und.b, s.root
        FROM spread s
        JOIN undirected und ON und.tick=s.tick AND und.surface=s.surface AND und.a=s.u
        JOIN nodes u        ON u.tick=und.tick AND u.surface=und.surface AND u.u=und.b
      )
      SELECT tick, surface, u, MIN(root) AS root
      FROM spread GROUP BY 1,2,3
    ) c
      ON c.tick=bc.tick AND c.surface=bc.surface AND c.root=bc.belt_component_id
  )
  SELECT b.unit_number,
         json_group_array(i_name) AS item_names
  FROM members m
  JOIN raw_belts b ON b.tick=m.tick AND b.surface=m.surface AND b.unit_number=m.unit
  LEFT JOIN (
    SELECT b.unit_number,
           json_extract_string(i.value, '$.name') AS i_name
    FROM raw_belts b,
         json_each(b.item_lines) AS l,
         json_each(json_extract(l.value, '$.items')) AS i
  ) j ON j.unit_number = b.unit_number
  WHERE m.belt_component_id = component_id AND m.tick = tickv AND m.surface = surf
  GROUP BY b.unit_number
);
"""


def create_views_and_macros(con: duckdb.DuckDBPyConnection) -> None:
    """Materialize or refresh all views and macros."""
    for name, sql in VIEW_SQL.items():
        con.execute(sql)
    for name, sql in MACRO_SQL.items():
        con.execute(sql)


# -----------------------------
# CLI helper (optional)
# -----------------------------
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Load Factorio snapshot JSONs into DuckDB and create views/macros.")
    ap.add_argument("snapshot_dir", help="Directory of *.json snapshots")
    ap.add_argument("--db", dest="db", default=DEFAULT_DB_PATH, help="DuckDB path (default: factoryverse.duckdb)")
    args = ap.parse_args()

    con = connect_db(args.db)
    ensure_schema(con)
    loaded = load_snapshot_dir(con, args.snapshot_dir)
    create_views_and_macros(con)
    print(f"Loaded {len(loaded)} snapshots into {args.db}")
