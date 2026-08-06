"""Offline test: SnapshotLoader.load_all() boot-loads the power_networks.jsonl
and latest status-<tick>.jsonl "state" feeds (power-impl-contracts.md Task 3,
Task 7c), on a synthetic tmp-dir tree shaped like the real script-output
layout (root/factoryverse/snapshots/power_networks.jsonl,
root/factoryverse/status/status-<tick>.jsonl) — the same layout RemoteView
hands SnapshotLoader (a script-output ROOT, not the pre-normalized
.../factoryverse/snapshots dir).
"""

from __future__ import annotations

import json

import pytest

from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader


POWER_LINE = {
    "tick": 12345,
    "networks": [
        {
            "network_id": 4,
            "anchor_pole": {
                "name": "small-electric-pole",
                "position": {"x": 971.5, "y": 971.5},
            },
            "pole_count": 3,
            "member_count": 7,
            "production_w": 77500.0,
            "consumption_w": 77500.0,
            "storage_j": 0.0,
            "production_w_by_prototype": {"electric-energy-interface": 77500.0},
            "consumption_w_by_prototype": {"assembling-machine-1": 77500.0},
        }
    ],
}

STATUS_DUMP_OLD = [
    {"meta": True, "tick": 4000, "count": 1},
    {"name": "boiler", "status": "no_power", "x": 1.0, "y": 2.0},
]

STATUS_DUMP_NEW = [
    {"meta": True, "tick": 5000, "count": 2},
    {"name": "assembling-machine-1", "status": "no_power", "x": 986.5, "y": 1140.5},
    {"name": "boiler", "status": "working", "x": 10.0, "y": 20.0},
]


@pytest.fixture
def state_feed_root(tmp_path):
    """Real production layout: root/factoryverse/{snapshots,status}/..."""
    snapshots_dir = tmp_path / "factoryverse" / "snapshots"
    snapshots_dir.mkdir(parents=True)
    status_dir = tmp_path / "factoryverse" / "status"
    status_dir.mkdir(parents=True)

    (snapshots_dir / "power_networks.jsonl").write_text(
        json.dumps(POWER_LINE) + "\n"
    )

    # Two dump files: the loader must pick the NEWEST by tick-in-filename,
    # not by directory iteration order or mtime.
    with open(status_dir / "status-4000.jsonl", "w") as f:
        for rec in STATUS_DUMP_OLD:
            f.write(json.dumps(rec) + "\n")
    with open(status_dir / "status-5000.jsonl", "w") as f:
        for rec in STATUS_DUMP_NEW:
            f.write(json.dumps(rec) + "\n")

    return tmp_path


@pytest.fixture
def loaded(state_feed_root):
    db = SnapshotDatabase()  # in-memory
    db.ensure_schema()
    loader = SnapshotLoader(db.connection, state_feed_root)
    result = loader.load_all()
    yield db.connection, result
    db.close()


class TestBootLoadPowerNetworks:
    def test_power_samples_populated(self, loaded):
        con, _ = loaded
        row = con.execute(
            "SELECT tick, network_count FROM power_samples"
        ).fetchone()
        assert row == (12345, 1)

    def test_power_networks_populated(self, loaded):
        con, _ = loaded
        row = con.execute(
            "SELECT network_id, anchor_pole_name FROM power_networks"
        ).fetchone()
        assert row == (4, "small-electric-pole")


class TestBootLoadEntityStatus:
    def test_newest_dump_wins_by_tick_in_filename(self, loaded):
        """status-5000.jsonl must be applied, not status-4000.jsonl, even
        though 4000 sorts/iterates first."""
        con, _ = loaded
        n = con.execute("SELECT COUNT(*) FROM entity_status").fetchone()[0]
        assert n == 2

        names = {
            r[0]
            for r in con.execute("SELECT entity_name FROM entity_status").fetchall()
        }
        assert names == {"assembling-machine-1", "boiler"}

    def test_freshness_marker_reflects_newest_dump(self, loaded):
        con, _ = loaded
        row = con.execute(
            "SELECT value FROM sync_state WHERE key = 'entity_status_last_tick'"
        ).fetchone()
        assert row == (5000,)


class TestBootLoadMissingFilesAreNoOps:
    def test_missing_power_and_status_files_do_not_error(self, tmp_path):
        """A snapshot tree with no power_networks.jsonl / status dumps at
        all (e.g. a brand-new save) must load without error and simply
        leave the state tables empty."""
        snapshots_dir = tmp_path / "factoryverse" / "snapshots"
        snapshots_dir.mkdir(parents=True)

        db = SnapshotDatabase()
        db.ensure_schema()
        try:
            loader = SnapshotLoader(db.connection, tmp_path)
            loader.load_all()  # must not raise
            assert db.connection.execute(
                "SELECT COUNT(*) FROM power_samples"
            ).fetchone()[0] == 0
            assert db.connection.execute(
                "SELECT COUNT(*) FROM entity_status"
            ).fetchone()[0] == 0
        finally:
            db.close()
