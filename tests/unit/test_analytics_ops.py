"""Unit tests for the one analytics reducer that lawfully exists:
``agent_manual_production_statistics``, aggregated from the agent's
crafting/mining EVENT files (analytics_ops.py). Real in-memory
SnapshotDatabase, no Factorio needed.

The power and status reducers that used to live beside it are gone on
purpose (Constitution §10, API plan §4.6); their readers are tested in
tests/unit/test_dump_readers.py.
"""

from __future__ import annotations

import json

import pytest

from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
from FactoryVerse.game.infra.duckdb import analytics_ops


@pytest.fixture()
def db():
    d = SnapshotDatabase(db_path=None)
    d.ensure_schema()
    yield d.connection
    d.close()


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


class TestAggregateProductEvents:
    def test_sums_products_and_tracks_latest_tick(self, tmp_path):
        path = tmp_path / "crafting-statistics.jsonl"
        _write(path, [
            {"agent_id": 1, "tick": 100, "recipe": "iron-gear-wheel", "products": {"iron-gear-wheel": 1}},
            {"agent_id": 1, "tick": 160, "recipe": "iron-gear-wheel", "products": {"iron-gear-wheel": 2}},
        ])
        totals, tick, agent = analytics_ops.aggregate_product_events(path)
        assert totals == {"iron-gear-wheel": 3}
        assert (tick, agent) == (160, 1)

    def test_missing_file_is_empty(self, tmp_path):
        totals, tick, agent = analytics_ops.aggregate_product_events(tmp_path / "nope.jsonl")
        assert (totals, tick, agent) == ({}, 0, None)

    def test_torn_last_line_is_skipped(self, tmp_path):
        path = tmp_path / "mining-statistics.jsonl"
        path.write_text(json.dumps({"agent_id": 2, "tick": 5, "products": {"wood": 4}}) + "\n{\"agent_id\": 2, \"ti", encoding="utf-8")
        totals, tick, agent = analytics_ops.aggregate_product_events(path)
        assert totals == {"wood": 4} and tick == 5 and agent == 2


class TestApplyAgentManualFiles:
    def test_writes_one_cumulative_row(self, db, tmp_path):
        agent_dir = tmp_path / "1"
        _write(agent_dir / "crafting-statistics.jsonl", [
            {"agent_id": 1, "tick": 100, "products": {"iron-gear-wheel": 1}},
        ])
        _write(agent_dir / "mining-statistics.jsonl", [
            {"agent_id": 1, "tick": 90, "products": {"wood": 4}},
        ])
        assert analytics_ops.apply_agent_manual_files(db, agent_dir) == 100
        row = db.execute(
            "SELECT agent_id, tick, crafted, mined FROM agent_manual_production_statistics"
        ).fetchone()
        assert row[0] == 1 and row[1] == 100
        assert json.loads(row[2]) == {"iron-gear-wheel": 1}
        assert json.loads(row[3]) == {"wood": 4}

    def test_reapply_is_idempotent(self, db, tmp_path):
        agent_dir = tmp_path / "1"
        _write(agent_dir / "crafting-statistics.jsonl", [
            {"agent_id": 1, "tick": 100, "products": {"iron-gear-wheel": 1}},
        ])
        analytics_ops.apply_agent_manual_files(db, agent_dir)
        analytics_ops.apply_agent_manual_files(db, agent_dir)
        assert db.execute("SELECT count(*) FROM agent_manual_production_statistics").fetchone()[0] == 1

    def test_empty_dir_writes_nothing(self, db, tmp_path):
        agent_dir = tmp_path / "3"
        agent_dir.mkdir()
        assert analytics_ops.apply_agent_manual_files(db, agent_dir) == 0
        assert db.execute("SELECT count(*) FROM agent_manual_production_statistics").fetchone()[0] == 0

    def test_agent_id_inferred_from_directory_name(self, db, tmp_path):
        agent_dir = tmp_path / "7"
        _write(agent_dir / "mining-statistics.jsonl", [{"tick": 10, "products": {"stone": 2}}])
        analytics_ops.apply_agent_manual_files(db, agent_dir)
        assert db.execute("SELECT agent_id FROM agent_manual_production_statistics").fetchone()[0] == 7
