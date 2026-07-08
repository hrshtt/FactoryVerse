"""map_entity_core group: the 10 loader-lifted placement columns.

Claim (frozen, liveness_spec): for every rig entity, the map_entity row's
entity_name / position_x/y / chunk_x/y / direction / bbox_* equal independent
engine truth. Pass criterion is exact agreement per entity, with the family's
anti-vacuity floors.

Also carries the family's SYNTHETIC PLANT (see PLANTS.md).
"""

from __future__ import annotations

import math

import pytest

from _frozen import runtime
from _frozen.liveness_spec import (
    MIN_NON_DEFAULT_VALUES,
    MIN_RIG_ENTITIES,
    MIN_ROWS_PER_LIVE_COLUMN,
)

TOL = 1e-6

# Rig: >= MIN_RIG_ENTITIES entities, multiple footprint sizes, >= 2 distinct
# non-default directions. Offsets are relative to the cell origin, in the band
# away from the cell's fixed resource patches (adjusted live in Phase B).
RIG = [
    # (name, dx, dy, direction, extra_lua)
    ("stone-furnace", 70.0, 70.0, "north", ""),
    ("burner-mining-drill", 75.0, 70.0, "east", ""),
    ("inserter", 78.5, 70.5, "south", ""),
    ("transport-belt", 80.5, 70.5, "west", ""),
    ("wooden-chest", 82.5, 70.5, "north", ""),
    ("small-electric-pole", 84.5, 70.5, "north", ""),
    ("assembling-machine-1", 88.0, 71.0, "north", ", recipe='iron-gear-wheel'"),
]


@pytest.fixture(scope="module")
def rig(rcon, cell, instance):
    placed = []
    for name, dx, dy, direction, extra in RIG:
        ox, oy = runtime.cell_origin(cell.cell_index)
        res = runtime.place(rcon, cell, name, ox + dx, oy + dy, direction, extra)
        placed.append({"name": name, "x": res["x"], "y": res["y"],
                       "direction": direction})
    runtime.require_floor(len(placed), MIN_RIG_ENTITIES, "rig entities placed")

    tick = runtime.re_snapshot_and_wait(rcon, cell.bounds)
    engine = runtime.engine_entities_in(rcon, cell.bounds, force=cell.force_name)
    runtime.require_floor(len(engine), MIN_RIG_ENTITIES, "engine-truth entities")

    con = runtime.load_db(instance, current_game_tick=runtime.game_tick(rcon))
    b = cell.bounds
    rows = con.execute(
        "SELECT entity_name, position_x, position_y, chunk_x, chunk_y, direction, "
        "bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y FROM map_entity "
        "WHERE position_x >= ? AND position_x < ? AND position_y >= ? AND position_y < ?",
        [b["left_top"]["x"], b["right_bottom"]["x"],
         b["left_top"]["y"], b["right_bottom"]["y"]]).fetchall()
    cols = ("entity_name", "position_x", "position_y", "chunk_x", "chunk_y",
            "direction", "bbox_min_x", "bbox_min_y", "bbox_max_x", "bbox_max_y")
    db = [dict(zip(cols, r)) for r in rows]
    return {"placed": placed, "engine": engine, "db": db, "tick": tick}


def _by_pos(items, xk, yk):
    return {(round(float(i[xk]), 3), round(float(i[yk]), 3)): i for i in items}


def _matched_pairs(rig):
    """(engine, db) pairs keyed by exact position; missing rows are the
    entity_name/position liveness failure surface, asserted in the tests."""
    eng = _by_pos(rig["engine"], "x", "y")
    db = _by_pos(rig["db"], "position_x", "position_y")
    return eng, db, [(eng[k], db[k]) for k in eng.keys() & db.keys()]


def test_entity_name_and_position_live(rig):
    eng, db, pairs = _matched_pairs(rig)
    runtime.require_floor(len(eng), MIN_ROWS_PER_LIVE_COLUMN, "engine entities")
    missing_in_db = sorted(str(k) + ":" + v["name"] for k, v in eng.items() if k not in db)
    phantom_in_db = sorted(str(k) + ":" + v["entity_name"] for k, v in db.items() if k not in eng)
    assert not missing_in_db, f"engine entities absent from map_entity: {missing_in_db}"
    assert not phantom_in_db, f"map_entity rows with no engine entity: {phantom_in_db}"
    for e, d in pairs:
        assert d["entity_name"] == e["name"], (e, d)


def test_chunk_columns_live(rig):
    _, _, pairs = _matched_pairs(rig)
    runtime.require_floor(len(pairs), MIN_ROWS_PER_LIVE_COLUMN, "matched rows")
    for e, d in pairs:
        assert int(d["chunk_x"]) == math.floor(float(e["x"]) / 32), (e, d)
        assert int(d["chunk_y"]) == math.floor(float(e["y"]) / 32), (e, d)


def _direction_pairs(rig):
    _, _, pairs = _matched_pairs(rig)
    runtime.require_floor(len(pairs), MIN_ROWS_PER_LIVE_COLUMN, "matched rows")
    non_default = [e for e, _ in pairs if e["direction"] not in (None, "north")]
    runtime.require_floor(len(non_default), MIN_NON_DEFAULT_VALUES,
                          "entities with non-default direction")
    return pairs


@pytest.mark.xfail(strict=True, reason="RED-FINDING NEW-2026-07-08 "
                   "(spec: MISREPRESENTED): docs promise direction NAMES "
                   "('NORTH, EAST, ...'); the VARCHAR column holds raw "
                   "defines.direction ints; the mod-emitted direction_name is "
                   "dropped by the loader")
def test_direction_documented_semantics(rig):
    pairs = _direction_pairs(rig)
    mismatches = [(e["name"], e["direction"], d["direction"])
                  for e, d in pairs
                  if e["direction"] is not None and d["direction"] != e["direction"]]
    assert not mismatches, f"direction representation drift (engine name vs DB): {mismatches}"


def test_direction_value_derivable(rig):
    """The honest other half: the int VALUES are engine-true (the column is
    misrepresented, not dead)."""
    pairs = _direction_pairs(rig)
    mismatches = [(e["name"], e["direction_int"], d["direction"])
                  for e, d in pairs
                  if d["direction"] is None or int(d["direction"]) != int(e["direction_int"])]
    assert not mismatches, f"direction ints drifted (engine vs DB): {mismatches}"


def test_bbox_columns_live(rig):
    """bbox_* semantics per the mod's emission: LuaEntity.selection_box
    (adjudicated Phase B — the furnace's DB box equals its selection box, not
    its collision box and not its tile footprint)."""
    _, _, pairs = _matched_pairs(rig)
    runtime.require_floor(len(pairs), MIN_ROWS_PER_LIVE_COLUMN, "matched rows")
    sizes = {(round(float(e["selbox_max_x"]) - float(e["selbox_min_x"]), 2),
              round(float(e["selbox_max_y"]) - float(e["selbox_min_y"]), 2))
             for e, _ in pairs}
    runtime.require_floor(len(sizes), MIN_NON_DEFAULT_VALUES, "distinct selection-box sizes")
    for e, d in pairs:
        for db_col, eng_col in (("bbox_min_x", "selbox_min_x"),
                                ("bbox_min_y", "selbox_min_y"),
                                ("bbox_max_x", "selbox_max_x"),
                                ("bbox_max_y", "selbox_max_y")):
            assert d[db_col] is not None, f"{e['name']}: {db_col} is NULL"
            assert abs(float(d[db_col]) - float(e[eng_col])) < TOL, \
                (e["name"], db_col, d[db_col], e[eng_col])


@pytest.mark.xfail(strict=True, reason="SYNTHETIC PLANT: deliberately wrong "
                   "expectation on a live column; if this ever passes the "
                   "family machinery is vacuous (see PLANTS.md)")
def test_synthetic_plant(rig):
    names = {d["entity_name"] for d in rig["db"]}
    assert "rocket-silo" in names, "the rig never places a rocket-silo"
