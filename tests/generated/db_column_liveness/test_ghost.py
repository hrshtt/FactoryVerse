"""ghost group: all 10 columns (ghost_name, position_x/y, chunk_x/y, direction,
placed_tick, placed_by, label, raw_data).

Claim (frozen, liveness_spec): ghost_name/position/chunk are LIVE (exact
agreement with independent engine truth); direction is MISREPRESENTED (same
class as map_entity.direction, tracker NEW-2026-07-08 -- see PLANTS.md);
placed_tick/placed_by/label/raw_data are classified LIVE by the frozen spec
(they are not in liveness_spec's known-dead registry).

RIG-ORDERING (lesson carried over from test_map_entity_builder.py's already-
established finding): re_snapshot_and_wait unconditionally re-runs the FULL
chunk gather and stamps every entity/ghost it finds with a builder-less
"pre-existing" marker (Map.lua:1376-1400 pre_existing_builder_info). This rig
establishes the baseline snapshot ONCE, BEFORE placing anything, then never
re-triggers a full re-snapshot; per-event ghost writes go straight to the
(synchronous) ghosts-updates.jsonl log (snapshot.append_ghost_operation ->
helpers.write_file), so builder metadata from placements made after the
baseline survives untouched into the DB.

EMPIRICAL FINDING (this sub-agent, cross-checked against static code and the
sibling test_map_entity_builder.py's proven-correct pattern for map_entity):
placed_tick / placed_by / label are a NEW mirage, not yet in the frozen
registry (liveness_spec.py classifies them LIVE) --

- serialize.serialize_ghost (src/fv_embodied_agent/utils/serialize.lua:476-478)
  nests builder metadata exactly like serialize_entity does:
  `data.builder = builder_info` (builder_info = {agent_id, player_id, label,
  placed_tick}). It NEVER emits a `placed_by` key at any level, nested or not
  -- there is no "who placed this" concept the mod computes under that name.
- loader.py's `_insert_entity` (map_entity path, line 504) correctly reads
  `data.get("builder", {})` and pulls agent_id/label/placed_tick from it --
  this is WHY the map_entity_builder group found those columns LIVE.
- loader.py's `_insert_ghost` (line 537-566) reads FLAT top-level
  `data.get("placed_by")` / `data.get("placed_tick")` / `data.get("label")` --
  never `data.get("builder", {})`. The ghost loader was never updated to
  match the entity loader's nesting-aware extraction.

Net effect: placed_tick and label ARE computed by the mod (visible in
raw_data as raw_data["builder"]["label"/"placed_tick"]) for ghosts placed
through the agent's `place_entity(ghost=true, label=...)` path, but the
ghost table's placed_tick/label columns are always NULL regardless -- a
structurally-absent value the docs promise while the mod genuinely has it
(README failure semantics: strict-xfail RED-FINDING). placed_by has no
engine/mod-side value under ANY name for ghosts (not even nested), so its
NULL is closer to "nothing to report" -- but the doc's promised semantics
("Who placed this ghost (agent/player)") is unfulfilled all the same, since
agent_id/label ARE knowable and simply never reach the column. Encoded as a
strict xfail alongside the other two for the same reason (the mirage class),
not registered in liveness_spec.py (sub-agent may not edit _frozen/) -- flag
to the orchestrator to add a NEW-2026-07-08-class entry for
("ghost","placed_by"), ("ghost","placed_tick"), ("ghost","label").

To make this a decisive, evidence-backed finding rather than a
"NULL-because-nothing-to-report" false positive, one rig ghost is placed
through the real agent placement path (agent_<id>.place_entity(...,
ghost=true, label=...)), which DOES populate builder_info with a genuine
agent_id/label/placed_tick (verified present in that row's raw_data).
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
    cases_for_group,
)

TOL = 1e-6

CASES = {c.column: c for c in cases_for_group("ghost")}


def _reason(column: str) -> str:
    c = CASES[column]
    return f"RED-FINDING {c.tracker}: {c.note}"


# Raw script-placed ghosts (create_entity{name='entity-ghost', raise_built=true}):
# no player/agent context -> builder_info nil entirely for these.
# wooden-chest/stone-furnace/small-electric-pole are non-rotatable prototypes
# (engine silently forces direction=north regardless of what's requested --
# confirmed empirically this run); only rotatable prototypes (drill,
# inserter, belt -- same set the map_entity_core golden rig uses for its
# non-default directions) actually carry a non-default direction.
# (inner_name, dx, dy, direction)
RAW_GHOSTS = [
    ("stone-furnace", 70.0, 70.0, "north"),
    ("burner-mining-drill", 74.0, 70.0, "east"),
    ("inserter", 77.5, 70.5, "south"),
    ("transport-belt", 80.0, 70.0, "west"),
    ("wooden-chest", 82.0, 70.0, "north"),
]

# Agent-attributed ghost: real builder_info (agent_id + label + placed_tick),
# via the actual agent.place_entity path (ghost=true bypasses the reach/item
# checks -- placement.lua:56 `if not ghost and not self:can_reach_position`).
# (inner_name, dx, dy, direction_int, label)
AGENT_GHOST = ("iron-chest", 84.0, 70.0, 0, "probe-agent-ghost")


def _place_ghost(rcon, session, inner_name, x, y, direction="north"):
    res = runtime.lua_strict(rcon, f"""
        local e = game.surfaces[1].create_entity{{
            name='entity-ghost', inner_name='{inner_name}',
            position={{x={x},y={y}}},
            direction=defines.direction.{direction},
            force='{session.force_name}', raise_built=true}}
        if e == nil then return {{success=false}} end
        return {{success=true, ghost_name=e.ghost_name, x=e.position.x, y=e.position.y}}
    """)
    if not res.get("success"):
        raise runtime.SpecBug(
            f"ghost rig placement failed: {inner_name} at ({x},{y}) in cell "
            f"{session.cell_index} -- adjust the rig, not the claim")
    return res


def _ghost_probe(rcon, bounds, force):
    """Independent engine truth for entity-ghost entities in bounds.
    runtime.engine_entities_in EXCLUDES ghosts by design -- this is our own
    ghost-specific probe, sharing no code with the mod or the loader."""
    res = runtime.lua_strict(rcon, f"""
        local dirname = {{}}
        for k, v in pairs(defines.direction) do dirname[v] = k end
        local out = {{}}
        for _, e in pairs(game.surfaces[1].find_entities_filtered{{
                area={runtime.bounds_lua(bounds)}, type='entity-ghost', force='{force}'}}) do
            out[#out+1] = {{
                ghost_name = e.ghost_name,
                x = e.position.x, y = e.position.y,
                direction = dirname[e.direction],
                direction_int = e.direction,
            }}
        end
        return {{entities = out, tick = game.tick}}
    """)
    return runtime.as_list(res.get("entities"))


@pytest.fixture(scope="module")
def rig(rcon, cell, instance):
    # Baseline snapshot FIRST (see module docstring: a full re-snapshot AFTER
    # placement would squash real builder metadata back to a builder-less
    # "pre-existing" stamp for anything the area-scan finds).
    runtime.re_snapshot_and_wait(rcon, cell.bounds)

    ox, oy = runtime.cell_origin(cell.cell_index)
    placed = []
    for name, dx, dy, direction in RAW_GHOSTS:
        res = _place_ghost(rcon, cell, name, ox + dx, oy + dy, direction)
        placed.append({"ghost_name": res["ghost_name"], "x": res["x"], "y": res["y"],
                       "direction": direction, "path": "raw"})
    runtime.require_floor(len(placed), MIN_RIG_ENTITIES, "raw ghost rig entities placed")

    agent_name, agent_dx, agent_dy, agent_direction, agent_label = AGENT_GHOST
    ax, ay = ox + agent_dx, oy + agent_dy
    agent_res = runtime.lua_strict(rcon, f"""
        return remote.call('agent_{cell.agent_id}', 'place_entity',
            '{agent_name}', {{x={ax},y={ay}}}, {agent_direction}, true, '{agent_label}')
    """)
    if not agent_res.get("success"):
        raise runtime.SpecBug(
            f"agent-attributed ghost placement failed: {agent_res.get('error') or agent_res}")
    pos = agent_res.get("position") or {"x": ax, "y": ay}
    placed.append({"ghost_name": agent_name, "x": pos["x"], "y": pos["y"],
                   "direction": "north", "path": "agent", "label": agent_label})

    engine = _ghost_probe(rcon, cell.bounds, cell.force_name)
    runtime.require_floor(len(engine), MIN_RIG_ENTITIES, "engine-truth ghosts")

    con = runtime.load_db(instance, current_game_tick=runtime.game_tick(rcon))
    b = cell.bounds
    rows = con.execute(
        "SELECT ghost_name, position_x, position_y, chunk_x, chunk_y, direction, "
        "placed_tick, placed_by, label, raw_data FROM ghost "
        "WHERE position_x >= ? AND position_x < ? AND position_y >= ? AND position_y < ?",
        [b["left_top"]["x"], b["right_bottom"]["x"],
         b["left_top"]["y"], b["right_bottom"]["y"]]).fetchall()
    cols = ("ghost_name", "position_x", "position_y", "chunk_x", "chunk_y", "direction",
            "placed_tick", "placed_by", "label", "raw_data")
    db = [dict(zip(cols, r)) for r in rows]

    return {"placed": placed, "engine": engine, "db": db,
            "agent_id": cell.agent_id, "agent_label": agent_label}


def _by_pos(items, xk, yk):
    return {(round(float(i[xk]), 3), round(float(i[yk]), 3)): i for i in items}


def _matched_pairs(rig):
    """(engine, db) pairs keyed by exact position; missing rows are the
    ghost_name/position liveness failure surface, asserted in the tests."""
    eng = _by_pos(rig["engine"], "x", "y")
    db = _by_pos(rig["db"], "position_x", "position_y")
    return eng, db, [(eng[k], db[k]) for k in eng.keys() & db.keys()]


def test_ghost_name_and_position_live(rig):
    """Two-sided set comparison (no missing ghosts, no phantoms) + exact name
    agreement, per group-specific guidance."""
    eng, db, pairs = _matched_pairs(rig)
    runtime.require_floor(len(eng), MIN_ROWS_PER_LIVE_COLUMN, "engine ghosts")
    missing_in_db = sorted(str(k) + ":" + v["ghost_name"] for k, v in eng.items() if k not in db)
    phantom_in_db = sorted(str(k) + ":" + v["ghost_name"] for k, v in db.items() if k not in eng)
    assert not missing_in_db, f"engine ghosts absent from ghost table: {missing_in_db}"
    assert not phantom_in_db, f"ghost rows with no engine ghost: {phantom_in_db}"
    for e, d in pairs:
        assert d["ghost_name"] == e["ghost_name"], (e, d)


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
                          "ghosts with non-default direction")
    return pairs


@pytest.mark.xfail(strict=True, reason=_reason("direction"))
def test_direction_documented_semantics(rig):
    pairs = _direction_pairs(rig)
    mismatches = [(e["ghost_name"], e["direction"], d["direction"])
                  for e, d in pairs
                  if e["direction"] is not None and d["direction"] != e["direction"]]
    assert not mismatches, f"direction representation drift (engine name vs DB): {mismatches}"


def test_direction_value_derivable(rig):
    """The honest other half: the int VALUES are engine-true (the column is
    misrepresented, not dead) -- same split as map_entity_core's golden
    pattern."""
    pairs = _direction_pairs(rig)
    mismatches = [(e["ghost_name"], e["direction_int"], d["direction"])
                  for e, d in pairs
                  if d["direction"] is None or int(d["direction"]) != int(e["direction_int"])]
    assert not mismatches, f"direction ints drifted (engine vs DB): {mismatches}"


def _agent_row(rig):
    """The one ghost placed through the real agent path -- the row that
    should carry non-NULL builder metadata if the column-lift worked."""
    agent_placed = next(p for p in rig["placed"] if p["path"] == "agent")
    db = _by_pos(rig["db"], "position_x", "position_y")
    key = (round(float(agent_placed["x"]), 3), round(float(agent_placed["y"]), 3))
    runtime.require_floor(1 if key in db else 0, 1, "agent-attributed ghost row present")
    return agent_placed, db[key]


def _raw_placed_rows(rig):
    raw_placed = [p for p in rig["placed"] if p["path"] == "raw"]
    db = _by_pos(rig["db"], "position_x", "position_y")
    rows = [db[(round(float(p["x"]), 3), round(float(p["y"]), 3))] for p in raw_placed
            if (round(float(p["x"]), 3), round(float(p["y"]), 3)) in db]
    runtime.require_floor(len(rows), MIN_ROWS_PER_LIVE_COLUMN, "raw-placed ghost rows")
    return rows


@pytest.mark.xfail(strict=True, reason="RED-FINDING NEW-2026-07-08-class (not yet in "
                   "liveness_spec registry -- flag to orchestrator): ghost.placed_tick is "
                   "computed by the mod into raw_data['builder']['placed_tick'] for "
                   "agent-placed ghosts (verified this run) but loader.py:_insert_ghost reads "
                   "flat data.get('placed_tick') instead of data.get('builder', {}).get"
                   "('placed_tick') (contrast _insert_entity, line 504-508, which IS "
                   "builder-aware) -- always NULL regardless of path")
def test_placed_tick_documented_liveness(rig, rcon):
    agent_placed, agent_db = _agent_row(rig)
    now = runtime.game_tick(rcon)
    assert agent_db["placed_tick"] is not None, (
        f"placed_tick is NULL for the agent-attributed ghost {agent_placed}")
    assert 0 < int(agent_db["placed_tick"]) <= now, (
        f"placed_tick {agent_db['placed_tick']} not plausible (now={now})")


@pytest.mark.xfail(strict=True, reason="RED-FINDING NEW-2026-07-08-class (not yet in "
                   "liveness_spec registry -- flag to orchestrator): ghost.label is computed "
                   "by the mod into raw_data['builder']['label'] for agent-placed ghosts "
                   "(verified this run, label='probe-agent-ghost') but loader.py:_insert_ghost "
                   "reads flat data.get('label') instead of data.get('builder', {}).get('label') "
                   "(contrast _insert_entity, builder-aware) -- always NULL regardless of path")
def test_label_documented_liveness(rig):
    agent_placed, agent_db = _agent_row(rig)
    assert agent_db["label"] == agent_placed["label"], (
        f"label drift/absence: sent {agent_placed['label']!r}, got {agent_db['label']!r}")


@pytest.mark.xfail(strict=True, reason="RED-FINDING NEW-2026-07-08-class (not yet in "
                   "liveness_spec registry -- flag to orchestrator): docs promise "
                   "'Who placed this ghost (agent/player)'; the mod computes agent_id/player_id "
                   "into raw_data['builder'] (same builder_info shape as map_entity) but never "
                   "emits a key named placed_by at ANY level, and even if it did, "
                   "loader.py:_insert_ghost never reads data.get('builder', {}) for the ghost "
                   "path -- the documented semantic is unreachable via any known write path")
def test_placed_by_documented_liveness(rig):
    agent_placed, agent_db = _agent_row(rig)
    assert agent_db["placed_by"] is not None, (
        f"placed_by is NULL for the agent-attributed ghost (agent_id={rig['agent_id']}) "
        f"placed via agent_{rig['agent_id']}.place_entity: {agent_placed}")


def test_builder_metadata_present_in_raw_data(rig):
    """Non-xfail companion: the value the ghost column-lift drops IS present
    inside raw_data's JSON blob for the agent-attributed ghost -- the mod
    computes it, only the loader fails to read the nested 'builder' key
    (confirmed by static read of loader.py:537-566 alongside the map_entity
    path at line 504, which IS builder-aware)."""
    agent_placed, agent_db = _agent_row(rig)
    assert agent_db["placed_tick"] is None and agent_db["label"] is None, (
        "placed_tick/label column no longer NULL for the agent-attributed ghost -- "
        "mirage may be fixed; re-check the xfail tests above before touching this companion")

    raw = json.loads(agent_db["raw_data"]) if agent_db["raw_data"] else {}
    builder = raw.get("builder") or {}
    assert builder.get("label") == agent_placed["label"], (
        f"raw_data['builder']['label'] mismatch/absent: {builder!r} vs sent "
        f"{agent_placed['label']!r} -- the mod-side evidence for the finding is missing")
    assert builder.get("agent_id") == rig["agent_id"], (
        f"raw_data['builder']['agent_id'] mismatch/absent: {builder!r} vs {rig['agent_id']!r}")
    assert isinstance(builder.get("placed_tick"), int) and builder["placed_tick"] > 0, (
        f"raw_data['builder']['placed_tick'] missing/implausible: {builder!r}")


def test_raw_data_matches_row(rig):
    """raw_data parses as JSON and agrees with the row's ghost_name/position/
    chunk columns (this part of the payload is top-level, not nested under
    'builder' -- see serialize_ghost -- and IS lifted, so this stays a plain
    non-xfail LIVE assertion)."""
    eng, db, pairs = _matched_pairs(rig)
    runtime.require_floor(len(pairs), MIN_ROWS_PER_LIVE_COLUMN, "matched rows with raw_data")
    bad = []
    for e, d in pairs:
        raw = d.get("raw_data")
        if raw is None:
            bad.append((d["ghost_name"], "raw_data is NULL"))
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as exc:
            bad.append((d["ghost_name"], f"raw_data not valid JSON: {exc}"))
            continue
        name = payload.get("ghost_name")
        if name != d["ghost_name"] or name != e["ghost_name"]:
            bad.append((d["ghost_name"], f"raw_data ghost_name mismatch: {name!r}"))
        pos = payload.get("position") or {}
        try:
            px, py = float(pos["x"]), float(pos["y"])
        except (KeyError, TypeError, ValueError):
            bad.append((d["ghost_name"], f"raw_data position missing/malformed: {pos!r}"))
            continue
        if abs(px - float(d["position_x"])) > TOL or abs(py - float(d["position_y"])) > TOL:
            bad.append((d["ghost_name"],
                       f"raw_data position {pos} != row ({d['position_x']}, {d['position_y']})"))
        raw_direction = payload.get("direction")
        if raw_direction is not None and int(raw_direction) != int(e["direction_int"]):
            bad.append((d["ghost_name"],
                       f"raw_data direction {raw_direction} != engine {e['direction_int']}"))
    assert not bad, f"raw_data liveness failures: {bad}"
