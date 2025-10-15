"""
DuckDB views and macros for generative buildable-area discovery.

This module complements `load_snapshots.py` by providing spatial reasoning
helpers built purely from existing raw_* tables (no new persistent tables):

- v_occupied_space: unified rectangles for anything occupying space
- v_explored_chunks: chunks inferred as explored from presence of data
- Macros:
  - generate_buildable_candidates_ctx(tickv, surf, step, footprint_w, footprint_h, expand_chunks)
  - generate_buildable_candidates()  -- latest tick on 'nauvis', defaults
  - find_buildable_near_entity_ctx(entity_id, radius, step, tickv, surf, footprint_w, footprint_h)
  - find_buildable_near_entity(entity_id, radius, step) -- auto context
  - describe_area_ctx(px, py, radius, tickv, surf)
  - describe_area(px, py, radius) -- auto context

Usage (example)
---------------
from FactoryVerse.services.duckdb.buildable_areas import (
    connect_db, create_buildable_views_and_macros
)

con = connect_db()
create_buildable_views_and_macros(con)

# Examples (no-arg versions use latest tick on 'nauvis'):
# con.execute("SELECT * FROM generate_buildable_candidates() WHERE is_buildable").fetchdf()
# con.execute("SELECT * FROM find_buildable_near_entity(12345, 20.0, 3.0)").fetchdf()
# con.execute("SELECT * FROM describe_area(100, 50, 15.0)").fetchdf()
"""
from __future__ import annotations

from typing import Dict

import duckdb  # type: ignore


DEFAULT_DB_PATH = "factoryverse.duckdb"


def connect_db(db_path: str = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(db_path)
    con.execute("PRAGMA threads=8;")
    return con


# ---------------------------------
# Minimal schema bootstrap (optional)
# ---------------------------------

def _ensure_min_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the raw_* tables required by views if they don't exist.
    Mirrors definitions in load_snapshots.ensure_schema for compatibility.
    """
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
            item_lines          JSON,
            neigh_inputs        INT[],
            neigh_outputs       INT[],
            chunk_x             INTEGER,
            chunk_y             INTEGER
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

# ---------------------------------
# Views
# ---------------------------------

VIEW_SQL: Dict[str, str] = {}


# Unified occupancy rectangles. Coordinates are axis-aligned [min_x,max_x] x [min_y,max_y].
# - Entities: selection box (falls back to bounding box)
# - Belts: approximate 1x1 around center position
# - Resource/Crude/Water tiles: exact 1x1 tiles
VIEW_SQL["v_occupied_space"] = r"""
CREATE OR REPLACE VIEW v_occupied_space AS
WITH ents AS (
  SELECT
    e.tick,
    e.surface,
    'entity'::VARCHAR AS kind,
    CAST(e.unit_number AS VARCHAR) AS ref_id,
    COALESCE(e.sel_min_x, e.bbox_min_x) AS min_x,
    COALESCE(e.sel_min_y, e.bbox_min_y) AS min_y,
    COALESCE(e.sel_max_x, e.bbox_max_x) AS max_x,
    COALESCE(e.sel_max_y, e.bbox_max_y) AS max_y
  FROM raw_entities e
), belts AS (
  SELECT
    b.tick,
    b.surface,
    'belt'::VARCHAR AS kind,
    CAST(b.unit_number AS VARCHAR) AS ref_id,
    (b.pos_x - 0.5) AS min_x,
    (b.pos_y - 0.5) AS min_y,
    (b.pos_x + 0.5) AS max_x,
    (b.pos_y + 0.5) AS max_y
  FROM raw_belts b
), res_tiles AS (
  SELECT
    r.tick,
    r.surface,
    'resource'::VARCHAR AS kind,
    (r.patch_id || ':' || CAST(r.tile_x AS VARCHAR) || ',' || CAST(r.tile_y AS VARCHAR)) AS ref_id,
    CAST(r.tile_x AS DOUBLE)       AS min_x,
    CAST(r.tile_y AS DOUBLE)       AS min_y,
    CAST(r.tile_x + 1 AS DOUBLE)   AS max_x,
    CAST(r.tile_y + 1 AS DOUBLE)   AS max_y
  FROM raw_resource_tiles r
), cru_tiles AS (
  SELECT
    c.tick,
    c.surface,
    'crude'::VARCHAR AS kind,
    (c.patch_id || ':' || CAST(c.tile_x AS VARCHAR) || ',' || CAST(c.tile_y AS VARCHAR)) AS ref_id,
    CAST(c.tile_x AS DOUBLE)       AS min_x,
    CAST(c.tile_y AS DOUBLE)       AS min_y,
    CAST(c.tile_x + 1 AS DOUBLE)   AS max_x,
    CAST(c.tile_y + 1 AS DOUBLE)   AS max_y
  FROM raw_crude_tiles c
), wat_tiles AS (
  SELECT
    w.tick,
    w.surface,
    'water'::VARCHAR AS kind,
    (w.patch_id || ':' || CAST(w.tile_x AS VARCHAR) || ',' || CAST(w.tile_y AS VARCHAR)) AS ref_id,
    CAST(w.tile_x AS DOUBLE)       AS min_x,
    CAST(w.tile_y AS DOUBLE)       AS min_y,
    CAST(w.tile_x + 1 AS DOUBLE)   AS max_x,
    CAST(w.tile_y + 1 AS DOUBLE)   AS max_y
  FROM raw_water_tiles w
)
SELECT * FROM ents
UNION ALL SELECT * FROM belts
UNION ALL SELECT * FROM res_tiles
UNION ALL SELECT * FROM cru_tiles
UNION ALL SELECT * FROM wat_tiles;
"""


VIEW_SQL["v_explored_chunks"] = r"""
CREATE OR REPLACE VIEW v_explored_chunks AS
WITH base AS (
  SELECT tick, surface, chunk_x, chunk_y FROM raw_entities
  UNION ALL
  SELECT tick, surface, chunk_x, chunk_y FROM raw_belts
  UNION ALL
  SELECT r.tick, r.surface, CAST(floor(r.tile_x / 32) AS INTEGER) AS chunk_x, CAST(floor(r.tile_y / 32) AS INTEGER) AS chunk_y FROM raw_resource_tiles r
  UNION ALL
  SELECT c.tick, c.surface, CAST(floor(c.tile_x / 32) AS INTEGER) AS chunk_x, CAST(floor(c.tile_y / 32) AS INTEGER) AS chunk_y FROM raw_crude_tiles c
  UNION ALL
  SELECT w.tick, w.surface, CAST(floor(w.tile_x / 32) AS INTEGER) AS chunk_x, CAST(floor(w.tile_y / 32) AS INTEGER) AS chunk_y FROM raw_water_tiles w
)
SELECT DISTINCT tick, surface, chunk_x, chunk_y FROM base;
"""


# Latest tick per surface helper view (for convenience macros without explicit ctx)
VIEW_SQL["v_latest_tick_surface"] = r"""
CREATE OR REPLACE VIEW v_latest_tick_surface AS
WITH ticks AS (
  SELECT tick, surface FROM raw_entities
  UNION ALL SELECT tick, surface FROM raw_belts
  UNION ALL SELECT tick, surface FROM raw_resource_tiles
  UNION ALL SELECT tick, surface FROM raw_crude_tiles
  UNION ALL SELECT tick, surface FROM raw_water_tiles
)
SELECT surface, MAX(tick) AS tick
FROM ticks
GROUP BY surface;
"""


# ---------------------------------
# Macros
# ---------------------------------

MACRO_SQL: Dict[str, str] = {}


MACRO_SQL["generate_buildable_candidates_ctx"] = r"""
CREATE OR REPLACE MACRO generate_buildable_candidates_ctx(tickv, surf, step, footprint_w, footprint_h, expand_chunks) AS TABLE (
  WITH occ0 AS (
    SELECT tick, surface, kind, ref_id, min_x, min_y, max_x, max_y
    FROM v_occupied_space WHERE tick = tickv AND surface = surf
  ), occ_bounds AS (
    SELECT *,
      CAST(floor(min_x / 32.0) AS BIGINT) AS cx0,
      CAST(floor((max_x - 1e-9) / 32.0) AS BIGINT) AS cx1,
      CAST(floor(min_y / 32.0) AS BIGINT) AS cy0,
      CAST(floor((max_y - 1e-9) / 32.0) AS BIGINT) AS cy1
    FROM occ0
  ), occ_idx AS (
    SELECT
      b.kind, b.ref_id, b.min_x, b.min_y, b.max_x, b.max_y,
      gx.cx AS chunk_x,
      gy.cy AS chunk_y
    FROM occ_bounds b,
         generate_series(b.cx0, b.cx1) AS gx(cx),
         generate_series(b.cy0, b.cy1) AS gy(cy)
  ), bbox AS (
    SELECT
      MIN(chunk_x) - expand_chunks AS min_cx,
      MAX(chunk_x) + expand_chunks AS max_cx,
      MIN(chunk_y) - expand_chunks AS min_cy,
      MAX(chunk_y) + expand_chunks AS max_cy
    FROM v_explored_chunks
    WHERE tick = tickv AND surface = surf
  ), bounds AS (
    SELECT
      CAST(floor((min_cx * 32) / step) AS BIGINT) AS ix0,
      CAST(floor(((max_cx + 1) * 32) / step) AS BIGINT) AS ix1,
      CAST(floor((min_cy * 32) / step) AS BIGINT) AS iy0,
      CAST(floor(((max_cy + 1) * 32) / step) AS BIGINT) AS iy1,
      CAST(step AS DOUBLE) AS step_d
    FROM bbox
  ), grid_i AS (
    SELECT ix, iy
    FROM bounds,
         generate_series(ix0, ix1) AS gx(ix),
         generate_series(iy0, iy1) AS gy(iy)
  ), grid AS (
    SELECT
      CAST(ix * step_d AS DOUBLE) AS px,
      CAST(iy * step_d AS DOUBLE) AS py,
      CAST(floor((ix * step_d) / 32.0) AS BIGINT) AS chunk_x,
      CAST(floor((iy * step_d) / 32.0) AS BIGINT) AS chunk_y
    FROM grid_i, bounds
  ), cand AS (
    SELECT
      px, py, chunk_x, chunk_y,
      (px - footprint_w / 2.0)  AS min_x,
      (py - footprint_h / 2.0)  AS min_y,
      (px + footprint_w / 2.0)  AS max_x,
      (py + footprint_h / 2.0)  AS max_y
    FROM grid
  ), blocked AS (
    SELECT
      c.px, c.py, c.chunk_x, c.chunk_y,
      COUNT(oi.kind)                         AS collisions,
      LIST(DISTINCT oi.kind)                 AS blocking_kinds
    FROM cand c
    LEFT JOIN occ_idx oi
      ON oi.chunk_x = c.chunk_x AND oi.chunk_y = c.chunk_y
     AND NOT (c.max_x < oi.min_x OR c.min_x > oi.max_x OR c.max_y < oi.min_y OR c.min_y > oi.max_y)
    GROUP BY 1,2,3,4
  )
  SELECT
    CAST(tickv AS BIGINT) AS tick,
    CAST(surf AS VARCHAR) AS surface,
    CAST(chunk_x AS INTEGER) AS chunk_x,
    CAST(chunk_y AS INTEGER) AS chunk_y,
    px, py,
    CASE WHEN collisions = 0 THEN TRUE ELSE FALSE END AS is_buildable,
    COALESCE(blocking_kinds, []) AS blocking_kinds
  FROM blocked
);
"""


MACRO_SQL["generate_buildable_candidates"] = r"""
CREATE OR REPLACE MACRO generate_buildable_candidates() AS TABLE (
  WITH ctx AS (
    SELECT tick, surface FROM v_latest_tick_surface WHERE surface = 'nauvis' ORDER BY tick DESC LIMIT 1
  )
  SELECT * FROM generate_buildable_candidates_ctx(
    (SELECT tick FROM ctx),
    (SELECT surface FROM ctx),
    2.0,   -- step tiles
    1.0,   -- footprint_w
    1.0,   -- footprint_h
    1      -- expand_chunks
  )
);
"""


MACRO_SQL["find_buildable_near_entity_ctx"] = r"""
CREATE OR REPLACE MACRO find_buildable_near_entity_ctx(entity_id, radius, step, tickv, surf, footprint_w, footprint_h) AS TABLE (
  WITH occ0 AS (
    SELECT tick, surface, kind, ref_id, min_x, min_y, max_x, max_y
    FROM v_occupied_space WHERE tick = tickv AND surface = surf
  ), occ_bounds AS (
    SELECT *,
      CAST(floor(min_x / 32.0) AS BIGINT) AS cx0,
      CAST(floor((max_x - 1e-9) / 32.0) AS BIGINT) AS cx1,
      CAST(floor(min_y / 32.0) AS BIGINT) AS cy0,
      CAST(floor((max_y - 1e-9) / 32.0) AS BIGINT) AS cy1
    FROM occ0
  ), occ_idx AS (
    SELECT
      b.kind, b.ref_id, b.min_x, b.min_y, b.max_x, b.max_y,
      gx.cx AS chunk_x,
      gy.cy AS chunk_y
    FROM occ_bounds b,
         generate_series(b.cx0, b.cx1) AS gx(cx),
         generate_series(b.cy0, b.cy1) AS gy(cy)
  ), e AS (
    SELECT unit_number, pos_x, pos_y FROM raw_entities
    WHERE tick = tickv AND surface = surf AND unit_number = entity_id
    ORDER BY tick DESC
    LIMIT 1
  ), bounds AS (
    SELECT
      CAST(floor((pos_x - radius) / step) AS BIGINT) AS ix0,
      CAST(floor((pos_x + radius) / step) AS BIGINT) AS ix1,
      CAST(floor((pos_y - radius) / step) AS BIGINT) AS iy0,
      CAST(floor((pos_y + radius) / step) AS BIGINT) AS iy1,
      CAST(step AS DOUBLE) AS step_d
    FROM e
  ), grid_i AS (
    SELECT ix, iy
    FROM bounds,
         generate_series(ix0, ix1) AS gx(ix),
         generate_series(iy0, iy1) AS gy(iy)
  ), grid AS (
    SELECT
      CAST(ix * step_d AS DOUBLE) AS px,
      CAST(iy * step_d AS DOUBLE) AS py,
      CAST(floor((ix * step_d) / 32.0) AS BIGINT) AS chunk_x,
      CAST(floor((iy * step_d) / 32.0) AS BIGINT) AS chunk_y
    FROM grid_i, bounds
  ), cand AS (
    SELECT
      px, py, chunk_x, chunk_y,
      (px - footprint_w / 2.0)  AS min_x,
      (py - footprint_h / 2.0)  AS min_y,
      (px + footprint_w / 2.0)  AS max_x,
      (py + footprint_h / 2.0)  AS max_y
    FROM grid
  ), blocked AS (
    SELECT
      c.px, c.py, c.chunk_x, c.chunk_y,
      COUNT(oi.kind)                         AS collisions,
      LIST(DISTINCT oi.kind)                 AS blocking_kinds
    FROM cand c
    LEFT JOIN occ_idx oi
      ON oi.chunk_x = c.chunk_x AND oi.chunk_y = c.chunk_y
     AND NOT (c.max_x < oi.min_x OR c.min_x > oi.max_x OR c.max_y < oi.min_y OR c.min_y > oi.max_y)
    GROUP BY 1,2,3,4
  ), with_dist AS (
    SELECT
      CAST(tickv AS BIGINT) AS tick,
      CAST(surf AS VARCHAR) AS surface,
      CAST(chunk_x AS INTEGER) AS chunk_x,
      CAST(chunk_y AS INTEGER) AS chunk_y,
      px, py,
      CASE WHEN collisions = 0 THEN TRUE ELSE FALSE END AS is_buildable,
      COALESCE(blocking_kinds, []) AS blocking_kinds,
      (SELECT sqrt((px - pos_x)*(px - pos_x) + (py - pos_y)*(py - pos_y)) FROM e) AS dist
    FROM blocked
  )
  SELECT * FROM with_dist
  WHERE dist <= radius
  ORDER BY is_buildable DESC, dist ASC
);
"""


MACRO_SQL["find_buildable_near_entity"] = r"""
CREATE OR REPLACE MACRO find_buildable_near_entity(entity_id, radius, step) AS TABLE (
  WITH ctx AS (
    SELECT e.unit_number AS entity_id, e.surface, e.tick
    FROM raw_entities e
    WHERE e.unit_number = entity_id
    ORDER BY e.tick DESC
    LIMIT 1
  )
  SELECT * FROM find_buildable_near_entity_ctx(
    (SELECT entity_id FROM ctx),
    radius,
    step,
    (SELECT tick FROM ctx),
    (SELECT surface FROM ctx),
    1.0,  -- footprint_w
    1.0   -- footprint_h
  )
);
"""


MACRO_SQL["describe_area_ctx"] = r"""
CREATE OR REPLACE MACRO describe_area_ctx(px, py, radius, tickv, surf) AS TABLE (
  WITH occ AS (
    SELECT *,
           ( (min_x + max_x) / 2.0 ) AS cx,
           ( (min_y + max_y) / 2.0 ) AS cy
    FROM v_occupied_space
    WHERE tick = tickv AND surface = surf
  ), occ_near AS (
    SELECT
      'occupied'::VARCHAR AS subject_type,
      kind,
      ref_id,
      cx AS pos_x,
      cy AS pos_y,
      (cx - px) AS dx,
      (cy - py) AS dy,
      sqrt((cx - px)*(cx - px) + (cy - py)*(cy - py)) AS dist
    FROM occ
    WHERE cx BETWEEN px - radius AND px + radius
      AND cy BETWEEN py - radius AND py + radius
  ), occ_dir AS (
    SELECT *,
      degrees(atan2(dy, dx)) AS angle_deg,
      CASE
        WHEN dx = 0 AND dy = 0 THEN 'here'
        WHEN degrees(atan2(dy, dx)) >= -22.5 AND degrees(atan2(dy, dx)) < 22.5   THEN 'E'
        WHEN degrees(atan2(dy, dx)) >= 22.5  AND degrees(atan2(dy, dx)) < 67.5   THEN 'NE'
        WHEN degrees(atan2(dy, dx)) >= 67.5  AND degrees(atan2(dy, dx)) < 112.5  THEN 'N'
        WHEN degrees(atan2(dy, dx)) >= 112.5 AND degrees(atan2(dy, dx)) < 157.5  THEN 'NW'
        WHEN degrees(atan2(dy, dx)) >= 157.5 OR  degrees(atan2(dy, dx)) < -157.5 THEN 'W'
        WHEN degrees(atan2(dy, dx)) >= -157.5 AND degrees(atan2(dy, dx)) < -112.5 THEN 'SW'
        WHEN degrees(atan2(dy, dx)) >= -112.5 AND degrees(atan2(dy, dx)) < -67.5  THEN 'S'
        WHEN degrees(atan2(dy, dx)) >= -67.5  AND degrees(atan2(dy, dx)) < -22.5  THEN 'SE'
        ELSE 'unknown'
      END AS direction
    FROM occ_near
  ), ent_near AS (
    SELECT
      'entity'::VARCHAR AS subject_type,
      e.name AS kind,
      CAST(e.unit_number AS VARCHAR) AS ref_id,
      e.pos_x, e.pos_y,
      (e.pos_x - px) AS dx,
      (e.pos_y - py) AS dy,
      sqrt((e.pos_x - px)*(e.pos_x - px) + (e.pos_y - py)*(e.pos_y - py)) AS dist
    FROM raw_entities e
    WHERE e.tick = tickv AND e.surface = surf
      AND e.pos_x BETWEEN px - radius AND px + radius
      AND e.pos_y BETWEEN py - radius AND py + radius
  ), ent_dir AS (
    SELECT *,
      degrees(atan2(dy, dx)) AS angle_deg,
      CASE
        WHEN dx = 0 AND dy = 0 THEN 'here'
        WHEN degrees(atan2(dy, dx)) >= -22.5 AND degrees(atan2(dy, dx)) < 22.5   THEN 'E'
        WHEN degrees(atan2(dy, dx)) >= 22.5  AND degrees(atan2(dy, dx)) < 67.5   THEN 'NE'
        WHEN degrees(atan2(dy, dx)) >= 67.5  AND degrees(atan2(dy, dx)) < 112.5  THEN 'N'
        WHEN degrees(atan2(dy, dx)) >= 112.5 AND degrees(atan2(dy, dx)) < 157.5  THEN 'NW'
        WHEN degrees(atan2(dy, dx)) >= 157.5 OR  degrees(atan2(dy, dx)) < -157.5 THEN 'W'
        WHEN degrees(atan2(dy, dx)) >= -157.5 AND degrees(atan2(dy, dx)) < -112.5 THEN 'SW'
        WHEN degrees(atan2(dy, dx)) >= -112.5 AND degrees(atan2(dy, dx)) < -67.5  THEN 'S'
        WHEN degrees(atan2(dy, dx)) >= -67.5  AND degrees(atan2(dy, dx)) < -22.5  THEN 'SE'
        ELSE 'unknown'
      END AS direction
    FROM ent_near
  )
  SELECT subject_type, kind, ref_id, pos_x, pos_y, dx, dy, dist, angle_deg, direction
  FROM (
    SELECT * FROM occ_dir
    UNION ALL
    SELECT * FROM ent_dir
  )
  ORDER BY dist ASC
);
"""


MACRO_SQL["describe_area"] = r"""
CREATE OR REPLACE MACRO describe_area(px, py, radius) AS TABLE (
  WITH ctx AS (
    SELECT tick, surface FROM v_latest_tick_surface WHERE surface = 'nauvis' ORDER BY tick DESC LIMIT 1
  )
  SELECT * FROM describe_area_ctx(px, py, radius, (SELECT tick FROM ctx), (SELECT surface FROM ctx))
);
"""


def create_buildable_views_and_macros(con: duckdb.DuckDBPyConnection) -> None:
    """Create or refresh buildable-area views and macros."""
    _ensure_min_schema(con)
    for name, sql in VIEW_SQL.items():
        con.execute(sql)
    for name, sql in MACRO_SQL.items():
        con.execute(sql)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Install buildable-area views and macros into DuckDB.")
    ap.add_argument("--db", dest="db", default=DEFAULT_DB_PATH, help="DuckDB path (default: factoryverse.duckdb)")
    args = ap.parse_args()

    con = connect_db(args.db)
    create_buildable_views_and_macros(con)
    print("Buildable-area views and macros installed.")


