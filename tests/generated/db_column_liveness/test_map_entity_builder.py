"""map_entity_builder group: the 5 builder-metadata columns on map_entity
(agent_id, player_id, label, placed_tick, raw_data).

Claim (frozen, liveness_spec): all five are LIVE. Pass criterion is exact
agreement with what we independently commanded through two placement paths.

IMPORTANT rig-ordering finding (this sub-agent's own discovery, corrects the
orchestrator's pilot-run framing): re_snapshot_area (what re_snapshot_and_wait
triggers) unconditionally clears the chunk's snapshot_tick and re-runs the
FULL chunk gather, which stamps EVERY entity it finds with the hardcoded
pre_existing_builder_info (label="pre-existing", placed_tick=nil --
src/fv_snapshot/game_state/Map.lua:1376-1400), REGARDLESS of true origin.
Calling it AFTER placement (as the pilot run apparently did) squashes real
agent_id/label/placed_tick back to NULL/"pre-existing" for every entity --
confirmed empirically: the loader logs "Dropped N update records older than
their chunk's init snapshot tick" when this happens. This rig instead
establishes the baseline snapshot ONCE, BEFORE anything is placed, then
never re-triggers a full re-snapshot -- entity-build events write
synchronously to the per-chunk updates log (utils/snapshot.lua
append_entity_operation uses helpers.write_file, not a queued async write),
so builder metadata from a placement made after the one-time baseline
survives untouched into the DB.

Under that ordering, the two placement paths' TRUE engine semantics are:
- Script placement (runtime.place / create_entity{raise_built=true}):
  _on_entity_built (src/fv_snapshot/game_state/Entities.lua:534-550) passes
  agent_id=nil, label=nil, player_id=event.player_index (nil for
  script_raised_built -- there is no player). All three are falsy, so
  write_entity_snapshot's builder_info is nil entirely: agent_id, player_id,
  label, AND placed_tick are all NULL. NOT the "pre-existing" string --
  that string is specific to the initial full-chunk-gather path, which
  this rig deliberately never lets touch post-placement entities.
- Agent placement (agent_<id>.place_entity, POSITIONAL args per
  docs/RUNTIME_PLAYBOOK.md Sec3): raises on_agent_entity_built with the real
  agent_id and the label we pass (src/fv_embodied_agent/agent_actions/
  placement.lua:331-336 -> Entities.lua:809-819), which the loader lifts.

player_id has no reachable non-default case: the headless server has no
players, so engine-true player_id is NULL for every entity in this rig
(agent- or script-placed alike). That test asserts NULL-everywhere instead
of forcing a fake floor (see COVERAGE LIMITS in the sub-agent report).
"""

from __future__ import annotations

import json

import pytest

from _frozen import runtime
from _frozen.liveness_spec import (
    MIN_NON_DEFAULT_VALUES,
    MIN_RIG_ENTITIES,
    MIN_ROWS_PER_LIVE_COLUMN,
)

TOL = 1e-6

# Script-placed baseline: deep in the factory-build quadrant (x:0-64, y:0-64,
# per src/factorio/scenarios/lab-grid/cell.lua RESOURCE_CONFIG comment),
# clear of the ore/water/oil bands that start at y>=57. 1x1 entities align
# on the .5 grid per the golden rig's convention (test_map_entity_core.py).
SCRIPT_RIG = [
    ("wooden-chest", 20.5, 20.5, "north"),
    ("wooden-chest", 25.5, 20.5, "north"),
    ("wooden-chest", 30.5, 20.5, "north"),
]

# Agent-placed entities: small offsets from the cell's spawn (build_distance
# ~10 tiles), spaced >=3 tiles apart to avoid collision between them.
# (name, dx, dy, direction (defines.direction int), label)
AGENT_RIG = [
    ("iron-chest", -3.5, -3.5, 0, "probe-alpha"),
    ("stone-furnace", -3.0, 0.0, 4, "probe-beta"),
    ("wooden-chest", 0.5, -3.5, 8, "probe-gamma"),
]


def _agent_add_items(rcon, agent_id, items):
    body = ", ".join(f"['{name}']={count}" for name, count in items.items())
    return runtime.lua_strict(
        rcon, f"return remote.call('agent','add_items',{agent_id},{{{body}}})")


def _agent_place(rcon, agent_id, name, x, y, direction, label):
    res = runtime.lua_strict(rcon, f"""
        return remote.call('agent_{agent_id}', 'place_entity', '{name}',
            {{x={x}, y={y}}}, {direction}, false, '{label}')
    """)
    if not res.get("success"):
        raise runtime.SpecBug(
            f"agent place_entity failed: {name} at ({x},{y}) label={label}: "
            f"{res.get('error') or res}")
    return res


@pytest.fixture(scope="module")
def rig(rcon, cell, instance):
    # Establish the cell's baseline snapshot FIRST, before anything is
    # placed. This matters: re_snapshot_area (what re_snapshot_and_wait
    # triggers) unconditionally clears the chunk's snapshot_tick and
    # re-runs the FULL chunk gather, which stamps EVERY entity it finds
    # with the hardcoded pre_existing_builder_info (Map.lua:1376-1400) --
    # including entities that were built via a real agent/script event
    # with real builder metadata. A second full re-snapshot AFTER placing
    # would silently squash our agent_id/label/placed_tick back to
    # NULL/"pre-existing" (confirmed empirically: loader.py logs "Dropped
    # N update records older than their chunk's init snapshot tick").
    # Placing after this one-time baseline, and never re-triggering a full
    # re-snapshot again, lets the (synchronous, per-event) entities-updates
    # log carry the real builder metadata through to the DB untouched.
    runtime.re_snapshot_and_wait(rcon, cell.bounds)

    script_placed = []
    for name, dx, dy, direction in SCRIPT_RIG:
        ox, oy = runtime.cell_origin(cell.cell_index)
        res = runtime.place(rcon, cell, name, ox + dx, oy + dy, direction)
        script_placed.append({"name": name, "x": res["x"], "y": res["y"]})

    item_counts = {name: 1 for name, *_ in AGENT_RIG}
    _agent_add_items(rcon, cell.agent_id, item_counts)

    spawn = cell.spawn
    agent_placed = []
    for name, dx, dy, direction, label in AGENT_RIG:
        res = _agent_place(rcon, cell.agent_id, name,
                            spawn["x"] + dx, spawn["y"] + dy, direction, label)
        pos = res.get("position") or {}
        agent_placed.append({
            "name": name, "x": pos.get("x"), "y": pos.get("y"), "label": label,
        })

    total_placed = len(script_placed) + len(agent_placed)
    runtime.require_floor(total_placed, MIN_RIG_ENTITIES, "rig entities placed")

    # engine_entities_in is a raw RCON scan (independent of snapshot state),
    # safe to call any time -- no re-snapshot needed for this truth channel.
    engine = runtime.engine_entities_in(rcon, cell.bounds, force=cell.force_name)
    runtime.require_floor(len(engine), MIN_RIG_ENTITIES, "engine-truth entities")

    con = runtime.load_db(instance, current_game_tick=runtime.game_tick(rcon))
    b = cell.bounds
    rows = con.execute(
        "SELECT entity_name, position_x, position_y, agent_id, player_id, "
        "label, placed_tick, raw_data FROM map_entity "
        "WHERE position_x >= ? AND position_x < ? AND position_y >= ? AND position_y < ?",
        [b["left_top"]["x"], b["right_bottom"]["x"],
         b["left_top"]["y"], b["right_bottom"]["y"]]).fetchall()
    cols = ("entity_name", "position_x", "position_y", "agent_id", "player_id",
            "label", "placed_tick", "raw_data")
    db = [dict(zip(cols, r)) for r in rows]

    return {
        "script_placed": script_placed,
        "agent_placed": agent_placed,
        "engine": engine,
        "db": db,
        "agent_id": cell.agent_id,
        "allocated_at_tick": cell.allocated_at_tick,
    }


def _by_pos(items, xk, yk):
    return {(round(float(i[xk]), 3), round(float(i[yk]), 3)): i for i in items}


def _joined_engine_db(rig):
    """(engine, db) rows keyed by exact position -- independent-truth join."""
    eng = _by_pos(rig["engine"], "x", "y")
    db = _by_pos(rig["db"], "position_x", "position_y")
    return eng, db, eng.keys() & db.keys()


def _agent_rows(rig):
    """(what-we-commanded, db row) pairs for the agent-placed entities."""
    agent_pos = _by_pos(rig["agent_placed"], "x", "y")
    db = _by_pos(rig["db"], "position_x", "position_y")
    return [(meta, db[k]) for k, meta in agent_pos.items() if k in db]


def _script_rows(rig):
    """db rows for the script-placed ("pre-existing") entities."""
    script_pos = _by_pos(rig["script_placed"], "x", "y")
    db = _by_pos(rig["db"], "position_x", "position_y")
    return [db[k] for k in script_pos.keys() & db.keys()]


def test_agent_id_live(rig):
    agent_rows = _agent_rows(rig)
    script_rows = _script_rows(rig)
    runtime.require_floor(len(agent_rows), MIN_ROWS_PER_LIVE_COLUMN,
                          "agent-placed matched rows")
    non_default = [d for _, d in agent_rows if d["agent_id"] is not None]
    runtime.require_floor(len(non_default), MIN_NON_DEFAULT_VALUES,
                          "rows with non-NULL agent_id")
    mismatches = [(m["name"], d["agent_id"]) for m, d in agent_rows
                  if d["agent_id"] != rig["agent_id"]]
    assert not mismatches, f"agent-placed rows with wrong/missing agent_id: {mismatches}"
    script_mismatches = [(d["entity_name"], d["agent_id"]) for d in script_rows
                         if d["agent_id"] is not None]
    assert not script_mismatches, (
        f"script-placed (no-operator) rows unexpectedly carry agent_id: {script_mismatches}")


def test_player_id_null_headless(rig):
    """No players exist on the headless server; engine-true player_id is
    NULL for every entity here, agent- or script-placed alike. This is the
    correctness case, not a gap -- see COVERAGE LIMITS in the sub-agent
    report for why a non-default player_id case cannot be exercised."""
    agent_rows = [d for _, d in _agent_rows(rig)]
    script_rows = _script_rows(rig)
    all_rows = agent_rows + script_rows
    runtime.require_floor(len(all_rows), MIN_ROWS_PER_LIVE_COLUMN,
                          "matched rows checked for player_id")
    non_null = [(d["entity_name"], d["player_id"]) for d in all_rows
                if d["player_id"] is not None]
    assert not non_null, (
        f"headless server produced non-NULL player_id (unexpected player presence): {non_null}")


def test_label_live(rig):
    """Agent placements carry the real label we sent. Script placements
    (create_entity{raise_built=true}, no player/agent operator) correctly
    get a NULL label -- "pre-existing" is a different, unrelated case (the
    initial full-chunk-gather stamp for entities never seen via an event;
    see the module docstring), which this rig's ordering deliberately keeps
    out of the way so it doesn't overwrite the entities placed here."""
    agent_rows = _agent_rows(rig)
    script_rows = _script_rows(rig)
    runtime.require_floor(len(agent_rows), MIN_ROWS_PER_LIVE_COLUMN,
                          "agent-placed matched rows")
    distinct_non_default = {d["label"] for _, d in agent_rows
                            if d["label"] not in (None, "pre-existing")}
    runtime.require_floor(len(distinct_non_default), MIN_NON_DEFAULT_VALUES,
                          "distinct non-default labels")
    mismatches = [(m["name"], m["label"], d["label"]) for m, d in agent_rows
                  if d["label"] != m["label"]]
    assert not mismatches, f"agent-placed label drift (sent, got): {mismatches}"
    script_mismatches = [(d["entity_name"], d["label"]) for d in script_rows
                         if d["label"] is not None]
    assert not script_mismatches, (
        f"script-placed (no-operator) rows unexpectedly carry a label: {script_mismatches}")


def test_placed_tick_live(rig, rcon):
    agent_rows = _agent_rows(rig)
    script_rows = _script_rows(rig)
    runtime.require_floor(len(agent_rows), MIN_ROWS_PER_LIVE_COLUMN,
                          "agent-placed matched rows")
    now = runtime.game_tick(rcon)
    non_default = [d for _, d in agent_rows if d["placed_tick"] is not None]
    runtime.require_floor(len(non_default), MIN_NON_DEFAULT_VALUES,
                          "rows with non-NULL placed_tick")
    bad = [(m["name"], d["placed_tick"]) for m, d in agent_rows
           if d["placed_tick"] is None
           or not (rig["allocated_at_tick"] < int(d["placed_tick"]) <= now)]
    assert not bad, (
        f"agent-placed placed_tick not plausible: {bad} "
        f"(allocated_at={rig['allocated_at_tick']}, now={now})")
    script_bad = [(d["entity_name"], d["placed_tick"]) for d in script_rows
                 if d["placed_tick"] is not None]
    assert not script_bad, (
        f"script-placed ('pre-existing') rows unexpectedly carry placed_tick: {script_bad}")


def test_raw_data_live(rig):
    eng, db, keys = _joined_engine_db(rig)
    runtime.require_floor(len(keys), MIN_ROWS_PER_LIVE_COLUMN, "matched rows with raw_data")
    bad = []
    for k in keys:
        e, d = eng[k], db[k]
        raw = d.get("raw_data")
        if raw is None:
            bad.append((d["entity_name"], "raw_data is NULL"))
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as exc:
            bad.append((d["entity_name"], f"raw_data not valid JSON: {exc}"))
            continue
        name = payload.get("name")
        if name != d["entity_name"] or name != e["name"]:
            bad.append((d["entity_name"], f"raw_data name mismatch: {name!r}"))
        pos = payload.get("position") or {}
        try:
            px, py = float(pos["x"]), float(pos["y"])
        except (KeyError, TypeError, ValueError):
            bad.append((d["entity_name"], f"raw_data position missing/malformed: {pos!r}"))
            continue
        if abs(px - float(d["position_x"])) > TOL or abs(py - float(d["position_y"])) > TOL:
            bad.append((d["entity_name"],
                       f"raw_data position {pos} != row ({d['position_x']}, {d['position_y']})"))
        raw_direction = payload.get("direction")
        if raw_direction is not None and int(raw_direction) != int(e["direction_int"]):
            bad.append((d["entity_name"],
                       f"raw_data direction {raw_direction} != engine {e['direction_int']}"))
    assert not bad, f"raw_data liveness failures: {bad}"
