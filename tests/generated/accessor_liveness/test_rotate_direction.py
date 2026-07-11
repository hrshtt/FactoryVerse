"""accessor_liveness / rotate_direction group (PILOT, orchestrator-authored).

Cases (frozen spec: cases_for_group("rotate_direction")):
- RotatableMixin.rotate        engine LIVE, db LIVE (ROT-1 fixed 2026-07-11)
- Rotatable180Mixin.rotate_180 engine LIVE, db LIVE (ROT-1 fixed 2026-07-11)

History (the reconciliation loop, kept for the audit trail):
- Baseline 2026-07-11: all three accessor cases strict-xfailed as PLANTS
  N1-N3 (ROT-1: mixin was a client-side no-op — and deeper, typed entities
  never received a direction attribute at all, so rotate() died on
  AttributeError before its no-op).
- Fix: EntityOperationsAction.rotate_entity wired to the remote method;
  mixins claim `direction` from the constructor chain and sync local state
  from the ENGINE-reported new direction.
- Flip: all three went strict-XPASS -> suite red -> this reconciliation.
  Assertions are now exact promised-value equality, not just "changed".

Positive controls retained (channel validity is independent of the fix):
- engine channel: script-rotate via raw Lua -> engine direction changes
- DB channel: placed rig row exists in map_entity with a direction value
"""

from __future__ import annotations

import pytest

from _frozen import runtime
from _frozen.accessor_spec import (
    ENGINE_READS,
    MIN_DISTINCT_TARGETS,
    wait_ops_flushed,
)
from conftest import engine_read, spawn_offset

pytestmark = pytest.mark.live


# --- rig ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def rig(rcon, cell):
    """One inserter (4-way rotatable) + one splitter (180 rotatable), placed
    within reach of the agent spawn. Script-placed (rig construction is not
    the surface under test; placement itself is COVERED per spec).
    NOTE: 1x1 entities snap to tile-centers — offsets must be half-integer."""
    ix, iy = spawn_offset(cell, -3.5, 0.5)
    sx, sy = spawn_offset(cell, 3.0, 2.5)   # splitter is 2x1; keep clear of agent
    runtime.place(rcon, cell, "inserter", ix, iy, direction="north")
    runtime.place(rcon, cell, "splitter", sx, sy, direction="north")
    wait_ops_flushed(rcon)
    return {"inserter": (ix, iy), "splitter": (sx, sy)}


def _engine_direction(rcon, cell, name, pos):
    res = engine_read(rcon, cell, name, pos[0], pos[1], ENGINE_READS["direction"])
    if res.get("missing"):
        raise runtime.SpecBug(f"rig entity {name} missing at {pos}")
    return int(res["value"])


def _typed_entity(typed, name):
    e = typed["view"].get_entity(name)
    if e is None:
        raise runtime.SpecBug(f"typed view returned no {name} (reachable gate?)")
    return e


def _db_direction(instance, rcon, name, pos):
    con = runtime.load_db(instance, runtime.game_tick(rcon))
    rows = con.execute(
        "SELECT direction FROM map_entity WHERE entity_name = ? "
        "AND abs(position_x - ?) < 0.01 AND abs(position_y - ?) < 0.01",
        [name, pos[0], pos[1]],
    ).fetchall()
    return rows


# --- positive controls (GREEN: the channels can see rotation) -----------------

def test_engine_channel_sees_scripted_rotation(rcon, cell, rig):
    pos = rig["inserter"]
    pre = _engine_direction(rcon, cell, "inserter", pos)
    res = runtime.lua_strict(rcon, f"""
        local e = game.surfaces[1].find_entity('inserter', {{x={pos[0]},y={pos[1]}}})
        e.rotate()
        return {{value = e.direction}}
    """)
    post = int(res["value"])
    assert post != pre, "engine channel blind: scripted rotate() not observed"
    # restore for the accessor cases
    runtime.lua_strict(rcon, f"""
        local e = game.surfaces[1].find_entity('inserter', {{x={pos[0]},y={pos[1]}}})
        while e.direction ~= {pre} do e.rotate() end
        return {{value = e.direction}}
    """)


def test_db_channel_has_rig_rows(instance, rcon, rig):
    for name in ("inserter", "splitter"):
        rows = _db_direction(instance, rcon, name, rig[name])
        assert rows, f"DB control failed: no map_entity row for rig {name}"


# --- the accessor cases (LIVE since the 2026-07-11 ROT-1 fix) ------------------

def test_rotate_mutates_engine_direction(rcon, cell, typed, rig):
    pos = rig["inserter"]
    ins = _typed_entity(typed, "inserter")
    seen = []
    for _ in range(MIN_DISTINCT_TARGETS):
        before = _engine_direction(rcon, cell, "inserter", pos)
        promised = ins.rotate()  # promises a 90-degree engine rotation
        after = _engine_direction(rcon, cell, "inserter", pos)
        assert after != before, (
            f"engine direction unchanged ({before} -> {after}): ROT-1 regressed")
        assert after == promised.value, (
            f"engine direction {after} != promised {promised.value} "
            f"({promised.name}); accessor and engine disagree")
        seen.append(after)
    assert len(set(seen)) == MIN_DISTINCT_TARGETS, (
        f"distinct-targets floor: expected {MIN_DISTINCT_TARGETS} distinct "
        f"engine directions, saw {seen}")


def test_rotate_180_mutates_engine_direction(rcon, cell, typed, rig):
    pos = rig["splitter"]
    before = _engine_direction(rcon, cell, "splitter", pos)
    sp = _typed_entity(typed, "splitter")
    promised = sp.rotate_180()  # promises a 180-degree engine rotation
    after = _engine_direction(rcon, cell, "splitter", pos)
    assert after != before, (
        f"engine direction unchanged ({before} -> {after}): ROT-1 regressed")
    assert after == promised.value, (
        f"engine direction {after} != promised {promised.value} "
        f"({promised.name}); accessor and engine disagree")


def test_rotate_reaches_db_direction(instance, rcon, cell, typed, rig):
    pos = rig["inserter"]
    db_pre_rows = _db_direction(instance, rcon, "inserter", pos)
    if not db_pre_rows:
        raise runtime.SpecBug("DB control missing: rig row absent before rotate")
    ins = _typed_entity(typed, "inserter")
    promised = ins.rotate()
    wait_ops_flushed(rcon)
    db_post_rows = _db_direction(instance, rcon, "inserter", pos)
    assert db_post_rows, "rig row vanished from map_entity after rotate()"
    # REPR-1: the column is VARCHAR holding the raw defines int — compare as int
    assert int(db_post_rows[0][0]) == promised.value, (
        f"DB direction {db_post_rows[0][0]!r} != promised {promised.value}; "
        "the rotated-op spine did not carry the mutation")
