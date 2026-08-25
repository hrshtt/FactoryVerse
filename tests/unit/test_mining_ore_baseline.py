"""MINE-BLOCK-1 — the depletion baseline must follow the resource to its table.

Natural resources are split across two tables: trees and rocks are rows in
``resource_entity``, ore deposits are rows in ``resource_tile``. The pre-flight
baseline used to query ``resource_entity`` unconditionally, so an ore target
could never be proven to exist and every attempt to hand-mine ore was rejected
before it began, while trees mined normally.

Observed live on a freeplay run: five consecutive rejections across
``patch.mine()``, ``mining.mine(name)`` and ``mining.mine(name, position=...)``,
each raising ``MiningReconciliationError: Cannot prove the selected resource
existed in DuckDB before queued mining completion``.
"""

from __future__ import annotations

import threading

import pytest

from FactoryVerse.game.agent.remote_view import (
    RESOURCE_ENTITY_TABLE,
    RESOURCE_TILE_TABLE,
    RemoteView,
)
from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase


def _view(database: SnapshotDatabase) -> RemoteView:
    view = object.__new__(RemoteView)
    view._loaded = True
    view._database = database
    view._db_lock = threading.Lock()
    view._sync = None
    return view


@pytest.fixture
def database():
    db = SnapshotDatabase()
    db.ensure_schema()
    db.connection.execute(
        """
        INSERT INTO resource_entity
        (name, entity_type, position_x, position_y, chunk_x, chunk_y, raw_data)
        VALUES ('tree-07', 'tree', -9.25, 47.0, -1, 1, '{}')
        """
    )
    db.connection.execute(
        """
        INSERT INTO resource_tile
        (name, position_x, position_y, amount, chunk_x, chunk_y)
        VALUES ('copper-ore', -31.0, -71.0, 2120, -1, -3)
        """
    )
    yield db
    db.close()


def test_ore_baseline_proves_existence_from_the_tile_table(database):
    """The regression: ore must be provable, or hand-mining ore is impossible."""
    baseline = _view(database).capture_resource_depletion_baseline(
        "copper-ore", -31.0, -71.0
    )

    # rows_at_start == 1 is exactly what MiningAction requires before it will
    # await a queued mine; 0 is what produced the live rejections.
    assert baseline["resource_rows_at_start"] == 1
    assert baseline["resource_table"] == RESOURCE_TILE_TABLE
    assert baseline["resource_amount_at_start"] == 2120


def test_the_old_entity_only_lookup_could_never_prove_ore(database):
    """Pin the defect itself, so the fix cannot be quietly undone.

    This is the exact query the baseline used to run. Against a database that
    genuinely holds the ore, it returns 0 — which is what MiningAction read as
    "cannot prove this resource exists" before rejecting the mine.
    """
    entity_rows = database.connection.execute(
        "SELECT count(*) FROM resource_entity "
        "WHERE name = ? AND position_x = ? AND position_y = ?",
        ["copper-ore", -31.0, -71.0],
    ).fetchone()[0]
    tile_rows = database.connection.execute(
        "SELECT count(*) FROM resource_tile "
        "WHERE name = ? AND position_x = ? AND position_y = ?",
        ["copper-ore", -31.0, -71.0],
    ).fetchone()[0]

    assert entity_rows == 0, "the old lookup found ore it should not have"
    assert tile_rows == 1, "the ore is really there, in the other table"


def test_entity_baseline_still_reads_the_entity_table(database):
    """Trees kept working throughout; the fix must not move them."""
    baseline = _view(database).capture_resource_depletion_baseline(
        "tree-07", -9.25, 47.0
    )

    assert baseline["resource_rows_at_start"] == 1
    assert baseline["resource_table"] == RESOURCE_ENTITY_TABLE
    # An entity is consumed whole; there is no partial amount to reconcile.
    assert "resource_amount_at_start" not in baseline


def test_absent_resource_is_still_unprovable(database):
    """The barrier must keep rejecting what genuinely is not there."""
    baseline = _view(database).capture_resource_depletion_baseline(
        "copper-ore", 999.0, 999.0
    )

    assert baseline["resource_rows_at_start"] == 0


class _OreRemovalSync:
    """Reports the tile removal the way the live sync service would."""

    def __init__(self, connection):
        self.connection = connection

    def flush_pending(self):
        return 0

    def get_entity_sequence(self):
        return 1

    def get_applied_resource_removal(self, name, x, y):
        assert (name, x, y) == ("copper-ore", -31.0, -71.0)
        return {
            "destroy_event_tick": 99,
            "duckdb_delete_tick": 99,
            "duckdb_rows_removed": 1,
        }


@pytest.mark.asyncio
async def test_depletion_wait_watches_the_table_the_baseline_measured(database):
    """A depleted ore tile is removed from resource_tile, not resource_entity.

    The decoy row below is the discriminator: a same-named row survives in
    ``resource_entity`` while the tile row is gone. Watching the entity table
    would never see the count reach zero and the wait would burn its timeout on
    a resource that genuinely did deplete.
    """
    database.connection.execute(
        """
        INSERT INTO resource_entity
        (name, entity_type, position_x, position_y, chunk_x, chunk_y, raw_data)
        VALUES ('copper-ore', 'resource', -31.0, -71.0, -1, -3, '{}')
        """
    )
    view = _view(database)
    view._sync = _OreRemovalSync(database.connection)
    database.connection.execute(
        "DELETE FROM resource_tile WHERE name = 'copper-ore' "
        "AND position_x = -31.0 AND position_y = -71.0"
    )

    facts = await view.wait_for_resource_depletion(
        "copper-ore",
        -31.0,
        -71.0,
        timeout=1.0,
        baseline={"resource_table": RESOURCE_TILE_TABLE},
    )

    assert facts["duckdb_rows_removed"] == 1

    # And the discriminator, stated as an assertion rather than a comment:
    # pointed at the entity table, the same call cannot see the depletion.
    with pytest.raises(TimeoutError):
        await view.wait_for_resource_depletion(
            "copper-ore",
            -31.0,
            -71.0,
            timeout=0.2,
            baseline={"resource_table": RESOURCE_ENTITY_TABLE},
        )


@pytest.mark.asyncio
async def test_unknown_resource_table_is_rejected_loudly(database):
    view = _view(database)

    with pytest.raises(ValueError, match="Unknown resource table"):
        await view.wait_for_resource_depletion(
            "copper-ore",
            -31.0,
            -71.0,
            timeout=0.1,
            baseline={"resource_table": "map_entity"},
        )
