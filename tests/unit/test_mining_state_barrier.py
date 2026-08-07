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
        "tree-01", 3.25, -7.5, timeout=0.2
    )

    assert view._sync.flushes == 2
    assert facts == {
        "destroy_event_tick": 42,
        "duckdb_delete_tick": 42,
        "duckdb_rows_removed": 1,
    }
    database.close()
