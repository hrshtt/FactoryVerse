"""Unit tests for the batched live read and the supply geometry it carries.

What survived the ``verify`` accessor: the mechanism. Geometry (offline,
prototype-backed) is exercised against the real factorio-data-dump.json so
the attempt-5 miss stays pinned to exact numbers with no live server; the
batched status read is covered with a canned payload.

Canonical case (terra-pro attempt-5, 2026-07-11): a medium-electric-pole spine
at y=64.5 (supply_area_distance 3.5) leaves an electric-mining-drill at y=59.5
exactly 0.15 tiles short on Y (collision half-height 1.35: box top at 60.85 vs
supply edge at 61.0), while an electric-furnace at y=62.5 is covered.
"""

import json

import pytest

from FactoryVerse.game.agent.infra.live_batch import (
    compute_supply_coverage,
    live_status_batch,
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



# ---------------------------------------------------------------------------
# live_status_batch — one roundtrip, symbolic status, honest not-found
# ---------------------------------------------------------------------------

class _FakeRcon:
    """Stand-in RconHandler: returns a fixed JSON body for any Lua command."""

    def __init__(self, payload):
        self._payload = payload
        self.last_cmd = None

    def execute(self, cmd, silent=True):
        self.last_cmd = cmd
        return json.dumps(self._payload)


class TestLiveStatusBatch:
    def test_rows_align_with_targets_and_carry_symbolic_status(self):
        rcon = _FakeRcon([
            {"found": True, "name": "electric-furnace", "x": 5.5, "y": 62.5,
             "status_name": "working", "electric_network_id": 7},
            {"found": True, "name": "electric-mining-drill", "x": 5.5, "y": 59.5,
             "status_name": "no_power"},
        ])
        rows = live_status_batch(rcon, [
            ("electric-furnace", {"x": 5.5, "y": 62.5}),
            ("electric-mining-drill", {"x": 5.5, "y": 59.5}),
        ])
        assert [r["name"] for r in rows] == ["electric-furnace", "electric-mining-drill"]
        assert rows[0]["status_name"] == "working" and rows[0]["electric_network_id"] == 7
        assert rows[1]["status_name"] == "no_power" and rows[1]["electric_network_id"] is None
        # the batched read decodes ints symbolically (defines.entity_status)
        assert "defines.entity_status" in rcon.last_cmd

    def test_not_found_is_said_not_guessed(self):
        rcon = _FakeRcon([{"found": False, "name": "electric-furnace", "x": 0.5, "y": 0.5}])
        rows = live_status_batch(rcon, [("electric-furnace", (0.5, 0.5))])
        assert rows[0]["found"] is False and rows[0]["status_name"] is None

    def test_short_payload_pads_with_not_found(self):
        rcon = _FakeRcon([])
        rows = live_status_batch(rcon, [("a", (0.5, 0.5)), ("b", (1.5, 0.5))])
        assert len(rows) == 2 and all(r["found"] is False for r in rows)

    def test_transport_error_is_not_an_empty_answer(self):
        rcon = _FakeRcon({"error": "boom"})
        rows = live_status_batch(rcon, [("a", (0.5, 0.5))])
        # an error payload yields no rows → padded not-found; the caller sees
        # `found=False`, never a fabricated status
        assert rows[0]["found"] is False
