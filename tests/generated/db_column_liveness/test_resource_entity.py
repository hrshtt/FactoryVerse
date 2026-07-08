"""resource_entity group: name, entity_type, position_x/y, chunk_x/y, raw_data.

Claim (frozen, liveness_spec): every documented column of resource_entity
(trees/rocks) is LIVE -- populated with engine-true values whenever the
engine has corresponding state. All 7 columns in this group classify as LIVE
(no known-dead entries for resource_entity in liveness_spec).

Lab-grid cells carry NO trees/rocks by construction (only fixed ore/stone
resource-tile patches + a water rectangle -- see terrain_and_meta). This rig
therefore raw-creates trees/rocks directly via game.surfaces[1].create_entity
(neutral force, raise_built=true) so the event pipeline sees them, same as a
human player chopping into virgin forest.

Engine truth channel: a bespoke probe (NOT runtime.engine_entities_in, which
filters by force and would drop neutral trees/rocks, and also excludes
type=='resource' but not 'tree'/'simple-entity' -- still, the CAUTION in the
task brief is explicit: write an independent probe). This probe filters by
TYPE only ('tree', 'simple-entity'), independent of the mod's own name-match
heuristic (Resource.lua:161 additionally requires the simple-entity's name to
contain "rock"/"stone" before treating it as a resource entity) -- using a
broader, independent filter here means any name-matching drift on the mod
side would show up as a genuine mismatch rather than being invisibly mirrored
away. Lab-grid cells have no other tree/simple-entity content by construction,
so this stays a clean two-sided set comparison.

Coordinate convention (verified against source, Resource.lua:30-97):
- M.serialize_rock / M.serialize_tree store entity.position RAW (no floor) --
  unlike resource_tile, which floors. position_x/y should therefore match
  engine e.position.x/y exactly (within float tolerance), not floor()'d.
- chunk_x/chunk_y are the gather-loop's chunk coordinates (the chunk file the
  entity's data landed under), which is the chunk containing entity.position
  -- i.e. floor(position/32), same convention as every other table.
"""

from __future__ import annotations

import json
import math

import pytest

from _frozen import runtime
from _frozen.liveness_spec import (
    MIN_NON_DEFAULT_VALUES,
    MIN_RIG_ENTITIES,
    MIN_ROWS_PER_LIVE_COLUMN,
)

TOL = 1e-6

# Rig: >= MIN_RIG_ENTITIES resource entities, 2 distinct entity_type values
# (tree, simple-entity), spread along the safe band (away from the cell's
# fixed ore/stone/water patches). Verified live 2026-07-08 against server_0
# cell 14: all 5 placements succeed with force='neutral' auto-assigned when
# force is omitted from create_entity.
RIG = [
    # (name, dx, dy)  -- offsets relative to cell origin
    ("tree-01", 60.0, 60.0),
    ("tree-05", 64.0, 60.0),
    ("tree-08", 68.0, 60.0),
    ("big-rock", 72.0, 60.0),
    ("huge-rock", 76.0, 60.0),
]


def _create_resource_entity(rcon, name: str, x: float, y: float) -> dict:
    """Raw-create a neutral tree/rock, raising script_raised_built so the
    snapshot mod's event pipeline sees it (mirrors runtime.place, but that
    helper forces a `force=` + `direction=` clause unsuited to neutral
    resource entities -- trees/rocks take neither)."""
    res = runtime.lua_strict(rcon, f"""
        local e = game.surfaces[1].create_entity{{
            name='{name}', position={{x={x},y={y}}}, raise_built=true}}
        if e == nil then return {{success=false}} end
        return {{success=true, name=e.name, type=e.type,
                 x=e.position.x, y=e.position.y, force=e.force.name}}
    """)
    if not res.get("success"):
        raise runtime.SpecBug(
            f"rig placement failed: {name} at ({x},{y}) -- adjust the rig, not the claim")
    return res


def _engine_resource_entities_in(rcon, bounds) -> list:
    """Independent engine truth: TYPE-only filter, no force filter (neutral
    entities have no player force to filter on), no name heuristic."""
    res = runtime.lua_strict(rcon, f"""
        local out = {{}}
        for _, e in pairs(game.surfaces[1].find_entities_filtered{{
                area={runtime.bounds_lua(bounds)}}}) do
            if e.type == 'tree' or e.type == 'simple-entity' then
                out[#out+1] = {{name=e.name, type=e.type,
                                x=e.position.x, y=e.position.y}}
            end
        end
        return {{entities = out}}
    """)
    return runtime.as_list(res.get("entities"))


@pytest.fixture(scope="module")
def rig(rcon, cell, instance):
    placed = []
    for name, dx, dy in RIG:
        ox, oy = runtime.cell_origin(cell.cell_index)
        res = _create_resource_entity(rcon, name, ox + dx, oy + dy)
        placed.append(res)
    runtime.require_floor(len(placed), MIN_RIG_ENTITIES, "rig resource entities placed")

    runtime.re_snapshot_and_wait(rcon, cell.bounds)
    engine = _engine_resource_entities_in(rcon, cell.bounds)
    runtime.require_floor(len(engine), MIN_RIG_ENTITIES, "engine-truth resource entities")

    con = runtime.load_db(instance, current_game_tick=runtime.game_tick(rcon))
    b = cell.bounds
    rows = con.execute(
        "SELECT name, entity_type, position_x, position_y, chunk_x, chunk_y, raw_data "
        "FROM resource_entity "
        "WHERE position_x >= ? AND position_x < ? AND position_y >= ? AND position_y < ?",
        [b["left_top"]["x"], b["right_bottom"]["x"],
         b["left_top"]["y"], b["right_bottom"]["y"]]).fetchall()
    cols = ("name", "entity_type", "position_x", "position_y",
             "chunk_x", "chunk_y", "raw_data")
    db = [dict(zip(cols, r)) for r in rows]
    return {"placed": placed, "engine": engine, "db": db}


def _by_pos(items, xk, yk):
    return {(round(float(i[xk]), 3), round(float(i[yk]), 3)): i for i in items}


def _matched_pairs(rig):
    """(engine, db) pairs keyed by exact position; missing rows are the
    name/position liveness failure surface, asserted in the tests."""
    eng = _by_pos(rig["engine"], "x", "y")
    db = _by_pos(rig["db"], "position_x", "position_y")
    return eng, db, [(eng[k], db[k]) for k in eng.keys() & db.keys()]


def test_name_and_position_live(rig):
    eng, db, pairs = _matched_pairs(rig)
    runtime.require_floor(len(eng), MIN_ROWS_PER_LIVE_COLUMN, "engine resource entities")
    missing_in_db = sorted(f"{k}:{v['name']}" for k, v in eng.items() if k not in db)
    phantom_in_db = sorted(f"{k}:{v['name']}" for k, v in db.items() if k not in eng)
    assert not missing_in_db, f"engine resource entities absent from resource_entity: {missing_in_db}"
    assert not phantom_in_db, f"resource_entity rows with no engine resource entity: {phantom_in_db}"
    for e, d in pairs:
        assert d["name"] == e["name"], (e, d)
    names = {d["name"] for _, d in pairs}
    runtime.require_floor(len(names), MIN_NON_DEFAULT_VALUES, "distinct resource_entity.name values")


def test_entity_type_live(rig):
    eng, db, pairs = _matched_pairs(rig)
    runtime.require_floor(len(pairs), MIN_ROWS_PER_LIVE_COLUMN, "matched rows")
    types = {d["entity_type"] for _, d in pairs}
    runtime.require_floor(len(types), MIN_NON_DEFAULT_VALUES, "distinct entity_type values")
    mismatches = [(e["name"], e["type"], d["entity_type"]) for e, d in pairs
                  if d["entity_type"] != e["type"]]
    assert not mismatches, f"entity_type drift (name, engine e.type, db entity_type): {mismatches}"
    # documented values are exactly the engine's raw type strings (per
    # schema_definitions.py notes: rocks store 'simple-entity', not 'rock')
    assert types <= {"tree", "simple-entity"}, f"unexpected entity_type values: {types}"


def test_chunk_columns_live(rig):
    _, _, pairs = _matched_pairs(rig)
    runtime.require_floor(len(pairs), MIN_ROWS_PER_LIVE_COLUMN, "matched rows")
    for e, d in pairs:
        assert int(d["chunk_x"]) == math.floor(float(e["x"]) / 32), (e, d)
        assert int(d["chunk_y"]) == math.floor(float(e["y"]) / 32), (e, d)


def test_position_exact_no_floor(rig):
    """resource_entity stores raw entity.position (Resource.lua:56/85), unlike
    resource_tile which floors -- assert the DB position is NOT rounded to an
    integer tile coordinate when the engine position has a fractional part."""
    eng, db, pairs = _matched_pairs(rig)
    runtime.require_floor(len(pairs), MIN_ROWS_PER_LIVE_COLUMN, "matched rows")
    for e, d in pairs:
        assert abs(float(d["position_x"]) - float(e["x"])) < TOL, (e, d)
        assert abs(float(d["position_y"]) - float(e["y"])) < TOL, (e, d)


def test_raw_data_live(rig):
    _, _, pairs = _matched_pairs(rig)
    runtime.require_floor(len(pairs), MIN_ROWS_PER_LIVE_COLUMN, "matched rows")
    non_null = [d for _, d in pairs if d["raw_data"]]
    runtime.require_floor(len(non_null), MIN_ROWS_PER_LIVE_COLUMN, "non-null raw_data rows")
    for e, d in pairs:
        assert d["raw_data"] is not None, f"{e['name']}: raw_data is NULL"
        payload = json.loads(d["raw_data"])
        assert payload["name"] == e["name"], (e, payload)
        assert payload["type"] == e["type"], (e, payload)
        assert abs(float(payload["position"]["x"]) - float(e["x"])) < TOL, (e, payload)
        assert abs(float(payload["position"]["y"]) - float(e["y"])) < TOL, (e, payload)


@pytest.mark.xfail(strict=True, reason="SYNTHETIC PLANT: deliberately wrong "
                   "expectation on a live column; if this ever passes the "
                   "family machinery is vacuous (see PLANTS.md)")
def test_synthetic_plant(rig):
    names = {d["name"] for d in rig["db"]}
    assert "rock-huge-old-relic-that-does-not-exist" in names, \
        "the rig never places this made-up name"
