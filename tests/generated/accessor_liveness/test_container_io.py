"""accessor_liveness / container_io group.

Cases (frozen spec: cases_for_group("container_io")):
- Container.store_item                       engine LIVE, db NOT_APPLICABLE
- Container.take_item                        engine LIVE, db NOT_APPLICABLE
- EntityOperationsAction.take_inventory_item  engine LIVE, db NOT_APPLICABLE
  (TEST-0: zero prior direct coverage)

Adjudicated boundary (PLANTS.md / accessor_spec.py, Harshit 2026-07-09):
inventory transfers get NO DB assertion — DB is a spatial reference + durable
contracts; volatile inventory state is ephemeral-bridge-only. Every assertion
below is engine-only.

Truth channels (frozen shapes, raw Lua only):
- chest contents: ENGINE_READS["chest_count"] (ITEM placeholder substituted)
  against the script-placed iron-chest, via conftest.engine_read.
- agent-side contents: the OTHER sanctioned raw channel (protocol point 5) —
  the agent character's main inventory read directly via
  find_entities_filtered{type='character'} + get_main_inventory():get_item_count,
  NOT remote 'agent_<id>' get_inventory_items (that goes through the mod's
  Agent.lua path; this stays pure LuaEntity/LuaInventory API, same posture as
  ENGINE_READS).

Partial-transfer semantics (anti-vacuity note in accessor_spec.py): every
assert here compares the ENGINE delta to what the accessor ITSELF reported
moving (InventoryItemPut.count / InventoryItemTaken.count), never to the
requested count — store_item can return partial-insert remainders per the
entity_ops.lua partial-insert contract.

Rig: one script-placed iron-chest within reach of the agent spawn (rig
construction is COVERED elsewhere per spec, not under test). Each real test
clears the chest itself at the top (raw Lua) so cases are order-independent
and each starts from the "chest starts empty" precondition the spec requires
be asserted explicitly.
"""

from __future__ import annotations

import pytest

from _frozen import runtime
from _frozen.accessor_spec import ENGINE_READS, MIN_TRANSFER_ITEMS
from conftest import engine_read, give_items, spawn_offset

from FactoryVerse.game.agent.embodied_actions.inventory import AgentInventory
from FactoryVerse.game.factory.types import MapPosition

pytestmark = pytest.mark.live

ITEM = "iron-plate"
STORE_COUNT = 5   # >= MIN_TRANSFER_ITEMS
TAKE_PRELOAD = 6  # baseline for take-back cases; > any single take_count below


# --- rig -----------------------------------------------------------------

@pytest.fixture(scope="module")
def rig(rcon, cell):
    """One iron-chest, script-placed within reach of the agent spawn.

    Offset must land on a half-integer (x.5, y.5): a 1x1 entity's collision
    box centers on the tile it's placed on, so create_entity SNAPS the actual
    position to the nearest tile center — an integer-offset request silently
    places the chest half a tile away from where find_entity later looks
    (confirmed empirically: (-2.0, 0.0) -> engine position (701.5, 384.5), a
    (0.5, 0.5) drift that makes every raw-Lua find_entity lookup miss)."""
    x, y = spawn_offset(cell, -2.5, 0.5)
    runtime.place(rcon, cell, "iron-chest", x, y, direction="north")
    return (x, y)


@pytest.fixture
def inventory(typed):
    return AgentInventory(typed["handler"], typed["placement"])


# --- raw-Lua probes (family-owned mechanics, not the surface under test) ---

def _chest_count(rcon, cell, pos, item_name: str) -> int:
    expr = ENGINE_READS["chest_count"].replace("ITEM", f"'{item_name}'")
    res = engine_read(rcon, cell, "iron-chest", pos[0], pos[1], expr)
    if res.get("missing"):
        raise runtime.SpecBug(f"rig chest missing at {pos}")
    return int(res["value"])


def _clear_chest(rcon, pos) -> None:
    res = runtime.lua_strict(rcon, f"""
        local e = game.surfaces[1].find_entity('iron-chest', {{x={pos[0]},y={pos[1]}}})
        if e == nil then error('rig chest missing at clear time') end
        e.get_inventory(defines.inventory.chest).clear()
        return {{ok = true}}
    """)
    if not res.get("ok"):
        raise runtime.SpecBug(f"chest clear failed: {res}")


def _scripted_insert(rcon, pos, item_name: str, count: int) -> int:
    """Preload the chest via a channel independent of Container.store_item,
    so take_item/take_inventory_item cases don't conflate with the store case."""
    res = runtime.lua_strict(rcon, f"""
        local e = game.surfaces[1].find_entity('iron-chest', {{x={pos[0]},y={pos[1]}}})
        if e == nil then error('rig chest missing at insert time') end
        local inserted = e.get_inventory(defines.inventory.chest)
            .insert({{name='{item_name}', count={count}}})
        return {{inserted = inserted}}
    """)
    return int(res["inserted"])


def _agent_item_count(rcon, cell, item_name: str) -> int:
    """The OTHER sanctioned raw channel: agent character main inventory,
    read directly via LuaEntity/LuaInventory (not the mod's get_inventory_items)."""
    res = runtime.lua_strict(rcon, f"""
        local chars = game.surfaces[1].find_entities_filtered{{
            type='character', force='{cell.force_name}'}}
        if #chars == 0 then return {{missing = true}} end
        local inv = chars[1].get_main_inventory()
        return {{value = inv and inv.get_item_count('{item_name}') or 0}}
    """)
    if res.get("missing"):
        raise runtime.SpecBug("agent character not found for inventory read")
    return int(res["value"])


def _typed_chest(typed):
    chest = typed["view"].get_entity("iron-chest")
    if chest is None:
        raise runtime.SpecBug("typed view returned no iron-chest (reachable gate?)")
    return chest


# --- A. Container.store_item ------------------------------------------------

def test_store_item_mutates_engine_chest_count(rcon, cell, typed, inventory, rig):
    _clear_chest(rcon, rig)
    pre = _chest_count(rcon, cell, rig, ITEM)
    assert pre == 0, f"precondition violated: chest not empty before store ({pre})"

    give_items(rcon, cell.agent_id, {ITEM: STORE_COUNT})
    chest = _typed_chest(typed)
    stacks = inventory.create_item_stacks(ITEM, count=STORE_COUNT, number_of_stacks=1)
    runtime.require_floor(sum(s.count for s in stacks), MIN_TRANSFER_ITEMS,
                           "store_item stack size")

    results = chest.store_item(stacks)  # promises engine chest += reported count
    reported_stored = sum(r.count for r in results)
    runtime.require_floor(reported_stored, MIN_TRANSFER_ITEMS,
                           "store_item reported count")

    post = _chest_count(rcon, cell, rig, ITEM)
    assert post - pre == reported_stored, (
        f"engine chest delta ({post - pre}) != accessor-reported stored count "
        f"({reported_stored}); store_item is a lying affordance")


# --- B. Container.take_item --------------------------------------------------

def test_take_item_mutates_engine_chest_count(rcon, cell, typed, rig):
    _clear_chest(rcon, rig)
    inserted = _scripted_insert(rcon, rig, ITEM, TAKE_PRELOAD)
    assert inserted == TAKE_PRELOAD, (
        f"rig precondition failed: scripted insert only placed "
        f"{inserted}/{TAKE_PRELOAD}")

    take_count = 3
    assert take_count >= MIN_TRANSFER_ITEMS
    assert take_count != TAKE_PRELOAD  # engine pre-state must differ from target

    agent_pre = _agent_item_count(rcon, cell, ITEM)
    chest = _typed_chest(typed)
    taken_stacks = chest.take_item(ITEM, take_count)  # promises chest -= reported, agent += reported
    reported_taken = sum(s.count for s in taken_stacks)
    runtime.require_floor(reported_taken, MIN_TRANSFER_ITEMS, "take_item reported count")

    chest_post = _chest_count(rcon, cell, rig, ITEM)
    agent_post = _agent_item_count(rcon, cell, ITEM)

    assert TAKE_PRELOAD - chest_post == reported_taken, (
        f"engine chest delta ({TAKE_PRELOAD - chest_post}) != accessor-reported "
        f"taken count ({reported_taken}); take_item is a lying affordance")
    assert agent_post - agent_pre == reported_taken, (
        f"agent inventory delta ({agent_post - agent_pre}) != accessor-reported "
        f"taken count ({reported_taken}); items vanished in transfer")


# --- C. EntityOperationsAction.take_inventory_item (TEST-0, no typed wrapper) ---

def test_entity_ops_take_inventory_item_mutates_engine_chest_count(rcon, cell, typed, rig):
    _clear_chest(rcon, rig)
    inserted = _scripted_insert(rcon, rig, ITEM, TAKE_PRELOAD)
    assert inserted == TAKE_PRELOAD, (
        f"rig precondition failed: scripted insert only placed "
        f"{inserted}/{TAKE_PRELOAD}")

    take_count = 4
    assert take_count >= MIN_TRANSFER_ITEMS
    assert take_count != TAKE_PRELOAD

    agent_pre = _agent_item_count(rcon, cell, ITEM)
    pos = MapPosition(x=rig[0], y=rig[1])
    result = typed["entity_ops"].take_inventory_item(
        "iron-chest", "chest", ITEM, count=take_count, position=pos)
    reported_taken = result.count
    runtime.require_floor(reported_taken, MIN_TRANSFER_ITEMS,
                           "take_inventory_item reported count")

    chest_post = _chest_count(rcon, cell, rig, ITEM)
    agent_post = _agent_item_count(rcon, cell, ITEM)

    assert TAKE_PRELOAD - chest_post == reported_taken, (
        f"engine chest delta ({TAKE_PRELOAD - chest_post}) != accessor-reported "
        f"taken count ({reported_taken}); take_inventory_item is a lying affordance")
    assert agent_post - agent_pre == reported_taken, (
        f"agent inventory delta ({agent_post - agent_pre}) != accessor-reported "
        f"taken count ({reported_taken}); items vanished in transfer")


# --- D. SYNTHETIC PLANT S2 (mandatory, PLANTS.md) ---------------------------

@pytest.mark.xfail(strict=True, reason="SYNTHETIC-PLANT")
def test_synthetic_plant_store_item_wrong_delta(rcon, cell, typed, inventory, rig):
    """Deliberately mutated expectation on the LIVE store_item surface: assert
    the engine count is off by a FIXED delta from the true transferred amount.
    Must fail (and does, mechanically, only because the assertion below is
    wrong) while test_store_item_mutates_engine_chest_count (A) passes. Does
    NOT call any shared assert helper with case A — the comparison here is a
    bare inline equality against a deliberately wrong target."""
    _clear_chest(rcon, rig)
    give_items(rcon, cell.agent_id, {ITEM: STORE_COUNT})
    chest = _typed_chest(typed)
    stacks = inventory.create_item_stacks(ITEM, count=STORE_COUNT, number_of_stacks=1)
    chest.store_item(stacks)

    post = _chest_count(rcon, cell, rig, ITEM)
    FIXED_WRONG_DELTA = 2
    wrong_target = STORE_COUNT + FIXED_WRONG_DELTA
    assert post == wrong_target, (
        f"SYNTHETIC-PLANT: expected mutated (wrong) chest count {wrong_target}, "
        f"engine actually shows {post}")
