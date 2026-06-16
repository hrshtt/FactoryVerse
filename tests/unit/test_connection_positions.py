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

from FactoryVerse.game.agent.placement_hints import PlacementHints
from FactoryVerse.game.factory.factorio_types import Direction


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
