"""Test Ground utilities for functional tests.

Provides TestGroundHelper for use with RCON clients in functional tests.
These utilities call the test_ground remote interface for placing entities,
resources, and managing test areas.

TODO: test-ground is a scenario, and this helper should eventually be ported
to use the scenario adapter pattern (similar to LabGridAdapter). The adapter
would be auto-detected by Tier4Runtime and accessible via tier4.scenario.

Usage:
    >>> from FactoryVerse.testing import TestGroundHelper
    >>> # With an RCON client (from tier3 or fixtures)
    >>> tg = TestGroundHelper(rcon_client)
    >>> tg.place_entity('iron-chest', 10, 10)
    >>> tg.clear_area((0, 0), (50, 50))
"""

import json
from typing import Optional, Dict, Any, List, Tuple, Union

from factorio_rcon import RCONClient


class TestGroundHelper:
    """Test Ground helper for functional tests.

    Provides resource placement, entity placement, and area management
    for testing and development workflows. Requires only an RCON client.
    """

    # Test area bounds (from test-ground scenario)
    AREA_SIZE = 512
    BOUNDS = {"left_top": {"x": -256, "y": -256}, "right_bottom": {"x": 256, "y": 256}}

    def __init__(self, rcon: Union[RCONClient, Dict[str, Any]]):
        """Initialize with RCON client.

        Args:
            rcon: Either an RCONClient directly, or a dict with 'rcon' key
                  (for backwards compatibility with boilerplate context pattern)
        """
        if isinstance(rcon, dict):
            # Support dict-like context for backwards compatibility
            self.rcon = rcon["rcon"]
        else:
            self.rcon = rcon

    # ========================================================================
    # RESOURCE PLACEMENT
    # ========================================================================

    def place_resource_patch(
        self,
        resource_name: str,
        center_x: float,
        center_y: float,
        size: int,
        amount: int = 10000,
    ) -> Dict[str, Any]:
        """Place a square resource patch."""
        result = self._call(
            "test_ground",
            "place_resource_patch",
            resource_name,
            center_x,
            center_y,
            size,
            amount,
        )
        return result

    def place_iron_patch(
        self, x: float, y: float, size: int = 32, amount: int = 10000
    ) -> Dict[str, Any]:
        """Convenience method for placing iron ore patch."""
        return self.place_resource_patch("iron-ore", x, y, size, amount)

    def place_copper_patch(
        self, x: float, y: float, size: int = 32, amount: int = 10000
    ) -> Dict[str, Any]:
        """Convenience method for placing copper ore patch."""
        return self.place_resource_patch("copper-ore", x, y, size, amount)

    def place_coal_patch(
        self, x: float, y: float, size: int = 32, amount: int = 10000
    ) -> Dict[str, Any]:
        """Convenience method for placing coal patch."""
        return self.place_resource_patch("coal", x, y, size, amount)

    # ========================================================================
    # ENTITY PLACEMENT
    # ========================================================================

    def place_entity(
        self,
        entity_name: str,
        x: float,
        y: float,
        direction: Optional[int] = None,
        force: str = "player",
    ) -> Dict[str, Any]:
        """Place an entity at a position."""
        result = self._call(
            "test_ground",
            "place_entity",
            entity_name,
            {"x": x, "y": y},
            direction,
            force,
        )
        return result

    def place_entity_grid(
        self,
        entity_name: str,
        start_x: float,
        start_y: float,
        rows: int,
        cols: int,
        spacing_x: float = 2.0,
        spacing_y: float = 2.0,
    ) -> List[Dict[str, Any]]:
        """Place entities in a grid pattern."""
        result = self._call(
            "test_ground",
            "place_entity_grid",
            entity_name,
            start_x,
            start_y,
            rows,
            cols,
            spacing_x,
            spacing_y,
        )
        return result.get("entities", [])

    # ========================================================================
    # AREA MANAGEMENT
    # ========================================================================

    def clear_area(
        self,
        left_top: Tuple[float, float],
        right_bottom: Tuple[float, float],
        preserve_characters: bool = True,
    ) -> int:
        """Clear all entities in a bounding box."""
        bounds = {
            "left_top": {"x": left_top[0], "y": left_top[1]},
            "right_bottom": {"x": right_bottom[0], "y": right_bottom[1]},
        }
        result = self._call("test_ground", "clear_area", bounds, preserve_characters)
        return result.get("cleared_count", 0)

    def reset_test_area(self) -> None:
        """Reset entire test area to clean state."""
        self._call("test_ground", "reset_test_area")

    # ========================================================================
    # SNAPSHOT CONTROL
    # ========================================================================

    def force_resnapshot(
        self, chunk_coords: Optional[List[Tuple[int, int]]] = None
    ) -> int:
        """Force re-snapshot of specified chunks."""
        if chunk_coords is not None:
            lua_chunks = [{"x": x, "y": y} for x, y in chunk_coords]
        else:
            lua_chunks = None

        result = self._call("test_ground", "force_resnapshot", lua_chunks)
        return result.get("chunks_enqueued", 0)

    # ========================================================================
    # INTERNALS
    # ========================================================================

    def _call(self, interface: str, method: str, *args) -> Dict[str, Any]:
        """Call a remote interface method."""
        # Serialize args to Lua
        lua_args = ", ".join(self._to_lua(arg) for arg in args)

        cmd = f"/c local res = remote.call('{interface}', '{method}', {lua_args}); rcon.print(helpers.table_to_json(res))"
        result = self.rcon.send_command(cmd)

        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"raw": result}

    def _to_lua(self, value: Any) -> str:
        """Convert Python value to Lua literal."""
        if value is None:
            return "nil"
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            return f'"{value}"'
        elif isinstance(value, dict):
            items = ", ".join(f'["{k}"] = {self._to_lua(v)}' for k, v in value.items())
            return "{" + items + "}"
        elif isinstance(value, (list, tuple)):
            items = ", ".join(self._to_lua(v) for v in value)
            return "{" + items + "}"
        else:
            return str(value)
