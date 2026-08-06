"""Unit tests for VerifyView — the live power/coverage confirmation UX.

Geometry (offline, prototype-backed) is exercised directly against the real
factorio-data-dump.json (assert-to-dump, like test_connection_positions.py), so
the attempt-5 miss is pinned to exact numbers with no live server. The live RCON
leg (powered/connected) is covered with canned payloads.

Canonical case (terra-pro attempt-5, 2026-07-11): a medium-electric-pole spine
at y=64.5 (supply_area_distance 3.5) leaves an electric-mining-drill at y=59.5
exactly 0.15 tiles short on Y (collision half-height 1.35: box top at 60.85 vs
supply edge at 61.0), while an electric-furnace at y=62.5 is covered.
"""

import json

import pytest

from FactoryVerse.game.agent.verify_view import (
    VerifyView,
    PoweredCheck,
    compute_supply_coverage,
    render_ascii_map,
    _collision_box,
)
from FactoryVerse.game.agent.placement_hints import _pole_prototype_distances
from FactoryVerse.game.factory.prototypes import get_entity_prototypes


# ---------------------------------------------------------------------------
# assert-to-dump: the numbers the geometry depends on ARE what the dump says
# ---------------------------------------------------------------------------

class TestDumpBackedConstants:
    def test_medium_pole_supply_is_3_5(self):
        _wire, supply = _pole_prototype_distances("medium-electric-pole")
        assert supply == 3.5

    def test_drill_collision_half_height_is_1_35(self):
        cb = get_entity_prototypes().get_prototype("electric-mining-drill")["collision_box"]
        # collision_box = [[x1,y1],[x2,y2]] centred on the entity
        assert cb[1][1] == 1.35 and cb[0][1] == -1.35

    def test_furnace_collision_half_height_is_1_2(self):
        cb = get_entity_prototypes().get_prototype("electric-furnace")["collision_box"]
        assert cb[1][1] == 1.2 and cb[0][1] == -1.2

    def test_collision_box_is_position_plus_offset(self):
        # box of a drill centred at (5.5, 59.5): y-top = 59.5 + 1.35 = 60.85
        box = _collision_box(get_entity_prototypes(), "electric-mining-drill", 5.5, 59.5)
        assert box == pytest.approx((4.15, 58.15, 6.85, 60.85))


# ---------------------------------------------------------------------------
# the attempt-5 geometry: drill 0.15 short on Y, furnace covered
# ---------------------------------------------------------------------------

class TestAttempt5Geometry:
    def _cov(self):
        poles = [{"pole_name": "medium-electric-pole", "x": 5.5, "y": 64.5}]
        ents = [
            ("electric-mining-drill", 5.5, 59.5),
            ("electric-furnace", 5.5, 62.5),
        ]
        return {c.entity_name: c for c in compute_supply_coverage(ents, poles)}

    def test_drill_not_covered_0_15_on_Y(self):
        drill = self._cov()["electric-mining-drill"]
        assert drill.covered is False
        assert drill.margin == pytest.approx(0.15)
        assert drill.margin_axis == "Y"
        assert "toward y=64.5" in drill.detail
        assert drill.by_pole_name == "medium-electric-pole"

    def test_furnace_covered(self):
        furnace = self._cov()["electric-furnace"]
        assert furnace.covered is True
        # overlap depth: furnace box y[61.3,63.7] inside supply y[61.0,68.0];
        # min overlap depth is 2.4 (the x-axis is centred, y-top gap 2.7)
        assert furnace.margin == pytest.approx(2.4)
        assert furnace.by_pole_name == "medium-electric-pole"

    def test_proposed_pole_preview_flips_drill_to_covered(self):
        poles = [
            {"pole_name": "medium-electric-pole", "x": 5.5, "y": 64.5},
            # as-if-placed one tile closer to the drill
            {"pole_name": "medium-electric-pole", "x": 5.5, "y": 63.5,
             "is_proposed": True},
        ]
        ents = [("electric-mining-drill", 5.5, 59.5)]
        drill = compute_supply_coverage(ents, poles)[0]
        # new supply edge: 63.5 - 3.5 = 60.0 <= drill box top 60.85 -> covered
        assert drill.covered is True


# ---------------------------------------------------------------------------
# deterministic ascii snapshot (small 2-pole, 3-entity scene)
# ---------------------------------------------------------------------------

EXPECTED_ASCII = (
    "         5    10\n"
    "         |    |\n"
    "   1 #####.#####\n"
    "   2 #####.#####\n"
    "   3 ##F##A##P##\n"
    "   4 #####.#####\n"
    "   5-#####.#####\n"
    "   6 ...........\n"
    "   7 ........d..\n"
    "legend: # supply tile  . uncovered  P pole  ? proposed  "
    "UPPER=entity covered  lower=NOT covered"
)


class TestAsciiSnapshot:
    def test_stable_render(self):
        poles = [
            {"pole_name": "small-electric-pole", "x": 3.5, "y": 3.5},
            {"pole_name": "small-electric-pole", "x": 9.5, "y": 3.5},
        ]
        ents = [
            ("electric-furnace", 3.5, 3.5),
            ("electric-mining-drill", 9.5, 7.5),
            ("assembling-machine-1", 6.5, 3.5),
        ]
        cov = compute_supply_coverage(ents, poles)
        resolved = []
        for p in poles:
            _w, s = _pole_prototype_distances(p["pole_name"])
            resolved.append({"name": p["pole_name"], "x": p["x"], "y": p["y"],
                             "supply": s, "is_proposed": False})
        resolved.sort(key=lambda q: (q["is_proposed"], q["x"], q["y"], q["name"]))
        assert render_ascii_map(cov, resolved) == EXPECTED_ASCII


# ---------------------------------------------------------------------------
# powered() mapping from a canned Lua payload
# ---------------------------------------------------------------------------

class _FakeRcon:
    """Stand-in RconHandler: returns a fixed JSON body for any Lua command."""

    def __init__(self, payload):
        self._payload = payload
        self.last_cmd = None

    def execute(self, cmd, silent=True):
        self.last_cmd = cmd
        return json.dumps(self._payload)


class TestPoweredMapping:
    def _view(self, payload):
        v = VerifyView.__new__(VerifyView)  # skip real RCON wiring
        v._rcon = _FakeRcon(payload)
        v._prototypes = get_entity_prototypes()
        return v

    def test_powered_and_unpowered_mapping(self):
        payload = [
            {"found": True, "name": "electric-furnace", "x": 5.5, "y": 62.5,
             "status_name": "working", "electric_network_id": 7, "powered": True},
            {"found": True, "name": "electric-mining-drill", "x": 5.5, "y": 59.5,
             "status_name": "no_power", "powered": False},
        ]
        v = self._view(payload)
        checks = v.powered([
            ("electric-furnace", {"x": 5.5, "y": 62.5}),
            ("electric-mining-drill", {"x": 5.5, "y": 59.5}),
        ])
        furnace = checks["electric-furnace@(5.5,62.5)"]
        drill = checks["electric-mining-drill@(5.5,59.5)"]
        assert isinstance(furnace, PoweredCheck)
        assert furnace.powered is True
        assert furnace.status_name == "working"
        assert furnace.electric_network_id == 7
        assert drill.powered is False
        assert drill.status_name == "no_power"
        assert drill.electric_network_id is None

    def test_single_target_accepted(self):
        payload = [{"found": True, "name": "electric-furnace", "x": 1.5, "y": 2.5,
                    "status_name": "working", "electric_network_id": 3, "powered": True}]
        v = self._view(payload)
        checks = v.powered(("electric-furnace", {"x": 1.5, "y": 2.5}))
        assert checks["electric-furnace@(1.5,2.5)"].powered is True

    def test_not_found_maps_cleanly(self):
        payload = [{"found": False, "name": "electric-furnace", "x": 0.5, "y": 0.5}]
        v = self._view(payload)
        chk = v.powered(("electric-furnace", (0.5, 0.5)))["electric-furnace@(0.5,0.5)"]
        assert chk.found is False and chk.powered is False

    def test_lua_body_decodes_status_via_defines(self):
        # the batched read must decode ints symbolically (defines.entity_status)
        payload = []
        v = self._view(payload)
        v.powered(("electric-furnace", (0.5, 0.5)))
        assert "defines.entity_status" in v._rcon.last_cmd


# ---------------------------------------------------------------------------
# connected() over the same canned path
# ---------------------------------------------------------------------------

class TestConnected:
    def _view(self, payload):
        v = VerifyView.__new__(VerifyView)
        v._rcon = _FakeRcon(payload)
        v._prototypes = get_entity_prototypes()
        return v

    def test_same_network_is_connected(self):
        payload = [
            {"found": True, "name": "electric-energy-interface", "x": 2.5, "y": 64.5,
             "status_name": "working", "electric_network_id": 9, "powered": True},
            {"found": True, "name": "medium-electric-pole", "x": 5.5, "y": 64.5,
             "status_name": "working", "electric_network_id": 9, "powered": True},
        ]
        v = self._view(payload)
        chk = v.connected(
            ("electric-energy-interface", {"x": 2.5, "y": 64.5}),
            ("medium-electric-pole", {"x": 5.5, "y": 64.5}),
        )
        assert chk.connected is True and "electric_network_id 9" in chk.explanation

    def test_different_network_not_connected(self):
        payload = [
            {"found": True, "name": "a", "x": 0.5, "y": 0.5, "electric_network_id": 1,
             "powered": True, "status_name": "working"},
            {"found": True, "name": "b", "x": 1.5, "y": 0.5, "electric_network_id": 2,
             "powered": True, "status_name": "working"},
        ]
        v = self._view(payload)
        chk = v.connected(("a", (0.5, 0.5)), ("b", (1.5, 0.5)))
        assert chk.connected is False
