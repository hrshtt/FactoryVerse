from __future__ import annotations

import threading

import pytest

from FactoryVerse.game.agent.embodied_actions.mining import (
    MiningAction,
    MiningReconciliationError,
)
from FactoryVerse.game.agent.remote_view import RemoteView
from FactoryVerse.game.factory.types import MapPosition
from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase


class _Rcon:
    def build_command(self, *args):
        return args

    def execute_and_parse_json(self, _command):
        return {
            "success": True,
            "queued": True,
            "action_id": "mine-1",
            "estimated_ticks": 1,
        }


class _Listener:
    async def await_action(self, _response, timeout=None):
        return {
            "success": True,
            "action_id": "mine-1",
            "tick": 42,
            "result": {
                "reason": "depleted",
                "entity_name": "tree-01",
                "position": {"x": 3.25, "y": -7.5},
                "actual_products": {},
            },
        }


class _CausalListener:
    async def await_action(self, _response, timeout=None):
        return {
            "success": True,
            "action_id": "mine-1",
            "tick": 42,
            "result": {
                "reason": "depleted",
                "entity_name": "tree-01",
                "position": {"x": 3.25, "y": -7.5},
                "actual_products": {"wood": 4},
                "causal_facts": {
                    "destroy_event_tick": 42,
                    "engine_exists": False,
                    "inventory_delta": {"wood": 4},
                },
            },
        }


class _NearestRcon(_Rcon):
    def execute_and_parse_json(self, _command):
        return {
            "success": True,
            "queued": True,
            "action_id": "mine-1",
            "estimated_ticks": 1,
            "entity_name": "tree-01",
            "entity_position": {"x": 3.25, "y": -7.5},
        }


class _CleanupRcon(_NearestRcon):
    def __init__(self, order, *, fail_stop=False):
        self.order = order
        self.fail_stop = fail_stop
        self.active = False

    def execute_and_parse_json(self, command):
        action = command[0]
        self.order.append(("rcon", action))
        if action == "mine_resource":
            self.active = True
            return super().execute_and_parse_json(command)
        assert action == "stop_mining"
        if self.fail_stop:
            raise RuntimeError("stop transport failed")
        self.active = False
        return {
            "success": False,
            "reason": "cancelled",
            "action_id": "mine-1",
        }


class _NeverAwaitListener:
    def __init__(self):
        self.awaited = False

    async def await_action(self, _response, timeout=None):
        self.awaited = True
        raise AssertionError("baseline failure must not await completion")


@pytest.mark.asyncio
async def test_mine_waits_for_resource_depletion_barrier():
    mining = MiningAction(_Rcon(), _Listener())
    observed = []

    async def barrier(name, x, y):
        observed.append((name, x, y))

    mining.set_resource_depletion_barrier(barrier)

    await mining.mine("tree-01", position=MapPosition(x=3.25, y=-7.5))

    assert observed == [("tree-01", 3.25, -7.5)]


class _ReconciliationFailureListener:
    async def await_action(self, _response, timeout=None):
        return {
            "success": False,
            "status": "failed",
            "action_id": "mine-1",
            "tick": 43,
            "result": {
                "reason": "reconciliation_failed",
                "entity_name": "tree-01",
                "position": {"x": 3.25, "y": -7.5},
                "actual_products": {},
                "causal_facts": {
                    "engine_exists": True,
                    "inventory_delta": {},
                    "expected_products": {"wood": 4},
                    "depletion_restarts": 4,
                    "trace": [
                        {
                            "tick": 43,
                            "phase": "stopped_while_entity_exists",
                        }
                    ],
                },
            },
        }


@pytest.mark.asyncio
async def test_mine_returns_structured_failure_instead_of_false_products():
    mining = MiningAction(_Rcon(), _ReconciliationFailureListener())
    barrier_called = False

    async def barrier(_name, _x, _y):
        nonlocal barrier_called
        barrier_called = True

    mining.set_resource_depletion_barrier(barrier)

    with pytest.raises(MiningReconciliationError) as raised:
        await mining.mine("tree-01", position=MapPosition(x=3.25, y=-7.5))

    error = raised.value
    assert error.action_id == "mine-1"
    assert error.resource_name == "tree-01"
    assert error.position == {"x": 3.25, "y": -7.5}
    assert error.facts["engine_exists"] is True
    assert error.facts["inventory_delta"] == {}
    assert error.facts["expected_products"] == {"wood": 4}
    assert error.facts["trace"][0]["tick"] == 43
    assert barrier_called is False


@pytest.mark.asyncio
async def test_mine_wraps_duckdb_depletion_timeout_as_reconciliation_failure():
    mining = MiningAction(_Rcon(), _Listener())

    async def barrier(_name, _x, _y):
        raise TimeoutError("row remained")

    mining.set_resource_depletion_barrier(barrier)

    with pytest.raises(MiningReconciliationError) as raised:
        await mining.mine("tree-01", position=MapPosition(x=3.25, y=-7.5))

    assert raised.value.facts["duckdb_depleted"] is False


@pytest.mark.asyncio
async def test_mine_rejects_mismatched_barrier_without_overwriting_engine_tick():
    mining = MiningAction(_Rcon(), _CausalListener())

    def prepare(_name, _x, _y):
        return {"resource_rows_at_start": 1, "entity_sequence_floor": 7}

    async def barrier(_name, _x, _y, **_kwargs):
        return {
            "snapshot_destroy_event_tick": 41,
            "duckdb_delete_tick": 41,
            "destroy_event_sequence": 8,
            "destroy_action_id": "mine-1",
            "resource_present_at_action_start": True,
            "duckdb_rows_removed": 1,
        }

    mining.set_resource_depletion_barrier(barrier, prepare)

    with pytest.raises(MiningReconciliationError) as raised:
        await mining.mine("tree-01", position=MapPosition(x=3.25, y=-7.5))

    assert raised.value.facts["destroy_event_tick"] == 42
    assert raised.value.facts["engine_destroy_event_tick"] == 42
    assert raised.value.facts["barrier_facts"]["snapshot_destroy_event_tick"] == 41
    assert mining.last_causal_facts["destroy_event_tick"] == 42


@pytest.mark.asyncio
async def test_positionless_mine_captures_exact_baseline_before_awaiting_completion():
    order = []

    class OrderedListener(_CausalListener):
        async def await_action(self, response, timeout=None):
            assert order == [
                ("prepare", "tree-01", 3.25, -7.5),
            ]
            order.append(("await", response.action_id))
            return await super().await_action(response, timeout=timeout)

    mining = MiningAction(_NearestRcon(), OrderedListener())

    def prepare(name, x, y):
        order.append(("prepare", name, x, y))
        return {"resource_rows_at_start": 1, "entity_sequence_floor": 7}

    async def barrier(name, x, y, **kwargs):
        order.append(("barrier", name, x, y))
        assert kwargs == {
            "expected_destroy_tick": 42,
            "expected_action_id": "mine-1",
            "baseline": {
                "resource_rows_at_start": 1,
                "entity_sequence_floor": 7,
            },
        }
        return {
            "snapshot_destroy_event_tick": 42,
            "duckdb_delete_tick": 42,
            "destroy_event_sequence": 8,
            "destroy_action_id": "mine-1",
            "resource_present_at_action_start": True,
            "duckdb_rows_removed": 1,
        }

    mining.set_resource_depletion_barrier(barrier, prepare)
    stacks = await mining.mine("tree", position=None)

    assert [(stack.name, stack.count) for stack in stacks] == [("wood", 4)]
    assert order == [
        ("prepare", "tree-01", 3.25, -7.5),
        ("await", "mine-1"),
        ("barrier", "tree-01", 3.25, -7.5),
    ]
    assert mining.last_causal_facts["destroy_event_tick"] == 42
    assert mining.last_causal_facts["snapshot_destroy_event_tick"] == 42


@pytest.mark.asyncio
async def test_unproven_positionless_mine_cancels_queue_before_raising():
    order = []
    rcon = _CleanupRcon(order)
    listener = _NeverAwaitListener()
    mining = MiningAction(rcon, listener)

    def prepare(name, x, y):
        order.append(("prepare", name, x, y))
        return {"resource_rows_at_start": 0, "entity_sequence_floor": 7}

    async def barrier(*_args, **_kwargs):
        raise AssertionError("unproven action must not enter the barrier")

    mining.set_resource_depletion_barrier(barrier, prepare)
    with pytest.raises(MiningReconciliationError) as raised:
        await mining.mine("tree", position=None)

    assert order == [
        ("rcon", "mine_resource"),
        ("prepare", "tree-01", 3.25, -7.5),
        ("rcon", "stop_mining"),
    ]
    assert listener.awaited is False
    assert rcon.active is False
    assert raised.value.facts["queued_action_cleanup"] == {
        "attempted": True,
        "succeeded": True,
        "reported_success": False,
        "reason": "cancelled",
        "action_id": "mine-1",
    }


@pytest.mark.asyncio
async def test_cleanup_error_never_masks_baseline_reconciliation_error():
    order = []
    rcon = _CleanupRcon(order, fail_stop=True)
    listener = _NeverAwaitListener()
    mining = MiningAction(rcon, listener)

    def prepare(_name, _x, _y):
        return {"resource_rows_at_start": 0, "entity_sequence_floor": 7}

    async def barrier(*_args, **_kwargs):
        raise AssertionError("unproven action must not enter the barrier")

    mining.set_resource_depletion_barrier(barrier, prepare)
    with pytest.raises(MiningReconciliationError) as raised:
        await mining.mine("tree", position=None)

    assert listener.awaited is False
    assert raised.value.facts["queued_action_cleanup"]["succeeded"] is False
    assert raised.value.facts["queued_action_cleanup"]["error"] == (
        "stop transport failed"
    )


class _DelayedRemovalSync:
    def __init__(self, connection):
        self.connection = connection
        self.flushes = 0

    def flush_pending(self):
        self.flushes += 1
        if self.flushes == 2:
            self.connection.execute(
                """
                DELETE FROM resource_entity
                WHERE name = ? AND position_x = ? AND position_y = ?
                """,
                ["tree-01", 3.25, -7.5],
            )
        return int(self.flushes == 2)

    def get_applied_resource_removal(self, name, x, y):
        assert (name, x, y) == ("tree-01", 3.25, -7.5)
        return {
            "destroy_event_tick": 42,
            "duckdb_delete_tick": 42,
            "duckdb_rows_removed": 1,
        }


class _StaleRemovalSync:
    def flush_pending(self):
        return 0

    def get_applied_resource_removal(self, _name, _x, _y):
        return {
            "snapshot_destroy_event_tick": 42,
            "destroy_event_sequence": 7,
            "destroy_action_id": "mine-1",
            "remove_payload_rows_removed": 1,
        }


@pytest.mark.asyncio
async def test_remote_view_depletion_barrier_waits_for_late_snapshot_mutation():
    database = SnapshotDatabase()
    database.ensure_schema()
    database.connection.execute(
        """
        INSERT INTO resource_entity
        (name, entity_type, position_x, position_y, chunk_x, chunk_y, raw_data)
        VALUES ('tree-01', 'tree', 3.25, -7.5, 0, -1, '{}')
        """
    )

    view = object.__new__(RemoteView)
    view._loaded = True
    view._database = database
    view._db_lock = threading.Lock()
    view._sync = _DelayedRemovalSync(database.connection)

    facts = await view.wait_for_resource_depletion(
        "tree-01", 3.25, -7.5, timeout=2.0
    )

    assert view._sync.flushes == 2
    assert facts == {
        "destroy_event_tick": 42,
        "duckdb_delete_tick": 42,
        "duckdb_rows_removed": 1,
    }
    database.close()


@pytest.mark.asyncio
async def test_remote_view_rejects_stale_same_position_removal_fact():
    database = SnapshotDatabase()
    database.ensure_schema()
    view = object.__new__(RemoteView)
    view._loaded = True
    view._database = database
    view._db_lock = threading.Lock()
    view._sync = _StaleRemovalSync()

    with pytest.raises(TimeoutError):
        await view.wait_for_resource_depletion(
            "tree-01",
            3.25,
            -7.5,
            timeout=0.0,
            expected_destroy_tick=42,
            expected_action_id="mine-1",
            baseline={"resource_rows_at_start": 1, "entity_sequence_floor": 7},
        )
    database.close()


@pytest.mark.asyncio
async def test_rewrite_before_exact_remove_still_proves_action_depletion(tmp_path):
    from FactoryVerse.game.infra.duckdb import apply_ops
    from FactoryVerse.game.infra.duckdb.sync import SyncService

    database = SnapshotDatabase()
    database.ensure_schema()
    apply_ops.upsert_resource_entity(
        database.connection,
        {
            "name": "tree-01",
            "type": "tree",
            "position": {"x": 3.25, "y": -7.5},
        },
        0,
        -1,
    )
    apply_ops.upsert_resource_entity(
        database.connection,
        {
            "name": "tree-02",
            "type": "tree",
            "position": {"x": 4.25, "y": -7.5},
        },
        0,
        -1,
    )
    sync = SyncService(
        database.connection,
        udp_dispatcher=object(),
        on_rebuild=lambda: None,
        initial_sequence=7,
        snapshot_dir=tmp_path,
    )
    view = object.__new__(RemoteView)
    view._loaded = True
    view._database = database
    view._db_lock = sync._db_lock
    view._sync = sync
    baseline = view.capture_resource_depletion_baseline("tree-01", 3.25, -7.5)

    path = tmp_path / "trees.jsonl"
    path.write_text(
        '{"name":"tree-02","type":"tree","position":{"x":4.25,"y":-7.5}}\n',
        encoding="utf-8",
    )
    sync._apply_trees_rocks_file(path, {"x": 0, "y": -1})
    sync._apply_entity_remove(
        {
            "name": "tree-01",
            "position": {"x": 3.25, "y": -7.5},
            "tick": 42,
            "sequence": 8,
            "action_id": "mine-1",
        }
    )

    facts = await view.wait_for_resource_depletion(
        "tree-01",
        3.25,
        -7.5,
        timeout=0.0,
        expected_destroy_tick=42,
        expected_action_id="mine-1",
        baseline=baseline,
    )
    assert facts["resource_present_at_action_start"] is True
    assert facts["remove_payload_rows_removed"] == 0
    assert facts["duckdb_rows_removed"] == 1
    assert facts["destroy_event_sequence"] == 8
    database.close()
