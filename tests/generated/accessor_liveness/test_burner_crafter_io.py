"""accessor_liveness / burner_crafter_io group (sub-agent instantiated).

Cases (frozen spec: cases_for_group("burner_crafter_io")):
- BurnerMixin.add_fuel          engine LIVE, db NOT_APPLICABLE
- BurnerMixin.take_fuel         engine LIVE, db NOT_APPLICABLE  (TEST-0)
- CrafterMixin.add_ingredients  engine LIVE, db NOT_APPLICABLE
- CrafterMixin.take_products    engine LIVE, db NOT_APPLICABLE

Adjudicated boundary rule (accessor_spec.py, PLANTS.md): inventory/fuel
transfer accessors get NO DB assertion — DB is a spatial reference + durable
contracts; volatile state is ephemeral-bridge-only. Truth is ONLY raw Lua
engine reads via conftest.engine_read + accessor_spec.ENGINE_READS
(fuel_count, furnace_source_count, furnace_result_count). Accessor return
values are NEVER asserted as truth — only used to cross-check the reported
moved-count against the independently-read engine delta.

Rig: one script-placed stone-furnace (a burner; works without electricity)
within reach of the agent spawn. Module-scoped so all four cases share one
rig and run in sequence: A (add_fuel) -> C (add_ingredients) -> wait for the
furnace to actually smelt -> D (take_products) -> B (take_fuel). Each case's
before/after deltas are read around ITS OWN call.
"""

from __future__ import annotations

import time

import pytest

from _frozen import runtime
from _frozen.accessor_spec import (
    ENGINE_READS,
    MIN_TRANSFER_ITEMS,
    wait_ops_flushed,
)
from conftest import engine_read, give_items, spawn_offset

from FactoryVerse.game.factory.item.create_item import create_item_stack

pytestmark = pytest.mark.live

# --- rig quantities ------------------------------------------------------------

COAL_GIVEN = 15
ORE_GIVEN = 10
ADD_FUEL_AMOUNT = 8          # case A: coal moved agent -> furnace
ADD_ORE_AMOUNT = 6           # case C: iron-ore moved agent -> furnace
MIN_PLATES_TO_WAIT_FOR = 2   # case D: smelt floor before taking products
TAKE_FUEL_AMOUNT = 3         # case B: coal moved furnace -> agent
SMELT_WAIT_TIMEOUT_S = 60.0  # stone furnace: ~3.2s/plate at speed 1


# --- rig -------------------------------------------------------------------


@pytest.fixture(scope="module")
def rig(rcon, cell):
    """One stone-furnace within reach of the agent spawn, plus coal + iron-ore
    in the agent's inventory. Script-placed / script-given (rig construction
    is not the surface under test)."""
    fx, fy = spawn_offset(cell, 3.0, 0.0)
    runtime.place(rcon, cell, "stone-furnace", fx, fy, direction="north")
    give_items(rcon, cell.agent_id, {"coal": COAL_GIVEN, "iron-ore": ORE_GIVEN})
    wait_ops_flushed(rcon)
    return {"furnace": (fx, fy)}


def _typed_entity(typed, name):
    e = typed["view"].get_entity(name)
    if e is None:
        raise runtime.SpecBug(f"typed view returned no {name} (reachable gate?)")
    return e


def _engine_int(rcon, cell, name, pos, expr):
    res = engine_read(rcon, cell, name, pos[0], pos[1], expr)
    if res.get("missing"):
        raise runtime.SpecBug(f"rig entity {name} missing at {pos}")
    return int(res["value"])


def _item_expr(key: str, item_name: str) -> str:
    """Substitute the ITEM placeholder in a frozen ENGINE_READS expression."""
    return ENGINE_READS[key].replace("ITEM", f"'{item_name}'")


def _agent_coal_count(rcon, force_name: str) -> int:
    """RAW channel for case B's agent-side gain: find the cell's agent
    character entity directly on the surface (not remote.call('agent_<id>',
    'get_inventory_items') — a different, mod-owned inspection path) and read
    its main inventory. Forces are per-cell-isolated, so this is unambiguous."""
    res = runtime.lua_strict(rcon, f"""
        local chars = game.surfaces[1].find_entities_filtered{{type='character', force='{force_name}'}}
        if #chars == 0 then return {{missing=true}} end
        local inv = chars[1].get_main_inventory()
        return {{value = inv and inv.get_item_count('coal') or 0}}
    """)
    if res.get("missing"):
        raise runtime.SpecBug("agent character not found for raw inventory read")
    return int(res["value"])


# --- Case A: BurnerMixin.add_fuel (engine LIVE) --------------------------------


def test_add_fuel_mutates_engine_fuel_count(rcon, cell, typed, rig):
    pos = rig["furnace"]
    pre = _engine_int(rcon, cell, "stone-furnace", pos, ENGINE_READS["fuel_count"])
    assert pre == 0, f"precondition violated: fresh furnace fuel_count={pre} (rig not fresh)"

    furnace = _typed_entity(typed, "stone-furnace")
    stack = create_item_stack("coal", ADD_FUEL_AMOUNT, placement=typed["placement"])
    results = furnace.add_fuel([stack])
    reported = sum(r.count for r in results)

    post = _engine_int(rcon, cell, "stone-furnace", pos, ENGINE_READS["fuel_count"])
    delta = post - pre

    runtime.require_floor(reported, MIN_TRANSFER_ITEMS, "add_fuel reported moved coal")
    assert delta == reported, (
        f"accessor reported moving {reported} coal but engine fuel_count moved "
        f"by {delta} ({pre} -> {post}); write-side lie")


# --- Case C: CrafterMixin.add_ingredients (engine LIVE) -------------------------


def test_add_ingredients_mutates_engine_source_count(rcon, cell, typed, rig):
    pos = rig["furnace"]
    src_expr = _item_expr("furnace_source_count", "iron-ore")
    pre = _engine_int(rcon, cell, "stone-furnace", pos, src_expr)
    assert pre == 0, f"precondition violated: fresh furnace furnace_source_count={pre}"

    furnace = _typed_entity(typed, "stone-furnace")
    stack = create_item_stack("iron-ore", ADD_ORE_AMOUNT, placement=typed["placement"])
    results = furnace.add_ingredients([stack])
    reported = sum(r.count for r in results)

    post = _engine_int(rcon, cell, "stone-furnace", pos, src_expr)
    delta = post - pre

    runtime.require_floor(reported, MIN_TRANSFER_ITEMS, "add_ingredients reported moved iron-ore")
    assert delta == reported, (
        f"accessor reported moving {reported} iron-ore but engine "
        f"furnace_source_count moved by {delta} ({pre} -> {post}); write-side lie")


# --- Case D: CrafterMixin.take_products (engine LIVE) ---------------------------


def test_take_products_after_smelt(rcon, cell, typed, rig):
    """Depends on A + C already having fueled/fed the furnace. Waits for the
    engine to actually smelt (no air/pollution gating exists for this — if it
    never happens, that is a SpecBug, not a weaker claim)."""
    pos = rig["furnace"]
    result_expr = _item_expr("furnace_result_count", "iron-plate")

    deadline = time.time() + SMELT_WAIT_TIMEOUT_S
    pre = None
    while time.time() < deadline:
        pre = _engine_int(rcon, cell, "stone-furnace", pos, result_expr)
        if pre >= MIN_PLATES_TO_WAIT_FOR:
            break
        time.sleep(1.0)
    else:
        raise runtime.SpecBug(
            f"furnace never produced >= {MIN_PLATES_TO_WAIT_FOR} iron-plate within "
            f"{SMELT_WAIT_TIMEOUT_S:.0f}s (last furnace_result_count={pre}); "
            "smelting did not occur despite fuel+ore present")

    furnace = _typed_entity(typed, "stone-furnace")
    products = furnace.take_products()  # None -> take everything in output
    reported = sum(p.count for p in products)

    post = _engine_int(rcon, cell, "stone-furnace", pos, result_expr)
    delta = pre - post

    runtime.require_floor(reported, MIN_TRANSFER_ITEMS, "take_products reported moved iron-plate")
    assert delta == reported, (
        f"accessor reported taking {reported} iron-plate but engine "
        f"furnace_result_count dropped by {delta} ({pre} -> {post}); write-side lie")


# --- Case B: BurnerMixin.take_fuel (engine LIVE; TEST-0, zero prior coverage) ---


def test_take_fuel_mutates_engine_fuel_count(rcon, cell, typed, rig):
    pos = rig["furnace"]
    pre_engine = _engine_int(rcon, cell, "stone-furnace", pos, ENGINE_READS["fuel_count"])
    pre_agent = _agent_coal_count(rcon, cell.force_name)

    furnace = _typed_entity(typed, "stone-furnace")
    taken = furnace.take_fuel(item_name="coal", count=TAKE_FUEL_AMOUNT)
    reported = sum(t.count for t in taken)

    post_engine = _engine_int(rcon, cell, "stone-furnace", pos, ENGINE_READS["fuel_count"])
    post_agent = _agent_coal_count(rcon, cell.force_name)
    engine_delta = pre_engine - post_engine
    agent_delta = post_agent - pre_agent

    runtime.require_floor(reported, MIN_TRANSFER_ITEMS, "take_fuel reported moved coal")
    assert engine_delta == reported, (
        f"accessor reported taking {reported} coal but engine fuel_count dropped "
        f"by {engine_delta} ({pre_engine} -> {post_engine}); write-side lie")
    assert agent_delta == reported, (
        f"accessor reported taking {reported} coal but the agent character's raw "
        f"main-inventory coal count only grew by {agent_delta} "
        f"({pre_agent} -> {post_agent}); items vanished in transit")
