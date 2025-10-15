from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import duckdb  # type: ignore
import pandas as pd

DEFAULT_DB_PATH = "factoryverse.duckdb"

def connect_db(db_path: str = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open or create the DuckDB database."""
    con = duckdb.connect(db_path)
    con.execute("PRAGMA threads=8;")
    return con


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


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Load Factorio snapshot JSONs into DuckDB and create views/macros.")
    ap.add_argument("snapshot_dir", help="Directory of *.json snapshots")
    ap.add_argument("--db", dest="db", default=DEFAULT_DB_PATH, help="DuckDB path (default: factoryverse.duckdb)")
    args = ap.parse_args()

    con = connect_db(args.db)
    create_views_and_macros(con)
    print(f"Loaded views and macros into {args.db}")
