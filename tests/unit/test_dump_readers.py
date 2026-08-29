"""The on-demand readers that replaced the polled tables (Constitution §10,
API plan §4.6): StatusDumpReader over factoryverse/status/status-<tick>.jsonl
and PowerDumpReader over factoryverse/snapshots/power_networks.jsonl.

Fixtures are the real file shapes the mods write (Entities.lua
dump_status_to_disk; Power.lua _on_nth_tick_power_networks_sample).
"""

from __future__ import annotations

import json

from FactoryVerse.game.agent.power_dump import PowerDumpReader, parse_samples
from FactoryVerse.game.agent.status_dump import StatusDumpReader

POWER_LINE = {
    "tick": 12345,
    "networks": [
        {
            "network_id": 4,
            "anchor_pole": {"name": "small-electric-pole", "position": {"x": 971.5, "y": 971.5}},
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
HEARTBEAT = {"tick": 12645, "networks": []}


def _write_status(root, tick, records):
    d = root / "factoryverse" / "status"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"status-{tick}.jsonl", "w") as f:
        f.write(json.dumps({"meta": True, "tick": tick, "count": len(records)}) + "\n")
        for r in records:
            f.write(json.dumps(r) + "\n")


def _write_power(root, lines, torn=False):
    d = root / "factoryverse" / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(l) + "\n" for l in lines)
    if torn:
        text += '{"tick": 99999, "netw'
    (d / "power_networks.jsonl").write_text(text)


class TestPowerDumpReader:
    def test_newest_is_the_highest_tick_and_names_its_source(self, tmp_path):
        _write_power(tmp_path, [POWER_LINE, HEARTBEAT])
        r = PowerDumpReader(tmp_path / "factoryverse" / "snapshots" / "power_networks.jsonl")
        newest = r.newest()
        assert newest.tick == 12645 and newest.networks == []
        assert newest.source == "power_dump:12645"
        assert r.available_ticks() == [12345, 12645]

    def test_at_or_before_and_network_lookup(self, tmp_path):
        _write_power(tmp_path, [POWER_LINE, HEARTBEAT])
        r = PowerDumpReader(tmp_path / "factoryverse" / "snapshots" / "power_networks.jsonl")
        s = r.at_or_before(12400)
        assert s.tick == 12345
        assert s.network(4)["anchor_pole"]["name"] == "small-electric-pole"
        assert s.network(5) is None and s.network(None) is None
        assert r.at_or_before(100) is None

    def test_missing_file_and_torn_line(self, tmp_path):
        assert PowerDumpReader(tmp_path / "nope.jsonl").newest() is None
        _write_power(tmp_path, [POWER_LINE], torn=True)
        r = PowerDumpReader(tmp_path / "factoryverse" / "snapshots" / "power_networks.jsonl")
        assert [s.tick for s in r.samples()] == [12345]

    def test_parse_ignores_non_sample_lines(self):
        assert [s.tick for s in parse_samples(["", "not json", json.dumps({"x": 1}), json.dumps(HEARTBEAT)])] == [12645]


class TestStatusDumpReader:
    def test_newest_by_tick_in_filename_not_iteration_order(self, tmp_path):
        _write_status(tmp_path, 5000, [{"name": "boiler", "status": "working", "x": 10.0, "y": 20.0}])
        _write_status(tmp_path, 4000, [{"name": "boiler", "status": "no_power", "x": 1.0, "y": 2.0}])
        r = StatusDumpReader(tmp_path / "factoryverse" / "status")
        block = r.current()
        assert block.tick == 5000 and block.source == "status_dump:5000"
        assert block.records == {("boiler", 10.0, 20.0): "working"}

    def test_changed_between_two_blocks(self, tmp_path):
        _write_status(tmp_path, 4000, [
            {"name": "boiler", "status": "no_power", "x": 1.0, "y": 2.0},
            {"name": "stone-furnace", "status": "working", "x": 3.0, "y": 4.0},
        ])
        _write_status(tmp_path, 5000, [
            {"name": "boiler", "status": "working", "x": 1.0, "y": 2.0},
            {"name": "burner-mining-drill", "status": "no_fuel", "x": 5.0, "y": 6.0},
        ])
        change = StatusDumpReader(tmp_path / "factoryverse" / "status").changed(4000)
        assert change.source == "status_dump:4000->5000"
        assert set(change.grouped()) == {"no_power -> working", "gone (was working)", "appeared as no_fuel"}

    def test_empty_directory_is_none_not_working(self, tmp_path):
        r = StatusDumpReader(tmp_path / "factoryverse" / "status")
        assert r.current() is None
        change = r.changed(0)
        assert change.from_tick is None and change.to_tick is None and change.transitions == []
