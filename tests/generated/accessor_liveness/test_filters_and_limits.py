"""accessor_liveness / filters_and_limits group.

Cases (frozen spec: cases_for_group("filters_and_limits")):
- InserterMixin.set_filter                    engine DEAD (FILT-1), db DEAD (FILT-1 -> CONF-1)
- EntityOperationsAction.set_inventory_limit   engine LIVE (TEST-0, zero prior coverage)

InserterMixin.set_filter is a NATURAL PLANT (PLANTS.md N4/N5): it calls
EntityOperationsAction.set_entity_filter with inventory_type="inserter_filter"
(inserter.py:107); EntityInterface.lua's INVENTORY_TYPE_MAP (lines 135-145)
has no "inserter_filter" key, so `_resolve_inventory_type` raises a Lua
error() (EntityInterface.lua:163-166) before the entity's inventory is even
looked up, let alone mutated. On the Python side, RconHandler.execute_and_parse_json
(rcon_handler.py:134) turns that xpcall envelope into a RuntimeError. Both
cases below let that exception propagate naturally (no try/except) into the
xfail(strict) path per protocol -- if the mapping is ever fixed, the accessor
call stops raising, the assert underneath starts actually running, and (since
CONF-1 -- serialize_entity never emits filters, see fv_embodied_agent/utils/serialize.lua,
grepped clean of any "filter" key) the DB leg would still fail on the assert
itself. Either failure mode keeps both tests red until reconciled -- an XPASS
here means someone wired the mapping up (engine leg) or serialization (db leg)
and forgot to update this spec + the tracker.

EntityOperationsAction.set_inventory_limit has zero prior coverage (TEST-0;
DOC-GAP-1 -- no typed accessor wraps it) and is classified engine LIVE. API
pin: EntityInterface:set_inventory_limit (EntityInterface.lua:380-398) calls
`inventory.set_bar(limit)` directly with no unit translation. LuaInventory's
get_bar/set_bar semantics (resources/factorio-api/2.0.76/runtime/classes/LuaInventory.json:
"Get the current bar. This is the index at which the red area starts.")
mean the accessor's "limit" argument IS the raw 1-indexed bar value, not a
usable-slot count with an implicit +1/-1 translation -- there is no off-by-one
here despite the parameter's name suggesting one. Verified empirically below
(both targets read back exactly as passed).
"""

from __future__ import annotations

import json

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
    """One inserter (InserterMixin.set_filter target) + one iron-chest
    (EntityOperationsAction.set_inventory_limit target), placed within reach
    of the agent spawn. Script-placed (rig construction is COVERED per spec,
    not the surface under test).

    NOTE: "filter-inserter" is not a valid 2.0.76 entity name (create_entity
    -> "Unknown entity name: filter-inserter") -- 2.0 merged filter-inserter /
    stack-inserter / stack-filter-inserter into the base "inserter" prototype,
    which now carries filter slots directly (LuaEntity.get_filter/set_filter
    work on any inserter). The typed layer's ENTITY_CLASS_MAP (create_entity.py)
    still lists a separate "filter-inserter" -> FilterInserter class, which is
    dead/unplaceable in this engine version -- friction finding, not this
    family's claim to fix."""
    fx, fy = spawn_offset(cell, -3.5, 0.5)
    cx, cy = spawn_offset(cell, -1.5, 0.5)  # half-integer offset: iron-chest is
    # a 1x1 tile entity that Factorio snaps to the tile-center grid; a
    # whole-integer offset (e.g. -1.0) gets silently re-centered by
    # create_entity to the nearest .5, so the requested position stops
    # matching the engine's actual placed position -- friction finding.
    runtime.place(rcon, cell, "inserter", fx, fy, direction="north")
    runtime.place(rcon, cell, "iron-chest", cx, cy, direction="north")
    wait_ops_flushed(rcon)
    return {"inserter": (fx, fy), "iron_chest": (cx, cy)}


def _typed_entity(typed, name):
    e = typed["view"].get_entity(name)
    if e is None:
        raise runtime.SpecBug(f"typed view returned no {name} (reachable gate?)")
    return e


def _db_raw(instance, rcon, name, pos):
    con = runtime.load_db(instance, runtime.game_tick(rcon))
    rows = con.execute(
        "SELECT raw_data FROM map_entity WHERE entity_name = ? "
        "AND abs(position_x - ?) < 0.01 AND abs(position_y - ?) < 0.01",
        [name, pos[0], pos[1]],
    ).fetchall()
    return rows


# --- positive controls (GREEN: the channels can see filters/rig rows) --------

def test_engine_channel_sees_scripted_filter(rcon, cell, rig):
    """Prove ENGINE_READS["filter"] can see a real engine-level filter change
    (script-set, table form {name=...} per ItemFilter union) -- so the DEAD
    result on the accessor case below is a real finding, not channel blindness."""
    pos = rig["inserter"]
    res = runtime.lua_strict(rcon, f"""
        local e = game.surfaces[1].find_entity('inserter', {{x={pos[0]},y={pos[1]}}})
        e.set_filter(1, {{name='iron-plate'}})
        local v = {ENGINE_READS["filter"]}
        e.set_filter(1, nil)
        return {{value = v}}
    """)
    assert res["value"] == "iron-plate", (
        "engine channel blind: scripted set_filter(1, {name='iron-plate'}) not "
        f"observed via ENGINE_READS['filter'] (saw {res!r})")


def test_db_channel_has_rig_rows(instance, rcon, rig):
    for name, key in (("inserter", "inserter"),
                       ("iron-chest", "iron_chest")):
        rows = _db_raw(instance, rcon, name, rig[key])
        assert rows, f"DB control failed: no map_entity row for rig {name}"


# --- InserterMixin.set_filter (LIVE since the 2026-07-11 FILT-1 fix) ---------
# History: baseline xfailed as PLANTS N4/N5 (Lua INVENTORY_TYPE_MAP lacked
# 'inserter_filter'; serialize emitted no filters). Fix: entity-level filter
# route in EntityInterface:set_filter (2.0 use_filters + entity.set_filter)
# + filter contract in serialize's inserter branch. Engine leg went
# strict-XPASS -> reconciled here to LIVE with the floors enforced.

def test_set_filter_mutates_engine_filter(rcon, cell, typed, rig):
    pos = rig["inserter"]
    pre = engine_read(rcon, cell, "inserter", pos[0], pos[1], ENGINE_READS["filter"])
    assert not pre.get("missing"), "rig control failed: inserter missing"
    ins = _typed_entity(typed, "inserter")
    seen = []
    for item in ("iron-plate", "copper-plate"):  # MIN_DISTINCT_TARGETS=2
        ok = ins.set_filter(1, item)
        assert ok is True, f"set_filter(1, {item!r}) reported failure"
        post = engine_read(rcon, cell, "inserter", pos[0], pos[1],
                           ENGINE_READS["filter"])
        assert post.get("value") == item, (
            f"engine filter slot 1 != {item!r} (saw {post!r}): FILT-1 regressed")
        seen.append(post.get("value"))
    assert len(set(seen)) == 2, f"distinct-targets floor unmet: {seen}"
    uf = engine_read(rcon, cell, "inserter", pos[0], pos[1],
                     ENGINE_READS["use_filters"])
    assert uf.get("value") is True, "use_filters not enabled by the accessor"


def test_set_filter_reaches_db_filters(instance, rcon, cell, typed, rig):
    pos = rig["inserter"]
    db_pre_rows = _db_raw(instance, rcon, "inserter", pos)
    if not db_pre_rows:
        raise runtime.SpecBug("DB control missing: rig row absent before set_filter")
    ins = _typed_entity(typed, "inserter")
    ins.set_filter(1, "iron-plate")
    wait_ops_flushed(rcon)
    db_post_rows = _db_raw(instance, rcon, "inserter", pos)
    assert db_post_rows, "DB control failed: rig row vanished after set_filter"
    raw_cell = db_post_rows[0][0]
    raw = json.loads(raw_cell) if isinstance(raw_cell, str) else (raw_cell or {})
    # Real serialized shape (verified live 2026-07-11):
    # raw_data.inserter = {..., use_filters, filter_mode, filters: [{index, name}]}
    ins_data = raw.get("inserter") or {}
    filters = ins_data.get("filters") or []
    assert any(
        isinstance(f, dict) and f.get("name") == "iron-plate"
        for f in filters
    ), (
        f"map_entity.raw_data.inserter has no 'iron-plate' filter (inserter="
        f"{ins_data!r}); the config-upsert spine dropped the contract (CONF-1)")
    assert ins_data.get("use_filters") is True, (
        f"raw_data.inserter.use_filters not recorded (inserter={ins_data!r})")


# --- EntityOperationsAction.set_inventory_limit (LIVE, TEST-0) --------------

def test_set_inventory_limit_mutates_engine_bar(rcon, cell, typed, rig):
    from FactoryVerse.game.factory.types import MapPosition

    pos = rig["iron_chest"]
    entity_ops = typed["entity_ops"]

    pre = int(engine_read(rcon, cell, "iron-chest", pos[0], pos[1],
                           ENGINE_READS["bar"])["value"])

    # REQUIRE_PRECONDITION_DELTA: first target must differ from the engine
    # pre-state, or a stale-read false green is possible.
    target1 = 5 if pre != 5 else 6
    assert target1 != pre, (
        f"precondition floor unmet: chosen target1={target1} equals engine "
        f"pre-state bar={pre}")
    entity_ops.set_inventory_limit(
        "iron-chest", "chest", target1,
        position=MapPosition(x=pos[0], y=pos[1]))
    post1 = int(engine_read(rcon, cell, "iron-chest", pos[0], pos[1],
                             ENGINE_READS["bar"])["value"])
    # Pass-through semantics (EntityInterface.lua:396 `inventory.set_bar(limit)`,
    # no +-1 translation): get_bar() reads back exactly the limit passed.
    assert post1 == target1, (
        f"engine bar after set_inventory_limit(limit={target1}) = {post1}, "
        f"expected {target1} (pass-through set_bar semantics)")

    # MIN_DISTINCT_TARGETS: a second, distinct value must also be reflected --
    # a single target can green on a stale read.
    target2 = 10 if target1 != 10 else 11
    assert target2 != target1
    entity_ops.set_inventory_limit(
        "iron-chest", "chest", target2,
        position=MapPosition(x=pos[0], y=pos[1]))
    post2 = int(engine_read(rcon, cell, "iron-chest", pos[0], pos[1],
                             ENGINE_READS["bar"])["value"])
    assert post2 == target2, (
        f"engine bar after set_inventory_limit(limit={target2}) = {post2}, "
        f"expected {target2} (pass-through set_bar semantics)")

    assert len({post1, post2}) == MIN_DISTINCT_TARGETS, (
        f"distinct-targets floor: expected {MIN_DISTINCT_TARGETS} distinct "
        f"engine bar values, saw {{post1: {post1}, post2: {post2}}}")
