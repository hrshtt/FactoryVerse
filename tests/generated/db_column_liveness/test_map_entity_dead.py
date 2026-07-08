"""map_entity_dead group: the 3 documented-but-dead map_entity columns
(electric_network_id, tile_x, tile_y) — see PLANTS.md, natural plants
MIRAGE-2 / NEW-2026-07-08.

Claim (frozen, liveness_spec): these columns are LIVE per schema_reference —
electric_network_id should equal engine truth whenever the engine has one;
tile_x/tile_y should be the anchor-tile ints (floor of position). Both are
DEAD_DOCUMENTED (loader.py:494-535 never lifts them into the INSERT list),
so every test here is a strict-xfail RED-FINDING: the test must fail while
the mirage persists and go red (XPASS) the moment someone fixes the lift
without reconciling spec + ledger.

Each xfail test establishes its engine-truth precondition as a floor
(runtime.require_floor) BEFORE the failing assertion, so a broken rig ERRORs
as SPEC-BUG instead of xfailing vacuously (README failure semantics).

Companion (non-xfail) tests prove the values the column-lift drops are still
present inside raw_data's JSON blob — confirmed by static read of
src/fv_embodied_agent/utils/serialize.lua (_serialize_base_properties emits
`out.electric_network_id` and `out.anchor_tile = {x=floor(x), y=floor(y)}`
into the same dict loader.py:533 does `json.dumps(data)` on) — the sharpest
form of the finding: the mod does not drop the data, only the column-lift
does.
"""

from __future__ import annotations

import json
import math

import pytest

from _frozen import runtime
from _frozen.liveness_spec import (
    MIN_ROWS_PER_LIVE_COLUMN,
    cases_for_group,
)

CASES = {c.column: c for c in cases_for_group("map_entity_dead")}


def _reason(column: str) -> str:
    c = CASES[column]
    return f"RED-FINDING {c.tracker}: {c.note}"


# Rig: a small-electric-pole + an inserter close enough for the pole's supply
# area to power it (small-electric-pole supply_area_distance covers ~2 tiles),
# plus a wooden-chest for a third entity with a known (unpowered) position.
# Offsets relative to cell origin, in the same band test_map_entity_core.py
# uses successfully (verified clear of the cell's fixed resource patches,
# Phase B) — this group runs in its own cell (FV_CELL_INDEX=11) so there is
# no cross-group placement conflict.
RIG = [
    ("small-electric-pole", 70.0, 80.0, "north", ""),
    ("inserter", 71.5, 80.5, "south", ""),
    ("wooden-chest", 73.5, 80.5, "north", ""),
]


@pytest.fixture(scope="module")
def rig(rcon, cell, instance):
    placed = []
    for name, dx, dy, direction, extra in RIG:
        ox, oy = runtime.cell_origin(cell.cell_index)
        res = runtime.place(rcon, cell, name, ox + dx, oy + dy, direction, extra)
        placed.append({"name": name, "x": res["x"], "y": res["y"]})

    tick = runtime.re_snapshot_and_wait(rcon, cell.bounds)
    engine = runtime.engine_entities_in(rcon, cell.bounds, force=cell.force_name)
    runtime.require_floor(len(engine), MIN_ROWS_PER_LIVE_COLUMN, "engine-truth entities")

    con = runtime.load_db(instance, current_game_tick=runtime.game_tick(rcon))
    b = cell.bounds
    rows = con.execute(
        "SELECT entity_name, position_x, position_y, electric_network_id, "
        "tile_x, tile_y, raw_data FROM map_entity "
        "WHERE position_x >= ? AND position_x < ? AND position_y >= ? AND position_y < ?",
        [b["left_top"]["x"], b["right_bottom"]["x"],
         b["left_top"]["y"], b["right_bottom"]["y"]]).fetchall()
    cols = ("entity_name", "position_x", "position_y", "electric_network_id",
            "tile_x", "tile_y", "raw_data")
    db = [dict(zip(cols, r)) for r in rows]
    return {"placed": placed, "engine": engine, "db": db, "tick": tick}


def _by_pos(items, xk, yk):
    return {(round(float(i[xk]), 3), round(float(i[yk]), 3)): i for i in items}


def _matched_pairs(rig):
    eng = _by_pos(rig["engine"], "x", "y")
    db = _by_pos(rig["db"], "position_x", "position_y")
    return eng, db, [(eng[k], db[k]) for k in eng.keys() & db.keys()]


def _powered_pairs(rig):
    """Engine-truth precondition floor: >= 2 entities the engine itself
    reports a non-nil electric_network_id for. If this floor is unmet the
    rig failed to establish power, and the test below must ERROR
    (AntiVacuityError -> SPEC-BUG), never silently xfail on an empty set."""
    _, _, pairs = _matched_pairs(rig)
    powered = [(e, d) for e, d in pairs if e.get("electric_network_id") is not None]
    runtime.require_floor(len(powered), 2,
                          "engine entities with non-nil electric_network_id")
    return powered


# ---------------------------------------------------------------------------
# electric_network_id (MIRAGE-2)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason=_reason("electric_network_id"))
def test_electric_network_id_documented_liveness(rig):
    powered = _powered_pairs(rig)
    mismatches = [(e["name"], e["electric_network_id"], d["electric_network_id"])
                  for e, d in powered
                  if d["electric_network_id"] != e["electric_network_id"]]
    assert not mismatches, (
        f"map_entity.electric_network_id disagrees with engine truth "
        f"(engine, db) pairs: {mismatches}")


def test_electric_network_id_present_in_raw_data(rig):
    """Non-xfail companion: the value the column-lift drops IS present
    inside raw_data's JSON blob — the mod does not drop it."""
    powered = _powered_pairs(rig)
    column_all_null = all(d["electric_network_id"] is None for _, d in powered)
    assert column_all_null, (
        "electric_network_id column is non-NULL for at least one powered "
        "entity — the mirage may have been fixed; re-check the xfail above "
        "before touching this companion")

    found_in_raw = []
    for e, d in powered:
        raw = json.loads(d["raw_data"]) if d["raw_data"] else {}
        if raw.get("electric_network_id") == e["electric_network_id"]:
            found_in_raw.append(e["name"])
    assert len(found_in_raw) == len(powered), (
        f"electric_network_id present+correct in raw_data for only "
        f"{len(found_in_raw)}/{len(powered)} powered entities "
        f"(engine ids: {[e['electric_network_id'] for e, _ in powered]})")


# ---------------------------------------------------------------------------
# tile_x / tile_y (NEW-2026-07-08)
# ---------------------------------------------------------------------------


def _position_pairs(rig):
    _, _, pairs = _matched_pairs(rig)
    runtime.require_floor(len(pairs), MIN_ROWS_PER_LIVE_COLUMN,
                          "matched rows with known position")
    return pairs


@pytest.mark.xfail(strict=True, reason=_reason("tile_x"))
def test_tile_x_documented_liveness(rig):
    pairs = _position_pairs(rig)
    mismatches = [(e["name"], math.floor(float(e["x"])), d["tile_x"])
                  for e, d in pairs
                  if d["tile_x"] is None or int(d["tile_x"]) != math.floor(float(e["x"]))]
    assert not mismatches, f"map_entity.tile_x not live: {mismatches}"


@pytest.mark.xfail(strict=True, reason=_reason("tile_y"))
def test_tile_y_documented_liveness(rig):
    pairs = _position_pairs(rig)
    mismatches = [(e["name"], math.floor(float(e["y"])), d["tile_y"])
                  for e, d in pairs
                  if d["tile_y"] is None or int(d["tile_y"]) != math.floor(float(e["y"]))]
    assert not mismatches, f"map_entity.tile_y not live: {mismatches}"


def test_tile_xy_present_in_raw_data_as_anchor_tile(rig):
    """Non-xfail companion: the anchor tile IS computed and shipped by the
    mod (serialize.lua _serialize_base_properties: out.anchor_tile =
    {x=floor(pos.x), y=floor(pos.y)}) — it lives in raw_data under
    'anchor_tile', not under keys 'tile_x'/'tile_y'; the columns are simply
    never lifted from it."""
    pairs = _position_pairs(rig)
    for e, d in pairs:
        assert d["tile_x"] is None and d["tile_y"] is None, (
            f"{e['name']}: tile_x/tile_y column no longer NULL — mirage may "
            "be fixed, re-check the xfail tests above before touching this "
            "companion")

    hits = []
    for e, d in pairs:
        raw = json.loads(d["raw_data"]) if d["raw_data"] else {}
        anchor = raw.get("anchor_tile") or {}
        if (anchor.get("x") == math.floor(float(e["x"]))
                and anchor.get("y") == math.floor(float(e["y"]))):
            hits.append(e["name"])
    assert len(hits) == len(pairs), (
        f"anchor_tile present+correct in raw_data for only "
        f"{len(hits)}/{len(pairs)} rows")
