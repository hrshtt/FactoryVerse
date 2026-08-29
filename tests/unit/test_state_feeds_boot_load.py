"""Boot load and the polled feeds (Constitution §10, API plan §4.6).

On a synthetic tree shaped like the real script-output layout, the loader
must (a) not error when the polled files exist or are absent, (b) create no
table for them, and (c) leave them on disk for the on-demand readers.
"""

from __future__ import annotations

import json

import pytest

from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader
from FactoryVerse.game.agent.remote_view import RemoteView

POWER_LINE = {"tick": 12345, "networks": [{"network_id": 4, "anchor_pole": {"name": "small-electric-pole", "position": {"x": 971.5, "y": 971.5}}, "pole_count": 3, "member_count": 7, "production_w": 77500.0, "consumption_w": 77500.0, "storage_j": 0.0, "production_w_by_prototype": {}, "consumption_w_by_prototype": {}}]}
STATUS_DUMP = [
    {"meta": True, "tick": 5000, "count": 1},
    {"name": "assembling-machine-1", "status": "no_power", "x": 986.5, "y": 1140.5},
]


@pytest.fixture
def state_feed_root(tmp_path):
    snapshots_dir = tmp_path / "factoryverse" / "snapshots"
    snapshots_dir.mkdir(parents=True)
    status_dir = tmp_path / "factoryverse" / "status"
    status_dir.mkdir(parents=True)
    (snapshots_dir / "power_networks.jsonl").write_text(json.dumps(POWER_LINE) + "\n")
    with open(status_dir / "status-5000.jsonl", "w") as f:
        for rec in STATUS_DUMP:
            f.write(json.dumps(rec) + "\n")
    return tmp_path


def _tables(con):
    return {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}


def test_loader_ignores_polled_files_and_creates_no_table_for_them(state_feed_root):
    db = SnapshotDatabase()
    db.ensure_schema()
    try:
        SnapshotLoader(db.connection, state_feed_root).load_all()  # must not raise
        names = _tables(db.connection)
        for gone in ("entity_status", "power_samples", "power_networks", "agent_production_statistics"):
            assert gone not in names
    finally:
        db.close()


def test_the_same_tree_is_readable_on_demand_with_a_declared_source(state_feed_root):
    rv = RemoteView(snapshot_dir=state_feed_root, entity_ops=None, place_ops=None,
                    walking_action=None, mining_action=None, udp_dispatcher=None, rcon_client=None)
    assert rv._status_dump().current().source == "status_dump:5000"
    assert rv._power_dump().newest().source == "power_dump:12345"
    # Both snapshot_dir conventions resolve to the same files.
    rv2 = RemoteView(snapshot_dir=state_feed_root / "factoryverse" / "snapshots", entity_ops=None, place_ops=None,
                     walking_action=None, mining_action=None, udp_dispatcher=None, rcon_client=None)
    assert rv2._status_dump().directory == rv._status_dump().directory
    assert rv2._power_dump().path == rv._power_dump().path


def test_missing_polled_files_do_not_error(tmp_path):
    (tmp_path / "factoryverse" / "snapshots").mkdir(parents=True)
    db = SnapshotDatabase()
    db.ensure_schema()
    try:
        SnapshotLoader(db.connection, tmp_path).load_all()
    finally:
        db.close()
    rv = RemoteView(snapshot_dir=tmp_path, entity_ops=None, place_ops=None,
                    walking_action=None, mining_action=None, udp_dispatcher=None, rcon_client=None)
    assert rv._status_dump().current() is None
    assert rv._power_dump().newest() is None
