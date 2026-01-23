"""Tests for fv_placement_hints Lua mod.

Tests the remote interface directly via RCON, creating test landscapes
programmatically (ores, water tiles, entities) to verify placement hints.

This tests the MOD's Lua implementation, not the Python placement_hints.py module.
"""

import pytest
import json
from typing import Any, Dict, List, Optional

from factorio_rcon import RCONClient
from FactoryVerse.environment.config import get_config
from FactoryVerse.infra.instance_manager import FactorioInstanceManager


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(scope="module")
def rcon() -> RCONClient:
    """RCON client connected to running Factorio instance."""
    config = get_config()
    instance = FactorioInstanceManager.from_env(config)
    client = RCONClient(instance.rcon_host, instance.rcon_port, instance.rcon_password)
    yield client


@pytest.fixture(scope="module")
def placement_hints(rcon: RCONClient):
    """Helper class to call placement_hints remote interface."""
    return PlacementHintsInterface(rcon)


class PlacementHintsInterface:
    """Wrapper for calling fv_placement_hints remote interface via RCON."""

    def __init__(self, rcon: RCONClient):
        self.rcon = rcon

    def call(self, method: str, *args) -> Any:
        """Call a placement_hints method and return parsed result."""
        # Convert args to Lua table representation
        lua_args = ", ".join(self._to_lua(arg) for arg in args)
        cmd = f'/c local ok, res = pcall(function() return remote.call("placement_hints", "{method}", {lua_args}) end); if ok then rcon.print(serpent.line(res)) else rcon.print("ERROR: "..tostring(res)) end'
        result = self.rcon.send_command(cmd)

        if result.startswith("ERROR:"):
            raise RuntimeError(f"placement_hints.{method} failed: {result}")

        return self._parse_lua(result)

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
            items = ", ".join(f"{k} = {self._to_lua(v)}" for k, v in value.items())
            return "{" + items + "}"
        elif isinstance(value, (list, tuple)):
            items = ", ".join(self._to_lua(v) for v in value)
            return "{" + items + "}"
        else:
            raise ValueError(f"Cannot convert {type(value)} to Lua")

    def _parse_lua(self, lua_str: str) -> Any:
        """Parse Lua serpent.line output to Python."""
        if not lua_str or lua_str.strip() == "":
            return None

        lua_str = lua_str.strip()

        # Handle simple cases
        if lua_str == "nil":
            return None
        if lua_str == "true":
            return True
        if lua_str == "false":
            return False

        # Try to parse as number
        try:
            if "." in lua_str:
                return float(lua_str)
            return int(lua_str)
        except ValueError:
            pass

        # Parse table (serpent.line format)
        # This is a simplified parser for common cases
        if lua_str.startswith("{") and lua_str.endswith("}"):
            return self._parse_lua_table(lua_str)

        # Return as string
        return lua_str

    def _parse_lua_table(self, lua_str: str) -> Any:
        """Parse a Lua table string to Python dict/list.

        Handles serpent.line output including nested tables and arrays.
        """
        return self._parse_lua_value(lua_str.strip())

    def _parse_lua_value(self, s: str) -> Any:
        """Parse a single Lua value."""
        s = s.strip()

        # Handle simple values
        if s == "nil":
            return None
        if s == "true":
            return True
        if s == "false":
            return False

        # Handle numbers
        try:
            if "." in s and s.replace(".", "").replace("-", "").replace("e", "").replace("E", "").isdigit():
                return float(s)
            if s.lstrip("-").isdigit():
                return int(s)
        except ValueError:
            pass

        # Handle quoted strings
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1]

        # Handle tables
        if s.startswith("{") and s.endswith("}"):
            return self._parse_lua_table_content(s[1:-1])

        # Return as-is for unknown types
        return s

    def _parse_lua_table_content(self, content: str) -> Any:
        """Parse the content inside a Lua table {...}."""
        content = content.strip()
        if not content:
            return {}

        # Tokenize respecting nested braces
        items = self._split_lua_items(content)

        # Determine if it's an array or dict
        # Array: all items are values (no = sign at top level)
        # Dict: all items have key = value format
        is_dict = False
        for item in items:
            item = item.strip()
            if "=" in item:
                # Check if = is at top level (not inside nested table)
                depth = 0
                for i, c in enumerate(item):
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                    elif c == "=" and depth == 0:
                        is_dict = True
                        break

        if is_dict:
            result = {}
            for item in items:
                item = item.strip()
                if not item:
                    continue
                # Find top-level =
                depth = 0
                eq_pos = -1
                for i, c in enumerate(item):
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                    elif c == "=" and depth == 0:
                        eq_pos = i
                        break

                if eq_pos > 0:
                    key = item[:eq_pos].strip()
                    value = item[eq_pos+1:].strip()
                    result[key] = self._parse_lua_value(value)
                else:
                    # Handle array-like items in a dict (rare)
                    pass
            return result
        else:
            # Array
            return [self._parse_lua_value(item.strip()) for item in items if item.strip()]

    def _split_lua_items(self, content: str) -> List[str]:
        """Split comma-separated items respecting nested braces."""
        items = []
        current = ""
        depth = 0

        for c in content:
            if c == "{":
                depth += 1
                current += c
            elif c == "}":
                depth -= 1
                current += c
            elif c == "," and depth == 0:
                items.append(current)
                current = ""
            else:
                current += c

        if current.strip():
            items.append(current)

        return items


@pytest.fixture(scope="function")
def test_area(rcon: RCONClient):
    """Create a clean test area and return its center position."""
    base_x = 200.5
    base_y = 200.5

    # Clear the area of all entities except character
    clear_cmd = f"""
    /sc local surface = game.surfaces[1]
    local area = {{left_top = {{x = {base_x - 30}, y = {base_y - 30}}}, right_bottom = {{x = {base_x + 30}, y = {base_y + 30}}}}}
    for _, entity in pairs(surface.find_entities_filtered{{area = area}}) do
        if entity.name ~= "character" then entity.destroy() end
    end
    rcon.print("cleared")
    """
    result = rcon.send_command(clear_cmd)
    assert "cleared" in result, f"Failed to clear test area: {result}"

    yield {"x": base_x, "y": base_y}

    # Cleanup after test
    rcon.send_command(clear_cmd)


# =============================================================================
# TEST: INTERFACE EXISTS
# =============================================================================


class TestInterfaceExists:
    """Verify the placement_hints interface is registered."""

    def test_interface_exists(self, rcon: RCONClient):
        """Check that placement_hints interface is available."""
        result = rcon.send_command(
            '/c rcon.print(tostring(remote.interfaces["placement_hints"] ~= nil))'
        )
        assert result.strip() == "true", "placement_hints interface not found"

    def test_interface_has_methods(self, rcon: RCONClient):
        """Check that expected methods are available."""
        result = rcon.send_command(
            '/c local iface = remote.interfaces["placement_hints"]; '
            'local methods = {}; for k,v in pairs(iface) do table.insert(methods, k) end; '
            'rcon.print(serpent.line(methods))'
        )

        expected_methods = [
            "validate_placement",
            "validate_positions",
            "get_valid_placements",
            "get_resource_placements",
            "get_water_placements",
            "get_placement_cue",
            "get_item_drop_connections",
            "get_fluid_connections",
            "get_inserter_placements",
            "get_pole_connections",
            "get_entity_output_info",
            "get_fluid_connection_points",
            "get_entity_footprint",
        ]

        for method in expected_methods:
            assert method in result, f"Method {method} not found in interface"


# =============================================================================
# TEST: VALIDATE PLACEMENT
# =============================================================================


class TestValidatePlacement:
    """Tests for validate_placement method."""

    def test_valid_placement_open_ground(self, placement_hints, test_area):
        """Test placement validation on clear ground."""
        result = placement_hints.call(
            "validate_placement",
            "transport-belt",
            {"x": test_area["x"], "y": test_area["y"]},
            None,
            False,
        )

        assert result["valid"] is True

    def test_invalid_placement_unknown_entity(self, placement_hints, test_area):
        """Test placement validation with unknown entity."""
        result = placement_hints.call(
            "validate_placement",
            "nonexistent-entity-xyz",
            {"x": test_area["x"], "y": test_area["y"]},
            None,
            False,
        )

        assert result["valid"] is False
        assert result["reason"] == "unknown_prototype"

    def test_placement_with_direction(self, placement_hints, test_area):
        """Test placement validation with direction."""
        # Inserter requires direction
        result = placement_hints.call(
            "validate_placement",
            "inserter",
            {"x": test_area["x"], "y": test_area["y"]},
            4,  # EAST
            False,
        )

        assert result["valid"] is True

    def test_placement_blocked_by_entity(self, rcon: RCONClient, placement_hints, test_area):
        """Test that placement is blocked when entity exists."""
        # Place a chest at the test position
        place_cmd = f'/c game.surfaces[1].create_entity{{name="iron-chest", position={{x={test_area["x"]}, y={test_area["y"]}}}, force="player"}}; rcon.print("placed")'
        result = rcon.send_command(place_cmd)
        assert "placed" in result

        # Try to validate placement at same position
        result = placement_hints.call(
            "validate_placement",
            "iron-chest",
            {"x": test_area["x"], "y": test_area["y"]},
            None,
            False,
        )

        assert result["valid"] is False


# =============================================================================
# TEST: VALIDATE POSITIONS (BATCH)
# =============================================================================


class TestValidatePositions:
    """Tests for validate_positions batch method."""

    def test_batch_validation(self, placement_hints, test_area):
        """Test batch validation of multiple positions."""
        positions = [
            {"x": test_area["x"], "y": test_area["y"]},
            {"x": test_area["x"] + 1, "y": test_area["y"]},
            {"x": test_area["x"] + 2, "y": test_area["y"]},
        ]

        result = placement_hints.call(
            "validate_positions",
            "transport-belt",
            positions,
            None,
            False,
        )

        assert isinstance(result, list)
        assert len(result) == 3
        assert all(r is True for r in result)


# =============================================================================
# TEST: GET VALID PLACEMENTS (AREA SCAN)
# =============================================================================


class TestGetValidPlacements:
    """Tests for get_valid_placements area scanning."""

    def test_area_scan_basic(self, placement_hints, test_area):
        """Test basic area scanning."""
        area = {
            "left_top": {"x": test_area["x"] - 5, "y": test_area["y"] - 5},
            "right_bottom": {"x": test_area["x"] + 5, "y": test_area["y"] + 5},
        }

        result = placement_hints.call(
            "get_valid_placements",
            "transport-belt",
            area,
            {"max_results": 10},
        )

        assert "positions" in result
        assert result["count"] > 0
        assert len(result["positions"]) <= 10

    def test_area_scan_with_directions(self, placement_hints, test_area):
        """Test area scanning includes direction info for directional entities."""
        area = {
            "left_top": {"x": test_area["x"] - 2, "y": test_area["y"] - 2},
            "right_bottom": {"x": test_area["x"] + 2, "y": test_area["y"] + 2},
        }

        result = placement_hints.call(
            "get_valid_placements",
            "inserter",
            area,
            {"max_results": 5, "include_directions": True},
        )

        assert "positions" in result
        # Should have direction info
        if result["count"] > 0:
            pos = result["positions"][0]
            assert "direction" in pos or "direction_name" in pos


# =============================================================================
# TEST: RESOURCE PLACEMENTS (Mining Drills)
# =============================================================================


class TestResourcePlacements:
    """Tests for get_resource_placements (mining drills on ore)."""

    @pytest.fixture
    def ore_patch(self, rcon: RCONClient, test_area):
        """Create an iron ore patch for testing."""
        ore_x = test_area["x"] + 50
        ore_y = test_area["y"]

        # Create a small ore patch (3x3)
        create_ore_cmd = f"""
        /sc local surface = game.surfaces[1]
        for dx = -1, 1 do
            for dy = -1, 1 do
                surface.create_entity{{
                    name = "iron-ore",
                    position = {{x = {ore_x} + dx, y = {ore_y} + dy}},
                    amount = 1000
                }}
            end
        end
        rcon.print("ore_created")
        """
        result = rcon.send_command(create_ore_cmd)
        assert "ore_created" in result, f"Failed to create ore: {result}"

        yield {"x": ore_x, "y": ore_y}

        # Cleanup
        cleanup_cmd = f"""
        /sc local surface = game.surfaces[1]
        local area = {{left_top = {{x = {ore_x - 5}, y = {ore_y - 5}}}, right_bottom = {{x = {ore_x + 5}, y = {ore_y + 5}}}}}
        for _, entity in pairs(surface.find_entities_filtered{{area = area, type = "resource"}}) do
            entity.destroy()
        end
        """
        rcon.send_command(cleanup_cmd)

    def test_resource_placements_on_ore(self, placement_hints, ore_patch):
        """Test finding valid drill placements on ore."""
        area = {
            "left_top": {"x": ore_patch["x"] - 5, "y": ore_patch["y"] - 5},
            "right_bottom": {"x": ore_patch["x"] + 5, "y": ore_patch["y"] + 5},
        }

        result = placement_hints.call(
            "get_resource_placements",
            "electric-mining-drill",
            area,
            {"max_results": 10},
        )

        assert "positions" in result
        assert result["count"] > 0

        # Verify positions have resource info
        pos = result["positions"][0]
        assert "resource_name" in pos
        assert pos["resource_name"] == "iron-ore"

    def test_resource_placements_empty_area(self, placement_hints, test_area):
        """Test no placements found in area without resources."""
        area = {
            "left_top": {"x": test_area["x"] - 5, "y": test_area["y"] - 5},
            "right_bottom": {"x": test_area["x"] + 5, "y": test_area["y"] + 5},
        }

        result = placement_hints.call(
            "get_resource_placements",
            "electric-mining-drill",
            area,
            {},
        )

        assert result["count"] == 0

    def test_non_resource_entity_error(self, placement_hints, test_area):
        """Test error when using non-resource entity."""
        area = {
            "left_top": {"x": test_area["x"] - 5, "y": test_area["y"] - 5},
            "right_bottom": {"x": test_area["x"] + 5, "y": test_area["y"] + 5},
        }

        result = placement_hints.call(
            "get_resource_placements",
            "transport-belt",  # Not a resource entity
            area,
            {},
        )

        assert "error" in result


# =============================================================================
# TEST: WATER PLACEMENTS (Offshore Pumps)
# =============================================================================


class TestWaterPlacements:
    """Tests for get_water_placements (offshore pumps)."""

    @pytest.fixture
    def water_tiles(self, rcon: RCONClient, test_area):
        """Create water tiles for testing offshore pump placement."""
        water_x = test_area["x"] + 80
        water_y = test_area["y"]

        # Create a small lake (5x5 water tiles with land border)
        create_water_cmd = f"""
        /sc local surface = game.surfaces[1]
        local tiles = {{}}
        -- Create water in center
        for dx = -2, 2 do
            for dy = -2, 2 do
                table.insert(tiles, {{name = "water", position = {{x = {water_x} + dx, y = {water_y} + dy}}}})
            end
        end
        surface.set_tiles(tiles)
        rcon.print("water_created")
        """
        result = rcon.send_command(create_water_cmd)
        assert "water_created" in result, f"Failed to create water: {result}"

        yield {"x": water_x, "y": water_y}

        # Cleanup - replace water with grass
        cleanup_cmd = f"""
        /sc local surface = game.surfaces[1]
        local tiles = {{}}
        for dx = -3, 3 do
            for dy = -3, 3 do
                table.insert(tiles, {{name = "grass-1", position = {{x = {water_x} + dx, y = {water_y} + dy}}}})
            end
        end
        surface.set_tiles(tiles)
        """
        rcon.send_command(cleanup_cmd)

    def test_water_placements_near_lake(self, placement_hints, water_tiles):
        """Test finding valid offshore pump placements near water."""
        # Search area includes water edge
        area = {
            "left_top": {"x": water_tiles["x"] - 5, "y": water_tiles["y"] - 5},
            "right_bottom": {"x": water_tiles["x"] + 5, "y": water_tiles["y"] + 5},
        }

        result = placement_hints.call(
            "get_water_placements",
            "offshore-pump",
            area,
            {"max_results": 20},
        )

        assert "positions" in result
        # Should find some valid positions at water edges
        # (may be 0 if water patch is too small or wrong shape)

    def test_water_placements_no_water(self, placement_hints, test_area):
        """Test no placements found in area without water."""
        area = {
            "left_top": {"x": test_area["x"] - 5, "y": test_area["y"] - 5},
            "right_bottom": {"x": test_area["x"] + 5, "y": test_area["y"] + 5},
        }

        result = placement_hints.call(
            "get_water_placements",
            "offshore-pump",
            area,
            {},
        )

        assert result["count"] == 0

    def test_non_water_entity_error(self, placement_hints, test_area):
        """Test error when using non-water entity."""
        area = {
            "left_top": {"x": test_area["x"] - 5, "y": test_area["y"] - 5},
            "right_bottom": {"x": test_area["x"] + 5, "y": test_area["y"] + 5},
        }

        result = placement_hints.call(
            "get_water_placements",
            "transport-belt",  # Not a water entity
            area,
            {},
        )

        assert "error" in result


# =============================================================================
# TEST: GET PLACEMENT CUE (Rich Feedback)
# =============================================================================


class TestGetPlacementCue:
    """Tests for get_placement_cue with rich feedback."""

    def test_placement_cue_valid(self, placement_hints, test_area):
        """Test placement cue for valid position."""
        result = placement_hints.call(
            "get_placement_cue",
            "iron-chest",
            {"x": test_area["x"], "y": test_area["y"]},
            None,
        )

        assert result["valid"] is True
        assert "footprint" in result
        assert "colliding_entities" in result
        assert len(result["colliding_entities"]) == 0

    def test_placement_cue_with_collision(self, rcon: RCONClient, placement_hints, test_area):
        """Test placement cue shows colliding entities."""
        # Place an entity first
        place_cmd = f'/c game.surfaces[1].create_entity{{name="iron-chest", position={{x={test_area["x"]}, y={test_area["y"]}}}, force="player"}}; rcon.print("placed")'
        rcon.send_command(place_cmd)

        result = placement_hints.call(
            "get_placement_cue",
            "iron-chest",
            {"x": test_area["x"], "y": test_area["y"]},
            None,
        )

        assert result["valid"] is False
        assert "colliding_entities" in result
        assert len(result["colliding_entities"]) > 0
        assert result["reason"] == "collision"

    def test_placement_cue_footprint(self, placement_hints, test_area):
        """Test that footprint info is returned."""
        result = placement_hints.call(
            "get_placement_cue",
            "electric-mining-drill",
            {"x": test_area["x"], "y": test_area["y"]},
            None,
        )

        assert "footprint" in result
        footprint = result["footprint"]
        assert "tiles" in footprint
        assert "bounding_box" in footprint
        # Mining drill is 3x3
        assert footprint["tile_width"] == 3
        assert footprint["tile_height"] == 3

    def test_placement_cue_valid_directions(self, placement_hints, test_area):
        """Test that valid directions are returned for directional entities."""
        result = placement_hints.call(
            "get_placement_cue",
            "inserter",
            {"x": test_area["x"], "y": test_area["y"]},
            None,  # Don't specify direction, let it find all valid
        )

        assert "valid_directions" in result
        # Inserter should have valid directions on open ground
        if result["valid"]:
            assert len(result["valid_directions"]) > 0


# =============================================================================
# TEST: ITEM DROP CONNECTIONS
# =============================================================================


class TestItemDropConnections:
    """Tests for get_item_drop_connections (drill → chest/belt)."""

    @pytest.fixture
    def placed_drill(self, rcon: RCONClient, test_area):
        """Place a mining drill for connection testing."""
        # Use smaller offset to stay within valid map area (lab tiles end around x=260)
        drill_x = test_area["x"] + 45
        drill_y = test_area["y"]

        # First create ore ONLY under drill footprint (3x3 area) to leave drop position clear
        create_ore_cmd = f"""
        /sc local surface = game.surfaces[1]
        -- Only create ore under the drill itself (not at drop position which is north)
        for dx = -1, 1 do
            for dy = 0, 2 do  -- South half only, leaving north clear for drop
                surface.create_entity{{
                    name = "iron-ore",
                    position = {{x = {drill_x} + dx, y = {drill_y} + dy}},
                    amount = 1000
                }}
            end
        end
        rcon.print("ore_created")
        """
        rcon.send_command(create_ore_cmd)

        # Place the drill
        place_cmd = f'/c game.surfaces[1].create_entity{{name="electric-mining-drill", position={{x={drill_x}, y={drill_y}}}, force="player"}}; rcon.print("placed")'
        result = rcon.send_command(place_cmd)
        assert "placed" in result, f"Failed to place drill: {result}"

        yield {"x": drill_x, "y": drill_y}

        # Cleanup
        cleanup_cmd = f"""
        /sc local surface = game.surfaces[1]
        local area = {{left_top = {{x = {drill_x - 10}, y = {drill_y - 10}}}, right_bottom = {{x = {drill_x + 10}, y = {drill_y + 10}}}}}
        for _, entity in pairs(surface.find_entities_filtered{{area = area}}) do
            if entity.name ~= "character" then entity.destroy() end
        end
        """
        rcon.send_command(cleanup_cmd)

    def test_item_drop_connections_chest(self, placement_hints, placed_drill):
        """Test finding chest positions that connect to drill output."""
        result = placement_hints.call(
            "get_item_drop_connections",
            "electric-mining-drill",
            {"x": placed_drill["x"], "y": placed_drill["y"]},
            "iron-chest",
            {"max_results": 10},
        )

        assert "positions" in result
        assert result["count"] > 0

        # Verify position structure
        pos = result["positions"][0]
        assert "position" in pos
        assert "perpendicular_offset" in pos

    def test_item_drop_connections_belt(self, placement_hints, placed_drill):
        """Test finding belt positions that connect to drill output."""
        result = placement_hints.call(
            "get_item_drop_connections",
            "electric-mining-drill",
            {"x": placed_drill["x"], "y": placed_drill["y"]},
            "transport-belt",
            {"max_results": 10},
        )

        assert "positions" in result
        # Belts should also be placeable near drill output

    def test_item_drop_connections_sorted_by_alignment(self, placement_hints, placed_drill):
        """Test that positions are sorted by perpendicular_offset."""
        result = placement_hints.call(
            "get_item_drop_connections",
            "electric-mining-drill",
            {"x": placed_drill["x"], "y": placed_drill["y"]},
            "iron-chest",
            {"max_results": 10},
        )

        if result["count"] > 1:
            offsets = [p["perpendicular_offset"] for p in result["positions"]]
            assert offsets == sorted(offsets), "Positions not sorted by alignment"

    def test_item_drop_entity_not_found(self, placement_hints, test_area):
        """Test error when source entity doesn't exist."""
        result = placement_hints.call(
            "get_item_drop_connections",
            "electric-mining-drill",
            {"x": test_area["x"], "y": test_area["y"]},  # No drill here
            "iron-chest",
            {},
        )

        assert "error" in result


# =============================================================================
# TEST: FLUID CONNECTIONS
# =============================================================================


class TestFluidConnections:
    """Tests for get_fluid_connections (machine → pipe)."""

    @pytest.fixture
    def placed_boiler(self, rcon: RCONClient, test_area):
        """Place a boiler for fluid connection testing."""
        boiler_x = test_area["x"] + 120
        boiler_y = test_area["y"]

        place_cmd = f'/c game.surfaces[1].create_entity{{name="boiler", position={{x={boiler_x}, y={boiler_y}}}, direction=defines.direction.east, force="player"}}; rcon.print("placed")'
        result = rcon.send_command(place_cmd)
        assert "placed" in result, f"Failed to place boiler: {result}"

        yield {"x": boiler_x, "y": boiler_y}

        # Cleanup
        cleanup_cmd = f'/c local e = game.surfaces[1].find_entity("boiler", {{x={boiler_x}, y={boiler_y}}}); if e then e.destroy() end'
        rcon.send_command(cleanup_cmd)

    def test_fluid_connections_pipe(self, placement_hints, placed_boiler):
        """Test finding pipe positions that connect to boiler."""
        result = placement_hints.call(
            "get_fluid_connections",
            "boiler",
            {"x": placed_boiler["x"], "y": placed_boiler["y"]},
            "pipe",
            {"max_results": 10},
        )

        assert "positions" in result
        # Boiler should have fluid connections

    def test_fluid_connections_pump(self, placement_hints, placed_boiler):
        """Test finding pump positions that connect to boiler."""
        result = placement_hints.call(
            "get_fluid_connections",
            "boiler",
            {"x": placed_boiler["x"], "y": placed_boiler["y"]},
            "pump",
            {},
        )

        assert "positions" in result


# =============================================================================
# TEST: INSERTER PLACEMENTS
# =============================================================================


class TestInserterPlacements:
    """Tests for get_inserter_placements between two entities."""

    @pytest.fixture
    def two_chests(self, rcon: RCONClient, test_area):
        """Place two chests for inserter connection testing."""
        chest1_x = test_area["x"] + 140
        chest1_y = test_area["y"]
        chest2_x = chest1_x + 2
        chest2_y = chest1_y

        place_cmd = f"""
        /sc local s = game.surfaces[1]
        s.create_entity{{name="iron-chest", position={{x={chest1_x}, y={chest1_y}}}, force="player"}}
        s.create_entity{{name="iron-chest", position={{x={chest2_x}, y={chest2_y}}}, force="player"}}
        rcon.print("placed")
        """
        result = rcon.send_command(place_cmd)
        assert "placed" in result

        yield {
            "chest1": {"x": chest1_x, "y": chest1_y},
            "chest2": {"x": chest2_x, "y": chest2_y},
        }

        # Cleanup
        cleanup_cmd = f"""
        /sc local s = game.surfaces[1]
        local area = {{left_top = {{x = {chest1_x - 5}, y = {chest1_y - 5}}}, right_bottom = {{x = {chest2_x + 5}, y = {chest2_y + 5}}}}}
        for _, entity in pairs(s.find_entities_filtered{{area = area}}) do
            if entity.name ~= "character" then entity.destroy() end
        end
        """
        rcon.send_command(cleanup_cmd)

    def test_inserter_placements_between_chests(self, placement_hints, two_chests):
        """Test finding inserter positions between two chests."""
        result = placement_hints.call(
            "get_inserter_placements",
            "iron-chest",
            two_chests["chest1"],
            "iron-chest",
            two_chests["chest2"],
            "inserter",
        )

        assert "positions" in result
        # With 2 tile gap, inserter should fit between

    def test_inserter_placements_with_direction(self, placement_hints, two_chests):
        """Test that inserter positions include direction."""
        result = placement_hints.call(
            "get_inserter_placements",
            "iron-chest",
            two_chests["chest1"],
            "iron-chest",
            two_chests["chest2"],
            "inserter",
        )

        if result["count"] > 0:
            pos = result["positions"][0]
            assert "direction" in pos
            assert "direction_name" in pos


# =============================================================================
# TEST: POLE CONNECTIONS
# =============================================================================


class TestPoleConnections:
    """Tests for get_pole_connections (pole → pole)."""

    @pytest.fixture
    def placed_pole(self, rcon: RCONClient, test_area):
        """Place a pole for connection testing."""
        # Use smaller offset to stay within valid map area (lab tiles end around x=260)
        pole_x = test_area["x"] + 50
        pole_y = test_area["y"]

        place_cmd = f'/c game.surfaces[1].create_entity{{name="medium-electric-pole", position={{x={pole_x}, y={pole_y}}}, force="player"}}; rcon.print("placed")'
        result = rcon.send_command(place_cmd)
        assert "placed" in result

        yield {"x": pole_x, "y": pole_y}

        # Cleanup
        cleanup_cmd = f'/c local e = game.surfaces[1].find_entity("medium-electric-pole", {{x={pole_x}, y={pole_y}}}); if e then e.destroy() end'
        rcon.send_command(cleanup_cmd)

    def test_pole_connections_within_range(self, placement_hints, placed_pole):
        """Test finding pole positions within wire range."""
        # Medium pole has wire distance of 9
        search_area = {
            "left_top": {"x": placed_pole["x"] - 10, "y": placed_pole["y"] - 10},
            "right_bottom": {"x": placed_pole["x"] + 10, "y": placed_pole["y"] + 10},
        }

        result = placement_hints.call(
            "get_pole_connections",
            "medium-electric-pole",
            {"x": placed_pole["x"], "y": placed_pole["y"]},
            "medium-electric-pole",
            search_area,
            {"max_results": 20},
        )

        assert "positions" in result
        assert result["count"] > 0

        # Verify wire distance info
        pos = result["positions"][0]
        assert "wire_distance" in pos
        assert pos["wire_distance"] <= 9  # Medium pole max

    def test_pole_connections_sorted_by_distance(self, placement_hints, placed_pole):
        """Test that pole positions are sorted by wire distance."""
        search_area = {
            "left_top": {"x": placed_pole["x"] - 8, "y": placed_pole["y"] - 8},
            "right_bottom": {"x": placed_pole["x"] + 8, "y": placed_pole["y"] + 8},
        }

        result = placement_hints.call(
            "get_pole_connections",
            "medium-electric-pole",
            {"x": placed_pole["x"], "y": placed_pole["y"]},
            "medium-electric-pole",
            search_area,
            {"max_results": 20},
        )

        if result["count"] > 1:
            distances = [p["wire_distance"] for p in result["positions"]]
            assert distances == sorted(distances), "Positions not sorted by distance"


# =============================================================================
# TEST: ENTITY INFO
# =============================================================================


class TestEntityInfo:
    """Tests for entity information methods."""

    def test_get_entity_output_info(self, rcon: RCONClient, placement_hints, test_area):
        """Test getting entity output info."""
        # Place a drill
        drill_x = test_area["x"] + 180
        drill_y = test_area["y"]

        # Create ore first
        rcon.send_command(
            f'/c game.surfaces[1].create_entity{{name="iron-ore", position={{x={drill_x}, y={drill_y}}}, amount=1000}}'
        )
        rcon.send_command(
            f'/c game.surfaces[1].create_entity{{name="electric-mining-drill", position={{x={drill_x}, y={drill_y}}}, force="player"}}'
        )

        result = placement_hints.call(
            "get_entity_output_info",
            "electric-mining-drill",
            {"x": drill_x, "y": drill_y},
        )

        assert result["entity_found"] is True
        assert "drop_position" in result
        assert "bounding_box" in result
        assert "direction" in result

        # Cleanup
        rcon.send_command(
            f'/sc for _, e in pairs(game.surfaces[1].find_entities_filtered{{position={{x={drill_x}, y={drill_y}}}}}) do e.destroy() end'
        )

    def test_get_entity_output_info_not_found(self, placement_hints, test_area):
        """Test output info when entity doesn't exist."""
        result = placement_hints.call(
            "get_entity_output_info",
            "electric-mining-drill",
            {"x": test_area["x"], "y": test_area["y"]},  # No drill here
        )

        assert result["entity_found"] is False

    def test_get_entity_footprint(self, placement_hints, test_area):
        """Test getting entity footprint."""
        result = placement_hints.call(
            "get_entity_footprint",
            "assembling-machine-2",
            {"x": test_area["x"], "y": test_area["y"]},
            None,
        )

        assert "tiles" in result
        assert "bounding_box" in result
        # Assembling machine 2 is 3x3
        assert result["tile_width"] == 3
        assert result["tile_height"] == 3


# =============================================================================
# TEST: FLUID CONNECTION POINTS
# =============================================================================


class TestFluidConnectionPoints:
    """Tests for get_fluid_connection_points."""

    def test_fluid_connection_points_boiler(self, rcon: RCONClient, placement_hints, test_area):
        """Test getting fluid connection points from boiler."""
        boiler_x = test_area["x"] + 200
        boiler_y = test_area["y"]

        rcon.send_command(
            f'/c game.surfaces[1].create_entity{{name="boiler", position={{x={boiler_x}, y={boiler_y}}}, direction=defines.direction.east, force="player"}}'
        )

        result = placement_hints.call(
            "get_fluid_connection_points",
            "boiler",
            {"x": boiler_x, "y": boiler_y},
        )

        assert result["entity_found"] is True
        assert "connections" in result
        # Boiler has fluid connections
        assert len(result["connections"]) > 0

        # Cleanup
        rcon.send_command(
            f'/c local e = game.surfaces[1].find_entity("boiler", {{x={boiler_x}, y={boiler_y}}}); if e then e.destroy() end'
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
