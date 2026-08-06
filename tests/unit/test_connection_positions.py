"""Unit tests for the connection-cue Python wrapper parsing (L4.6 findings).

Pins the PY-1 falsy-zero regression: ``defines.direction.north == 0`` is
falsy, and ``Direction(p["direction"]) if p.get("direction")`` silently
stripped the rotation off every north-facing fluid cue — the agent then
placed a rotatable target (boiler, steam engine) at the right position with
an arbitrary direction: adjacent but fluid-dead (the 2026-06-11 finale
field-run failure texture).

The Lua layer itself is certified live by scripts/certification/check_L4_6.py
(cue => engine-verified connection); these tests cover ONLY the Python
parsing between the remote result and ConnectionPosition.
"""

from unittest.mock import MagicMock

import pytest

from FactoryVerse.game.agent.placement_hints import (
    PlacementHints,
    ConnectionPositionList,
    _pole_prototype_distances,
)
from FactoryVerse.game.factory.factorio_types import Direction
from FactoryVerse.game.factory.prototypes import get_entity_prototypes


def _hints_with_fluid_result(positions):
    hints = PlacementHints.__new__(PlacementHints)  # skip RCON wiring
    hints._client = MagicMock()
    hints._client.get_fluid_connections.return_value = {"positions": positions}
    return hints


def _source():
    src = MagicMock()
    src.name = "boiler"
    src.position = MagicMock()
    return src


class TestFluidCueDirectionParsing:
    def test_north_direction_zero_is_preserved(self):
        """PY-1 regression: direction=0 (north) must NOT collapse to None."""
        hints = _hints_with_fluid_result([
            {"position": {"x": 524.5, "y": 25.5}, "direction": 0, "valid": True},
        ])
        cues = hints._get_fluid_pipe_positions(_source(), "steam-engine")
        assert len(cues) == 1
        assert cues[0].direction == Direction.NORTH  # not None!

    def test_all_cardinal_directions_preserved(self):
        hints = _hints_with_fluid_result([
            {"position": {"x": 1.0, "y": 1.0}, "direction": d, "valid": True}
            for d in (0, 4, 8, 12)
        ])
        cues = hints._get_fluid_pipe_positions(_source(), "pipe")
        assert [c.direction for c in cues] == [
            Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST,
        ]

    def test_missing_direction_is_none(self):
        """Direction-less cues (legacy fallback path, LUA-1) parse as None —
        the consumer must treat them as rotation-unknown, not north."""
        hints = _hints_with_fluid_result([
            {"position": {"x": 2.0, "y": 2.0}, "valid": True},
        ])
        cues = hints._get_fluid_pipe_positions(_source(), "pipe")
        assert len(cues) == 1
        assert cues[0].direction is None

    def test_invalid_cues_filtered(self):
        hints = _hints_with_fluid_result([
            {"position": {"x": 1.0, "y": 1.0}, "direction": 4, "valid": False},
            {"position": {"x": 3.0, "y": 3.0}, "direction": 8, "valid": True},
        ])
        cues = hints._get_fluid_pipe_positions(_source(), "pipe")
        assert len(cues) == 1
        assert cues[0].direction == Direction.SOUTH


class TestPolePrototypeDistancesNotHardcoded:
    """PWR-HARDCODE-1: pole wire/supply distances must come from the
    prototype pipeline, not hardcoded per-pole-name dicts that can drift
    from the engine (big-electric-pole's wire distance was hardcoded 30.0;
    the real prototype value is 32 — asserted against the dump, not the
    literal, so this test would have failed against the old hardcoded
    value while still passing if the dump itself changes)."""

    def test_big_electric_pole_wire_distance_matches_dump(self):
        expected_wire, expected_supply = (
            get_entity_prototypes().get_prototype("big-electric-pole")["maximum_wire_distance"],
            get_entity_prototypes().get_prototype("big-electric-pole")["supply_area_distance"],
        )
        wire, supply = _pole_prototype_distances("big-electric-pole")
        assert wire == expected_wire
        assert supply == expected_supply
        # Documented real-world value at time of writing (L3.3-scoped dump)
        assert wire == 32

    def test_small_electric_pole_supply_matches_dump(self):
        expected_supply = get_entity_prototypes().get_prototype(
            "small-electric-pole")["supply_area_distance"]
        _wire, supply = _pole_prototype_distances("small-electric-pole")
        assert supply == expected_supply
        assert supply == 2.5

    def test_unknown_pole_name_raises_loudly(self):
        with pytest.raises(ValueError, match="not-a-real-pole"):
            _pole_prototype_distances("not-a-real-pole")


class TestConnectionPositionListReason:
    """REASON-1: a zero-cue connection query must carry WHY, not just [].

    _get_electric_wire_positions previously discarded everything from the
    Lua result but `positions` — count, max_wire_distance, and (for fluid)
    reason were all thrown away. get_pole_connections never emits `reason`
    at all, so the electric-wire wrapper must synthesize one from what it
    DOES get back (max_wire_distance + search extent + count).
    """

    def _hints_with_pole_result(self, result):
        hints = PlacementHints.__new__(PlacementHints)
        hints._client = MagicMock()
        hints._client.get_pole_connections.return_value = result
        return hints

    def test_empty_electric_result_carries_synthesized_reason(self):
        hints = self._hints_with_pole_result(
            {"positions": {}, "count": 0, "max_wire_distance": 7.5,
             "source_name": "small-electric-pole"}
        )
        cues = hints._get_electric_wire_positions(_source(), "small-electric-pole")

        assert isinstance(cues, ConnectionPositionList)
        # Still list-compatible: empty-list truthiness unchanged
        assert len(cues) == 0
        assert not cues
        assert cues == []

        # But the "why" is no longer thrown away
        assert cues.reason is not None
        assert cues.max_wire_distance == 7.5
        assert "max_wire_distance" in repr(cues)

    def test_non_empty_result_has_no_reason(self):
        hints = self._hints_with_pole_result({
            "positions": [
                {"position": {"x": 1.0, "y": 1.0}, "wire_distance": 5.0,
                 "wire_distance_utilization": 0.5, "valid": True},
            ],
            "count": 1,
            "max_wire_distance": 7.5,
            "source_name": "small-electric-pole",
        })
        cues = hints._get_electric_wire_positions(_source(), "small-electric-pole")
        assert len(cues) == 1
        assert cues.reason is None

    def test_fluid_reason_surfaces_luas_own_reason(self):
        """Fluid's Lua reason (connections/init.lua) must pass through
        unmodified rather than being discarded."""
        hints = PlacementHints.__new__(PlacementHints)
        hints._client = MagicMock()
        hints._client.get_fluid_connections.return_value = {
            "positions": [],
            "count": 0,
            "reason": "source entity exposes no live pipe connections",
            "source_name": "boiler",
        }
        cues = hints._get_fluid_pipe_positions(_source(), "pipe")
        assert len(cues) == 0
        assert cues.reason == "source entity exposes no live pipe connections"


class TestItemDropCueParsing:
    def test_positions_parse_with_perpendicular_offset(self):
        hints = PlacementHints.__new__(PlacementHints)
        hints._client = MagicMock()
        hints._client.get_item_drop_connections.return_value = {
            "positions": [
                {"position": {"x": 496.5, "y": 69.5},
                 "perpendicular_offset": 0.0, "valid": True},
            ]
        }
        cues = hints._get_item_drop_positions(_source(), "wooden-chest")
        assert len(cues) == 1
        assert cues[0].position.x == 496.5
        assert cues[0].perpendicular_offset == 0.0
