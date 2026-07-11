"""Family fixtures for accessor_liveness, built on the frozen runtime + spec.

Session shape: one cell allocation per pytest session (FV_CELL_INDEX), a TYPED
session (RconHandler + action classes + ReachableView) bound to that cell's
agent, rigs placed WITHIN REACH of the agent spawn (typed mutators are
reachable-gated). Engine truth comes only from raw Lua via the frozen runtime;
DB truth (spine cases) via accessor_spec.wait_ops_flushed + runtime.load_db.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_SRC = str(Path(__file__).resolve().parents[3] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from _frozen import runtime  # noqa: E402

pytestmark = pytest.mark.live

LIVE = os.environ.get("FV_LIVE_TESTS") == "1"


def pytest_collection_modifyitems(config, items):
    if not LIVE:
        skip = pytest.mark.skip(reason="live suite: set FV_LIVE_TESTS=1 with a running lab-grid instance")
        for item in items:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def instance() -> runtime.Instance:
    return runtime.instance_from_env()


@pytest.fixture(scope="session")
def rcon(instance):
    r = runtime.connect(instance)
    runtime.verify_grid_config(r)
    return r


@pytest.fixture(scope="session")
def cell(rcon):
    idx = int(os.environ.get("FV_CELL_INDEX", "16"))
    session = runtime.allocate_cell(rcon, idx)
    yield session
    runtime.release_cell(rcon, session)


@pytest.fixture(scope="session")
def frozen_spec():
    from _frozen import accessor_spec
    return accessor_spec


@pytest.fixture(scope="session")
def typed(rcon, cell):
    """The typed layer under test, bound to the cell's agent.

    Mirrors tier4_runtime._load_reachable_view wiring exactly (RconHandler +
    EntityOperationsAction + PlacementAction + MovementAction). MovementAction
    gets no async listener — this family never walks; rigs are placed within
    reach of spawn.
    """
    from FactoryVerse.game.agent.infra.rcon_handler import RconHandler
    from FactoryVerse.game.agent.embodied_actions.entity_operations import (
        EntityOperationsAction)
    from FactoryVerse.game.agent.embodied_actions.place_entity import PlacementAction
    from FactoryVerse.game.agent.embodied_actions.walking import MovementAction
    from FactoryVerse.game.agent.reachable_view import ReachableView

    handler = RconHandler(rcon, f"agent_{cell.agent_id}")  # interface name, not bare id
    entity_ops = EntityOperationsAction(handler)
    movement = MovementAction(handler, async_listener=None)
    placement = PlacementAction(handler, entity_ops, movement)
    view = ReachableView(
        rcon_handler=handler,
        entity_ops=entity_ops,
        place_ops=placement,
        walking_action=movement,
    )
    return {"view": view, "entity_ops": entity_ops, "placement": placement,
            "handler": handler}


def drain_cell_snapshots(rcon, cell, timeout_s: float = 120.0) -> None:
    """Block until the allocation/reset-triggered re-gather of this cell has
    LANDED: every cell chunk's snapshot_tick >= the allocation tick, writer
    IDLE, queue empty. wait_ops_flushed alone races the enqueue->start gap —
    a late init gather then stamps rig builds 'pre-existing' and the loader
    drops their ops as stale (PROV-1 class; flaked the recipe file 2026-07-11).
    Call this at rig start in any file whose claims are provenance-sensitive."""
    import time as _t
    from _frozen import runtime as _rt

    want = _rt.cell_chunks(cell.bounds)
    deadline = _t.time() + timeout_s
    last = {}
    while _t.time() < deadline:
        st = _rt.lua(rcon, "return remote.call('map','get_snapshot_status')")
        snapped = _rt.lookup_snapshot_ticks(rcon)
        stale = [c for c in want if snapped.get(c, -1) < cell.allocated_at_tick]
        last = {"phase": st.get("phase"), "write_queue": st.get("write_queue_size"),
                "stale_chunks": len(stale)}
        if last["phase"] == "IDLE" and last["write_queue"] == 0 and not stale:
            return
        _t.sleep(0.5)
    raise runtime.SpecBug(
        f"cell-snapshot drain timed out after {timeout_s:.0f}s (last={last}) — "
        "refusing to build a provenance-sensitive rig over an unlanded re-gather")


def give_items(rcon, agent_id: int, items: dict) -> None:
    """Add items to the agent inventory (idiom from check_L2_4.py:452)."""
    lua_items = ",".join(f"['{k}']={v}" for k, v in items.items())
    runtime.lua_strict(
        rcon, f"return remote.call('agent','add_items',{agent_id},{{{lua_items}}})")


def engine_read(rcon, cell, entity_name: str, x: float, y: float, expr: str):
    """Frozen engine truth channel: find the rig entity by name+position and
    evaluate one accessor_spec.ENGINE_READS expression against it. Raw Lua
    only — never the mod inspection path, never typed state."""
    return runtime.lua_strict(rcon, f"""
        local e = game.surfaces[1].find_entity('{entity_name}', {{x={x},y={y}}})
        if e == nil then return {{missing=true}} end
        return {{value = {expr}}}
    """)


def spawn_offset(cell, dx: float, dy: float):
    """A rig position within reach of the agent spawn."""
    return cell.spawn["x"] + dx, cell.spawn["y"] + dy
