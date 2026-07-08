"""terrain_and_meta group: resource_tile, water_tile, chunk_snapshot_meta.

Claim (frozen, liveness_spec): every resource_tile / water_tile row inside the
cell equals independent engine truth, and every chunk overlapping the cell has
a chunk_snapshot_meta row whose tick tracks the re_snapshot trigger and
map.get_chunk_lookup's snapshot_tick. All columns in this group classify as
LIVE in liveness_spec (no known-dead entries for these three tables) -- no
rig needed: every lab-grid cell already carries fixed resource patches
(iron/copper/coal/stone, ~1459 tiles) and a water rectangle (216 tiles), per
the group brief.

COORDINATE CONVENTION (discovered empirically 2026-07-08 against server_0,
cell 13; confirmed by source read):
- Engine resource entities sit at tile-center positions (e.g. x=74.5); the mod
  stores math.floor(entity.position.x/y) into resource_tile.position_x/y
  (src/fv_snapshot/game_state/Resource.lua:30-37,
  M.serialize_resource_tile -> utils.floor).
- Engine water LuaTile.position is already an integer tile coordinate; the
  mod runs it through the same utils.extract_position -> utils.floor path
  (src/fv_snapshot/utils/utils.lua:159-165) before storing it, so it is a
  no-op there.
- Both sides therefore agree once BOTH are passed through floor(): a single
  `_floor_key` normalization applied to engine truth and read as-is (already
  integral) from the DB gives a consistent bijection in both directions. This
  is LIVE, not a MIRAGE-class drift (contrast map_entity.direction).
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

# Group-specific floors (stricter than the family defaults; from the group
# brief): amount comparisons must be sampled across >= this many positions and
# >= this many distinct resource names.
MIN_AMOUNT_SAMPLE = 20
MIN_AMOUNT_NAMES = 3


def _floor_key(x, y):
    return (math.floor(float(x)), math.floor(float(y)))


@pytest.fixture(scope="module")
def terrain(rcon, cell, instance):
    trigger_tick = runtime.game_tick(rcon)
    runtime.re_snapshot_and_wait(rcon, cell.bounds, trigger_tick)

    b = cell.bounds
    engine = runtime.lua_strict(rcon, f"""
        local out_res, out_water = {{}}, {{}}
        for _, e in pairs(game.surfaces[1].find_entities_filtered{{
                area={runtime.bounds_lua(b)}, type='resource'}}) do
            out_res[#out_res+1] = {{name=e.name, x=e.position.x, y=e.position.y,
                                    amount=e.amount}}
        end
        for _, t in pairs(game.surfaces[1].find_tiles_filtered{{
                area={runtime.bounds_lua(b)},
                name={{'water','deepwater','water-green','deepwater-green'}}}}) do
            out_water[#out_water+1] = {{x=t.position.x, y=t.position.y}}
        end
        return {{resources=out_res, water=out_water}}
    """)
    engine_resources = runtime.as_list(engine.get("resources"))
    engine_water = runtime.as_list(engine.get("water"))
    runtime.require_floor(len(engine_resources), MIN_RIG_ENTITIES, "engine resource tiles")
    runtime.require_floor(len(engine_water), MIN_ROWS_PER_LIVE_COLUMN, "engine water tiles")

    lookup_ticks = runtime.lookup_snapshot_ticks(rcon)

    con = runtime.load_db(instance, current_game_tick=runtime.game_tick(rcon))
    res_rows = con.execute(
        "SELECT name, position_x, position_y, chunk_x, chunk_y, amount FROM resource_tile "
        "WHERE position_x >= ? AND position_x < ? AND position_y >= ? AND position_y < ?",
        [b["left_top"]["x"], b["right_bottom"]["x"],
         b["left_top"]["y"], b["right_bottom"]["y"]]).fetchall()
    water_rows = con.execute(
        "SELECT position_x, position_y, chunk_x, chunk_y FROM water_tile "
        "WHERE position_x >= ? AND position_x < ? AND position_y >= ? AND position_y < ?",
        [b["left_top"]["x"], b["right_bottom"]["x"],
         b["left_top"]["y"], b["right_bottom"]["y"]]).fetchall()
    meta_rows = con.execute("SELECT chunk_x, chunk_y, tick FROM chunk_snapshot_meta").fetchall()

    res_cols = ("name", "position_x", "position_y", "chunk_x", "chunk_y", "amount")
    water_cols = ("position_x", "position_y", "chunk_x", "chunk_y")
    return {
        "trigger_tick": trigger_tick,
        "engine_resources": engine_resources,
        "engine_water": engine_water,
        "lookup_ticks": lookup_ticks,
        "db_resources": [dict(zip(res_cols, r)) for r in res_rows],
        "db_water": [dict(zip(water_cols, r)) for r in water_rows],
        "db_meta": {(int(cx), int(cy)): int(t) for cx, cy, t in meta_rows},
        "chunks": runtime.cell_chunks(b),
    }


def _engine_res_by_pos(terrain):
    return {_floor_key(e["x"], e["y"]): e for e in terrain["engine_resources"]}


def _db_res_by_pos(terrain):
    return {_floor_key(r["position_x"], r["position_y"]): r for r in terrain["db_resources"]}


def _engine_water_by_pos(terrain):
    return {_floor_key(t["x"], t["y"]): t for t in terrain["engine_water"]}


def _db_water_by_pos(terrain):
    return {_floor_key(r["position_x"], r["position_y"]): r for r in terrain["db_water"]}


def test_resource_position_and_name_live(terrain):
    eng = _engine_res_by_pos(terrain)
    db = _db_res_by_pos(terrain)
    runtime.require_floor(len(eng), MIN_ROWS_PER_LIVE_COLUMN, "engine resource positions")
    missing_in_db = sorted(f"{k}:{eng[k]['name']}" for k in eng.keys() - db.keys())
    phantom_in_db = sorted(f"{k}:{db[k]['name']}" for k in db.keys() - eng.keys())
    assert not missing_in_db, \
        f"engine resource tiles absent from resource_tile ({len(missing_in_db)}): {missing_in_db[:20]}"
    assert not phantom_in_db, \
        f"resource_tile rows with no engine resource ({len(phantom_in_db)}): {phantom_in_db[:20]}"
    mismatches = [(k, eng[k]["name"], db[k]["name"]) for k in eng.keys() & db.keys()
                  if db[k]["name"] != eng[k]["name"]]
    assert not mismatches, f"resource_tile.name drift (pos, engine, db): {mismatches[:20]}"


def test_resource_chunk_columns_live(terrain):
    eng = _engine_res_by_pos(terrain)
    db = _db_res_by_pos(terrain)
    common = eng.keys() & db.keys()
    runtime.require_floor(len(common), MIN_ROWS_PER_LIVE_COLUMN, "matched resource positions")
    distinct_chunks = {(int(db[k]["chunk_x"]), int(db[k]["chunk_y"])) for k in common}
    runtime.require_floor(len(distinct_chunks), MIN_NON_DEFAULT_VALUES,
                          "distinct resource chunk coordinates")
    mismatches = []
    for k in common:
        px, py = k
        want = (math.floor(px / 32), math.floor(py / 32))
        got = (int(db[k]["chunk_x"]), int(db[k]["chunk_y"]))
        if got != want:
            mismatches.append((k, want, got))
    assert not mismatches, f"resource_tile chunk_x/y drift (pos, want, got): {mismatches[:20]}"


def test_resource_amount_live(terrain):
    eng = _engine_res_by_pos(terrain)
    db = _db_res_by_pos(terrain)
    common = eng.keys() & db.keys()
    runtime.require_floor(len(common), MIN_AMOUNT_SAMPLE, "resource positions sampled for amount")
    names = {eng[k]["name"] for k in common}
    runtime.require_floor(len(names), MIN_AMOUNT_NAMES, "distinct resource names sampled for amount")
    mismatches = [(k, eng[k]["name"], eng[k]["amount"], db[k]["amount"]) for k in common
                  if int(eng[k]["amount"]) != int(db[k]["amount"])]
    assert not mismatches, f"resource_tile.amount drift (pos, name, engine, db): {mismatches[:20]}"


def test_water_position_live(terrain):
    eng = _engine_water_by_pos(terrain)
    db = _db_water_by_pos(terrain)
    runtime.require_floor(len(eng), MIN_ROWS_PER_LIVE_COLUMN, "engine water tiles")
    missing_in_db = sorted(str(k) for k in eng.keys() - db.keys())
    phantom_in_db = sorted(str(k) for k in db.keys() - eng.keys())
    assert not missing_in_db, \
        f"engine water tiles absent from water_tile ({len(missing_in_db)}): {missing_in_db[:20]}"
    assert not phantom_in_db, \
        f"water_tile rows with no engine water tile ({len(phantom_in_db)}): {phantom_in_db[:20]}"


def test_water_chunk_columns_live(terrain):
    eng = _engine_water_by_pos(terrain)
    db = _db_water_by_pos(terrain)
    common = eng.keys() & db.keys()
    runtime.require_floor(len(common), MIN_ROWS_PER_LIVE_COLUMN, "matched water positions")
    mismatches = []
    for k in common:
        px, py = k
        want = (math.floor(px / 32), math.floor(py / 32))
        got = (int(db[k]["chunk_x"]), int(db[k]["chunk_y"]))
        if got != want:
            mismatches.append((k, want, got))
    assert not mismatches, f"water_tile chunk_x/y drift (pos, want, got): {mismatches[:20]}"


@pytest.mark.xfail(strict=True, reason="RED-FINDING NEW-2026-07-08 (spec classifies "
                   "chunk_snapshot_meta as LIVE; not yet filed in liveness_spec/tracker "
                   "-- escalate to orchestrator): chunk_snapshot_meta has NO row for "
                   "chunks that have zero resource/water/entity/ghost content (cell 13, "
                   "9/16 overlapped chunks, e.g. (25,5)..(28,8)), even though "
                   "map.get_chunk_lookup reports a fresh snapshot_tick for every one of "
                   "them >= the re_snapshot trigger tick. Root cause (Map.lua:1443-1578): "
                   "an entirely-empty chunk builds an empty write_queue -- no init JSONL "
                   "of any kind is ever written, so the loader's kind=chunk_meta line "
                   "(loader.py:664-676) never gets recorded for that chunk. The documented "
                   "claim ('per-chunk snapshot freshness'; 'a max(tick) far behind current "
                   "game tick means the map snapshot is stale') is only true for chunks "
                   "that have ever carried snapshot-worthy content -- it cannot answer "
                   "'is this chunk stale' for a chunk with none, which reads as "
                   "indistinguishable from 'never snapshotted'.")
def test_chunk_snapshot_meta_live(terrain):
    chunks = terrain["chunks"]
    runtime.require_floor(len(chunks), 1, "chunks overlapping cell bounds")
    db_meta = terrain["db_meta"]
    missing = [c for c in chunks if c not in db_meta]
    assert not missing, f"chunk_snapshot_meta missing rows for chunks: {missing}"
    stale = [(c, db_meta[c]) for c in chunks if db_meta[c] < terrain["trigger_tick"]]
    assert not stale, (
        f"chunk_snapshot_meta tick older than the re_snapshot trigger tick "
        f"({terrain['trigger_tick']}): {stale}")
    lookup_ticks = terrain["lookup_ticks"]
    drift = [(c, db_meta[c], lookup_ticks.get(c)) for c in chunks
             if c in lookup_ticks and db_meta[c] != lookup_ticks[c]]
    assert not drift, (
        "chunk_snapshot_meta.tick disagrees with map.get_chunk_lookup's "
        f"snapshot_tick (chunk, db_tick, lookup_tick): {drift}")
