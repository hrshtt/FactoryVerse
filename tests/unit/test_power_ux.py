"""Offline unit tests for the agent-facing power UX layer (WS4):
RemoteView.get_power_networks / diagnose_power and the Task Progress power
digest line.

No Factorio needed: the power sample and the status dump are written as the
real files the mods produce (they are NOT tables — Constitution §10), read
on demand by remote_view.power()/diagnose_power, joined to direct map_entity
inserts (the as-of-write electric_network_id the census/diagnosis join on).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from FactoryVerse.game.infra.duckdb.query import QueryExecutor
from FactoryVerse.game.agent.remote_view import RemoteView


# =============================================================================
# Harness — a RemoteView backed by a real in-memory DB, no load()/RCON
# =============================================================================


def _make_view(root: Path | None = None) -> RemoteView:
    rv = RemoteView(
        snapshot_dir=root if root is not None else Path("."),
        entity_ops=None,
        place_ops=None,
        walking_action=None,
        mining_action=None,
        udp_dispatcher=None,
        rcon_client=None,
    )
    rv._database.ensure_schema()
    rv._query = QueryExecutor(
        rv._database.connection,
        entity_ops=None,
        place_ops=None,
        walking_action=None,
        mining_action=None,
        sync_service=None,
        db_lock=rv._db_lock,
    )
    rv._loaded = True
    return rv


def _ins_entity(con, name, x, y, nid=None, force="player"):
    con.execute(
        "INSERT INTO map_entity "
        "(entity_name, position_x, position_y, chunk_x, chunk_y, electric_network_id, force) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [name, x, y, int(x) // 32, int(y) // 32, nid, force],
    )


# One sample tick with four networks + a status dump covering the members.
#   nid 4  working rig            77.5kW gen / 50.0kW load   (headroom 1.55)
#   nid 9  undersupplied          30.0kW / 60.0kW            (1 low_power)
#   nid 5  no generation           0.0kW / 50.0kW            (1 no_power)
#   nid 7  starved generator       0.0kW / 50.0kW            (no_power + no_fuel boiler)
POWER_LINE = {
    "tick": 1000,
    "networks": [
        {"network_id": 4, "anchor_pole": {"name": "small-electric-pole", "position": {"x": 10.5, "y": 10.5}},
         "pole_count": 1, "member_count": 2, "production_w": 77500.0, "consumption_w": 50000.0, "storage_j": 0.0,
         "production_w_by_prototype": {"electric-energy-interface": 77500.0},
         "consumption_w_by_prototype": {"assembling-machine-1": 50000.0}},
        {"network_id": 9, "anchor_pole": {"name": "small-electric-pole", "position": {"x": 20.5, "y": 20.5}},
         "pole_count": 1, "member_count": 2, "production_w": 30000.0, "consumption_w": 60000.0, "storage_j": 0.0,
         "production_w_by_prototype": {"steam-engine": 30000.0},
         "consumption_w_by_prototype": {"assembling-machine-1": 60000.0}},
        {"network_id": 5, "anchor_pole": {"name": "small-electric-pole", "position": {"x": 30.5, "y": 30.5}},
         "pole_count": 1, "member_count": 1, "production_w": 0.0, "consumption_w": 50000.0, "storage_j": 0.0,
         "production_w_by_prototype": {},
         "consumption_w_by_prototype": {"assembling-machine-1": 50000.0}},
        {"network_id": 7, "anchor_pole": {"name": "small-electric-pole", "position": {"x": 40.5, "y": 40.5}},
         "pole_count": 1, "member_count": 2, "production_w": 0.0, "consumption_w": 50000.0, "storage_j": 0.0,
         "production_w_by_prototype": {},
         "consumption_w_by_prototype": {"assembling-machine-1": 50000.0}},
    ],
}

STATUS_DUMP = [
    {"meta": True, "tick": 1000, "count": 6},
    {"name": "assembling-machine-1", "status": "working", "x": 11.5, "y": 11.5},
    {"name": "assembling-machine-1", "status": "low_power", "x": 21.5, "y": 21.5},
    {"name": "assembling-machine-1", "status": "no_power", "x": 31.5, "y": 31.5},
    {"name": "assembling-machine-1", "status": "no_power", "x": 41.5, "y": 41.5},
    {"name": "boiler", "status": "no_fuel", "x": 42.5, "y": 42.5},
    {"name": "assembling-machine-1", "status": "no_power", "x": 500.5, "y": 500.5},
]


def _write_feeds(root: Path, power_lines, status_dump) -> None:
    (root / "factoryverse" / "snapshots").mkdir(parents=True, exist_ok=True)
    (root / "factoryverse" / "status").mkdir(parents=True, exist_ok=True)
    (root / "factoryverse" / "snapshots" / "power_networks.jsonl").write_text(
        "".join(json.dumps(l) + "\n" for l in power_lines)
    )
    tick = status_dump[0]["tick"]
    (root / "factoryverse" / "status" / f"status-{tick}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in status_dump)
    )


@pytest.fixture()
def seeded(tmp_path) -> RemoteView:
    _write_feeds(tmp_path, [POWER_LINE], STATUS_DUMP)
    rv = _make_view(tmp_path)
    rv._feed_root = tmp_path
    con = rv._database.connection
    # anchor poles
    _ins_entity(con, "small-electric-pole", 10.5, 10.5, nid=4)
    _ins_entity(con, "small-electric-pole", 20.5, 20.5, nid=9)
    _ins_entity(con, "small-electric-pole", 30.5, 30.5, nid=5)
    _ins_entity(con, "small-electric-pole", 40.5, 40.5, nid=7)
    # members
    _ins_entity(con, "assembling-machine-1", 11.5, 11.5, nid=4)
    _ins_entity(con, "assembling-machine-1", 21.5, 21.5, nid=9)
    _ins_entity(con, "assembling-machine-1", 31.5, 31.5, nid=5)
    _ins_entity(con, "assembling-machine-1", 41.5, 41.5, nid=7)
    _ins_entity(con, "boiler", 42.5, 42.5, nid=7)
    _ins_entity(con, "assembling-machine-1", 500.5, 500.5, nid=None)  # uncovered
    return rv


def _net(report, nid):
    return next(n for n in report.networks if n.network_id == nid)


# =============================================================================
# get_power_networks — census
# =============================================================================


class TestCensus:
    def test_no_sample_returns_none_tick(self, tmp_path):
        rv = _make_view(tmp_path)
        report = rv.power()
        assert report.sample_tick is None
        assert report.networks == []
        assert "no power sample" in report.freshness_note
        assert report.source == "power_dump:none"

    def test_all_networks_present_ordered_by_anchor(self, seeded):
        report = seeded.power()
        assert report.sample_tick == 1000
        assert report.source == "power_dump:1000" and report.status_source == "status_dump:1000"
        assert [n.network_id for n in report.networks] == [4, 9, 5, 7]  # ordered by anchor x

    def test_get_power_networks_is_the_same_read(self, seeded):
        assert seeded.power().source == seeded.power().source

    def test_working_rig_fields(self, seeded):
        net = _net(seeded.power(), 4)
        assert net.anchor_pole_name == "small-electric-pole"
        assert net.anchor_pole_position == {"x": 10.5, "y": 10.5}
        assert (net.production_w, net.consumption_w) == (77500.0, 50000.0)
        assert net.headroom_ratio == pytest.approx(1.55)
        assert net.production_by_prototype == {"electric-energy-interface": 77500.0}
        assert net.consumption_by_prototype == {"assembling-machine-1": 50000.0}
        assert (net.low_power_count, net.no_power_count) == (0, 0)

    def test_undersupplied_rig_counts_and_headroom(self, seeded):
        net = _net(seeded.power(), 9)
        assert net.headroom_ratio == pytest.approx(0.5)
        assert net.low_power_count == 1
        assert net.no_power_count == 0

    def test_no_generation_rig(self, seeded):
        net = _net(seeded.power(), 5)
        assert net.production_w == 0.0
        assert net.headroom_ratio == pytest.approx(0.0)  # 0/50000
        assert net.no_power_count == 1

    def test_freshness_note_mentions_status_join(self, seeded):
        note = seeded.power().freshness_note
        assert "tick 1000" in note
        assert "as-of" in note

    def test_as_of_tick_param(self, seeded):
        # no sample at or before 999 on disk: say so, never fabricate a block
        report = seeded.power(as_of_tick=999)
        assert report.sample_tick is None
        assert report.networks == []
        assert "at or before tick 999" in report.freshness_note
        # at or before 1000 is the block itself
        assert seeded.power(as_of_tick=1000).sample_tick == 1000

    def test_unattributed_no_power_counts_orphans(self, seeded):
        # DIGEST-2: the no_power assembler at (500.5,500.5) has nid=None —
        # it attributes to NO network and must not vanish from the report.
        report = seeded.power()
        assert report.unattributed_no_power == 1
        # ...and it must NOT also be inside any per-network count
        assert sum(n.no_power_count for n in report.networks) == 2  # nets 5 and 7 only

    def test_unattributed_counts_status_without_map_entity_row(self, seeded):
        # An entity present in the status dump but absent from map_entity
        # entirely is also an orphan. The dump is re-read on every call.
        _write_feeds(seeded._feed_root, [POWER_LINE], STATUS_DUMP + [
            {"name": "electric-mining-drill", "status": "no_power", "x": 600.5, "y": 600.5},
        ])
        assert seeded.power().unattributed_no_power == 2


# =============================================================================
# diagnose_power
# =============================================================================


class TestDiagnose:
    def test_working(self, seeded):
        d = seeded.diagnose_power("assembling-machine-1", {"x": 11.5, "y": 11.5})
        assert d.verdict == "working"
        assert "working" in d.explanation

    def test_uncovered_no_power(self, seeded):
        d = seeded.diagnose_power("assembling-machine-1", (500.5, 500.5))
        assert d.verdict == "not_covered_by_any_pole"

    def test_no_generation(self, seeded):
        d = seeded.diagnose_power("assembling-machine-1", {"x": 31.5, "y": 31.5})
        assert d.verdict == "network_has_no_generation"
        assert d.covering_pole_name == "small-electric-pole"
        assert d.production_w == 0.0

    def test_upstream_generator_starved(self, seeded):
        d = seeded.diagnose_power("assembling-machine-1", {"x": 41.5, "y": 41.5})
        assert d.verdict == "upstream_generator_starved"
        assert "boiler" in d.explanation

    def test_undersupplied_low_power(self, seeded):
        d = seeded.diagnose_power("assembling-machine-1", {"x": 21.5, "y": 21.5})
        assert d.verdict == "network_undersupplied"
        assert d.production_w == 30000.0
        assert d.consumption_w == 60000.0

    def test_entity_not_found(self, seeded):
        d = seeded.diagnose_power("assembling-machine-1", {"x": 999.0, "y": 999.0})
        assert d.verdict == "entity_not_found"

    def test_pole_reports_nil_status(self, seeded):
        d = seeded.diagnose_power("small-electric-pole", {"x": 10.5, "y": 10.5})
        assert d.verdict == "non_electric_or_no_issue"
        assert "nil-status" in d.explanation

    def test_no_status_data(self, seeded):
        con = seeded._database.connection
        _ins_entity(con, "assembling-machine-1", 70.5, 70.5, nid=4)  # in map, not in status dump
        d = seeded.diagnose_power("assembling-machine-1", {"x": 70.5, "y": 70.5})
        assert d.verdict == "no_status_data"


# =============================================================================
# Task Progress power digest line (never throws)
# =============================================================================


def _render(rv):
    from FactoryVerse.infra.llm.orchestrator import AgentOrchestrator

    class _Runtime:
        remote_view = rv

    class _Self:
        runtime = _Runtime()

    return AgentOrchestrator._render_power_digest_line(_Self())


class TestDigestLine:
    def test_omitted_when_no_sample(self, tmp_path):
        assert _render(_make_view(tmp_path)) is None

    def test_full_line(self, seeded):
        line = _render(seeded)
        assert line == (
            "power: 4 nets | "
            "net@(10.5,10.5) 77.5kW/50.0kW gen/load | "
            "net@(20.5,20.5) 30.0kW/60.0kW 1 low_power | "
            "net@(30.5,30.5) 0.0kW/50.0kW 1 no_power | "
            "+1 more | "
            "1 unpowered (no net)"  # DIGEST-2: the nid=None orphan at (500.5,500.5)
        )

    def test_never_throws_on_broken_view(self):
        class _Runtime:
            remote_view = object()  # get_power_networks missing -> AttributeError

        class _Self:
            runtime = _Runtime()

        from FactoryVerse.infra.llm.orchestrator import AgentOrchestrator

        assert AgentOrchestrator._render_power_digest_line(_Self()) is None



# =============================================================================
# status() / status_changed() — the base-wide read, source-declared
# =============================================================================


class TestStatusSummary:
    def test_groups_by_status_with_positions_and_source(self, seeded):
        summary = seeded.status(max_positions=2)
        assert summary.source == "status_dump:1000" and summary.tick == 1000
        assert summary.total == 6
        assert summary.count("no_power") == 3
        no_power = summary.groups["no_power"]
        assert len(no_power.entities) == 2 and no_power.more == 1
        assert summary.age_ticks is None  # no engine connection: no fake age

    def test_status_filter(self, seeded):
        summary = seeded.status(statuses=["no_fuel"])
        assert set(summary.groups) == {"no_fuel"}
        assert summary.groups["no_fuel"].entities == [("boiler", 42.5, 42.5)]

    def test_no_dump_is_none_not_healthy(self, tmp_path):
        summary = _make_view(tmp_path).status()
        assert summary.tick is None and summary.groups == {} and summary.source == "status_dump:none"

    def test_changed_uses_two_blocks(self, seeded):
        root = seeded._feed_root
        (root / "factoryverse" / "status" / "status-1600.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in [
                {"meta": True, "tick": 1600, "count": 1},
                {"name": "boiler", "status": "working", "x": 42.5, "y": 42.5},
            ])
        )
        change = seeded.status_changed(since_tick=1000)
        assert change.source == "status_dump:1000->1600"
        assert "no_fuel -> working" in change.grouped()
