"""Offline contracts for file and DuckDB production-statistics routes."""

from __future__ import annotations

import json

import pytest

from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader
from FactoryVerse.game.infra.duckdb.sync import SyncService
from FactoryVerse.game.tasks.sources import AgentSnapshotSource, DuckDBSource


def _write_jsonl(path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _make_feed(root) -> None:
    (root / "factoryverse" / "snapshots").mkdir(parents=True)
    agent_dir = root / "factoryverse" / "agent-snapshots" / "1"
    _write_jsonl(
        agent_dir / "production-statistics.jsonl",
        [
            {"agent_id": 1, "tick": 60, "input": {}, "output": {}},
            {
                "agent_id": 1,
                "tick": 120,
                "input": {"iron-gear-wheel": 2},
                "output": {"iron-plate": 4},
            },
        ],
    )
    _write_jsonl(
        agent_dir / "crafting-statistics.jsonl",
        [
            {
                "agent_id": 1,
                "tick": 100,
                "recipe": "iron-gear-wheel",
                "products": {"iron-gear-wheel": 1},
            },
            {
                "agent_id": 1,
                "tick": 110,
                "recipe": "iron-gear-wheel",
                "products": {"iron-gear-wheel": 1},
            },
        ],
    )
    _write_jsonl(
        agent_dir / "mining-statistics.jsonl",
        [
            {
                "agent_id": 1,
                "tick": 90,
                "entity_name": "tree-01",
                "products": {"wood": 4},
            }
        ],
    )


@pytest.mark.asyncio
async def test_boot_replay_matches_file_and_database_routes(tmp_path):
    _make_feed(tmp_path)
    database = SnapshotDatabase()
    database.ensure_schema()
    SnapshotLoader(database.connection, tmp_path).load_all()

    file_source = AgentSnapshotSource(tmp_path)
    db_source = DuckDBSource(database.connection)

    assert await db_source.get_force_production(1) == await file_source.get_force_production(1)
    assert await db_source.get_manual_production(1) == await file_source.get_manual_production(1)


@pytest.mark.asyncio
async def test_live_file_notifications_refresh_database_route(tmp_path):
    _make_feed(tmp_path)
    database = SnapshotDatabase()
    database.ensure_schema()
    SnapshotLoader(database.connection, tmp_path).load_all()
    sync = SyncService(
        database.connection,
        udp_dispatcher=object(),
        on_rebuild=lambda: None,
        snapshot_dir=tmp_path,
    )

    agent_dir = tmp_path / "factoryverse" / "agent-snapshots" / "1"
    with open(agent_dir / "production-statistics.jsonl", "a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "agent_id": 1,
                    "tick": 180,
                    "input": {"iron-gear-wheel": 3},
                    "output": {"iron-plate": 6},
                }
            )
            + "\n"
        )
    with open(agent_dir / "crafting-statistics.jsonl", "a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "agent_id": 1,
                    "tick": 170,
                    "recipe": "iron-gear-wheel",
                    "products": {"iron-gear-wheel": 1},
                }
            )
            + "\n"
        )

    sync._handle_file_io(
        {
            "event_type": "file_io",
            "file_type": "agent_production_statistics",
            "file_path": "factoryverse/agent-snapshots/1/production-statistics.jsonl",
            "agent_id": 1,
        }
    )
    sync._handle_file_io(
        {
            "event_type": "file_io",
            "file_type": "agent_crafting_statistics",
            "file_path": "factoryverse/agent-snapshots/1/crafting-statistics.jsonl",
            "agent_id": 1,
        }
    )
    assert sync.flush_pending() == 2

    file_source = AgentSnapshotSource(tmp_path)
    db_source = DuckDBSource(database.connection)
    assert await db_source.get_force_production(1) == await file_source.get_force_production(1)
    assert await db_source.get_manual_production(1) == await file_source.get_manual_production(1)


def test_agent_statistics_tables_are_real_and_resettable():
    database = SnapshotDatabase()
    database.ensure_schema()
    names = {
        row[0]
        for row in database.connection.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }
    assert "agent_production_statistics" in names
    assert "agent_manual_production_statistics" in names

    database.connection.execute(
        "INSERT INTO agent_production_statistics VALUES (1, 1, '{}')"
    )
    database.reset()
    assert database.connection.execute(
        "SELECT count(*) FROM agent_production_statistics"
    ).fetchone()[0] == 0

