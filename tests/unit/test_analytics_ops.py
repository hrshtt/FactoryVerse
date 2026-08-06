"""Unit tests for the power/status "state" feed reducer (analytics_ops.py —
power-impl-contracts.md C4, Task 7a/7b).

Mirrors test_apply_ops.py's style: real in-memory SnapshotDatabase, no
Factorio needed. The power_networks.jsonl line below is copied verbatim from
contract C1 so these tests pin the reducer against the frozen shape, not a
strawman.
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
    return d.connection


# Exact example line from contract C1 (power-impl-contracts.md).
C1_LINE = {
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

HEARTBEAT_LINE = {"tick": 12645, "networks": []}


# =============================================================================
# 7a. power_samples / power_networks reducer round-trips
# =============================================================================


class TestApplyPowerSampleC1Line:
    def test_power_samples_row_written(self, db):
        analytics_ops.apply_power_sample(db, C1_LINE)
        row = db.execute(
            "SELECT tick, network_count FROM power_samples WHERE tick = 12345"
        ).fetchone()
        assert row == (12345, 1)

    def test_power_networks_row_written_with_correct_columns(self, db):
        analytics_ops.apply_power_sample(db, C1_LINE)
        row = db.execute(
            """
            SELECT tick, network_id, anchor_pole_name, anchor_pole_x, anchor_pole_y,
                   pole_count, member_count, production_w, consumption_w, storage_j,
                   production_by_prototype, consumption_by_prototype
            FROM power_networks WHERE tick = 12345
            """
        ).fetchone()
        assert row is not None
        (
            tick, network_id, anchor_name, anchor_x, anchor_y,
            pole_count, member_count, production_w, consumption_w, storage_j,
            production_json, consumption_json,
        ) = row
        assert (tick, network_id) == (12345, 4)
        assert anchor_name == "small-electric-pole"
        assert (anchor_x, anchor_y) == (971.5, 971.5)
        assert (pole_count, member_count) == (3, 7)
        assert (production_w, consumption_w, storage_j) == (77500.0, 77500.0, 0.0)
        # JSON blobs must round-trip to the exact by-prototype breakdown
        assert json.loads(production_json) == {"electric-energy-interface": 77500.0}
        assert json.loads(consumption_json) == {"assembling-machine-1": 77500.0}

    def test_returns_network_count(self, db):
        assert analytics_ops.apply_power_sample(db, C1_LINE) == 1


class TestApplyPowerSampleHeartbeat:
    def test_heartbeat_writes_power_samples_row(self, db):
        analytics_ops.apply_power_sample(db, HEARTBEAT_LINE)
        row = db.execute(
            "SELECT tick, network_count FROM power_samples WHERE tick = 12645"
        ).fetchone()
        assert row == (12645, 0)

    def test_heartbeat_writes_zero_network_rows(self, db):
        analytics_ops.apply_power_sample(db, HEARTBEAT_LINE)
        n = db.execute(
            "SELECT COUNT(*) FROM power_networks WHERE tick = 12645"
        ).fetchone()[0]
        assert n == 0

    def test_heartbeat_returns_zero(self, db):
        assert analytics_ops.apply_power_sample(db, HEARTBEAT_LINE) == 0


class TestApplyPowerSampleIdempotent:
    def test_same_tick_reapply_does_not_duplicate(self, db):
        """power_networks has no primary key (it's a history table) — the
        reducer must DELETE-then-INSERT per tick so replaying the same line
        twice (boot load re-run, or a live duplicate UDP notification) does
        not duplicate rows."""
        analytics_ops.apply_power_sample(db, C1_LINE)
        analytics_ops.apply_power_sample(db, C1_LINE)
        n = db.execute(
            "SELECT COUNT(*) FROM power_networks WHERE tick = 12345"
        ).fetchone()[0]
        assert n == 1

    def test_same_tick_reapply_power_samples_still_one_row(self, db):
        analytics_ops.apply_power_sample(db, C1_LINE)
        analytics_ops.apply_power_sample(db, C1_LINE)
        n = db.execute(
            "SELECT COUNT(*) FROM power_samples WHERE tick = 12345"
        ).fetchone()[0]
        assert n == 1

    def test_multiple_ticks_all_present(self, db):
        analytics_ops.apply_power_sample(db, C1_LINE)
        analytics_ops.apply_power_sample(db, HEARTBEAT_LINE)
        ticks = {
            r[0] for r in db.execute("SELECT tick FROM power_samples").fetchall()
        }
        assert ticks == {12345, 12645}


# =============================================================================
# 7b. entity_status full-replace + freshness surface
# =============================================================================


DUMP_A = [
    {"meta": True, "tick": 5000, "count": 2},
    {"name": "assembling-machine-1", "status": "no_power", "x": 986.5, "y": 1140.5},
    {"name": "boiler", "status": "working", "x": 10.0, "y": 20.0},
]

DUMP_B = [
    {"meta": True, "tick": 5060, "count": 1},
    {"name": "boiler", "status": "working", "x": 10.0, "y": 20.0},
]

DUMP_EMPTY = [{"meta": True, "tick": 5120, "count": 0}]


class TestApplyStatusDumpFullReplace:
    def test_dump_a_populates_two_rows(self, db):
        n = analytics_ops.apply_status_dump(db, DUMP_A)
        assert n == 2
        assert db.execute("SELECT COUNT(*) FROM entity_status").fetchone()[0] == 2

    def test_dump_b_replaces_dump_a_exactly(self, db):
        analytics_ops.apply_status_dump(db, DUMP_A)
        analytics_ops.apply_status_dump(db, DUMP_B)
        rows = db.execute(
            "SELECT entity_name, status_name, tick FROM entity_status"
        ).fetchall()
        assert rows == [("boiler", "working", 5060)]

    def test_meta_only_dump_empties_table(self, db):
        analytics_ops.apply_status_dump(db, DUMP_A)
        analytics_ops.apply_status_dump(db, DUMP_EMPTY)
        assert db.execute("SELECT COUNT(*) FROM entity_status").fetchone()[0] == 0

    def test_meta_only_dump_is_still_observable_via_freshness_marker(self, db):
        """Design decision (documented in analytics_ops docstring): the
        freshness surface is sync_state['entity_status_last_tick']. An
        all-meta, zero-entity dump leaves entity_status empty, which alone
        is indistinguishable from 'never ingested anything' — the marker
        makes 'a dump WAS applied, it just said count=0' observable."""
        analytics_ops.apply_status_dump(db, DUMP_EMPTY)
        row = db.execute(
            "SELECT value FROM sync_state WHERE key = 'entity_status_last_tick'"
        ).fetchone()
        assert row == (5120,)

    def test_freshness_marker_tracks_latest_applied_tick(self, db):
        analytics_ops.apply_status_dump(db, DUMP_A)
        row = db.execute(
            "SELECT value FROM sync_state WHERE key = 'entity_status_last_tick'"
        ).fetchone()
        assert row == (5000,)
        analytics_ops.apply_status_dump(db, DUMP_B)
        row = db.execute(
            "SELECT value FROM sync_state WHERE key = 'entity_status_last_tick'"
        ).fetchone()
        assert row == (5060,)


class TestApplyStatusDumpValidation:
    def test_empty_lines_raises(self, db):
        with pytest.raises(ValueError):
            analytics_ops.apply_status_dump(db, [])

    def test_missing_meta_line_raises(self, db):
        with pytest.raises(ValueError):
            analytics_ops.apply_status_dump(
                db, [{"name": "boiler", "status": "working", "x": 1.0, "y": 2.0}]
            )
