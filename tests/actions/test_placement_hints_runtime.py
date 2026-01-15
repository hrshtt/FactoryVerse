"""Runtime tests for the placement_hints module.

These tests run against a live Factorio server (test-ground scenario) to
validate the PlacementValidator and PlacementHints against real game state.

Tests cover:
- PlacementValidator.validate_placement: Single position validation
- PlacementValidator.validate_batch: Multiple position validation
- PlacementValidator.validate_line: Line position validation
- PlacementValidator.validate_grid: Grid position validation
- PlacementHints.get_placement_line: Belt/pipe line generation
- GhostPlan.validate: Plan re-validation after map changes

Requirements:
- Factorio server running with test-ground scenario
- RCON port 27100 (or configured port)
"""

import pytest
from factorio_rcon import RCONClient

from FactoryVerse.agent.actions.placement_hints import (
    PlacementValidator,
    PlacementHints,
    GhostPlan,
    ConnectionType,
)
from FactoryVerse.agent.infra.rcon_handler import RconHandler
from FactoryVerse.factory.types import MapPosition, Direction


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(scope="module")
def rcon_client():
    """Create RCON client connected to test server.

    Uses port 27100 for test-ground scenario.
    """
    client = RCONClient("localhost", 27100, "factorio")
    yield client


@pytest.fixture(scope="module")
def rcon_handler(rcon_client):
    """Create RconHandler with a dummy agent ID for validation.

    PlacementValidator only uses rcon.execute(), not agent-specific methods.
    """
    return RconHandler(rcon_client, agent_id="test_validator")


@pytest.fixture(scope="module")
def validator(rcon_handler):
    """Create PlacementValidator instance."""
    return PlacementValidator(rcon_handler)


@pytest.fixture(scope="module")
def hints(rcon_handler):
    """Create PlacementHints instance."""
    return PlacementHints(rcon_handler)


@pytest.fixture(scope="function")
def clean_test_position(rcon_client):
    """Get a clean position for testing and clear it afterwards.

    Uses a randomized offset from 100,100 to avoid collisions.
    """
    import random

    base_x = 100 + random.randint(0, 50)
    base_y = 100 + random.randint(0, 50)

    # Clear area before test
    clear_cmd = f"""
    /sc local surface = game.surfaces[1]
    local area = {{left_top = {{x = {base_x - 10}, y = {base_y - 10}}}, right_bottom = {{x = {base_x + 20}, y = {base_y + 20}}}}}
    for _, entity in pairs(surface.find_entities_filtered{{area = area}}) do
        if entity.name ~= "character" then entity.destroy() end
    end
    """
    rcon_client.send_command(clear_cmd)

    yield MapPosition(x=float(base_x), y=float(base_y))

    # Clear area after test
    rcon_client.send_command(clear_cmd)


@pytest.fixture(scope="function")
def clear_line_area(rcon_client):
    """Clear a horizontal area for belt line tests."""
    base_x = 50
    base_y = 50
    length = 20

    # Clear larger area for line tests
    clear_cmd = f"""
    /sc local surface = game.surfaces[1]
    local area = {{left_top = {{x = {base_x - 2}, y = {base_y - 2}}}, right_bottom = {{x = {base_x + length + 2}, y = {base_y + 2}}}}}
    for _, entity in pairs(surface.find_entities_filtered{{area = area}}) do
        if entity.name ~= "character" then entity.destroy() end
    end
    """
    rcon_client.send_command(clear_cmd)

    yield {
        "start": MapPosition(x=float(base_x), y=float(base_y)),
        "end": MapPosition(x=float(base_x + length), y=float(base_y)),
        "length": length + 1,  # Inclusive
    }

    # Cleanup
    rcon_client.send_command(clear_cmd)


# =============================================================================
# PLACEMENTVALIDATOR TESTS
# =============================================================================


class TestPlacementValidatorRuntime:
    """Runtime tests for PlacementValidator against actual game state."""

    def test_validate_placement_empty_position(self, validator, clean_test_position):
        """Test validation returns True for empty, valid position."""
        result = validator.validate_placement(
            "transport-belt", clean_test_position, direction=Direction.EAST, ghost=True
        )

        assert result is True, "Empty position should be valid for belt placement"

    def test_validate_placement_with_collision(
        self, validator, clean_test_position, rcon_client
    ):
        """Test validation returns False when position has an entity."""
        # Place a chest at the position first
        place_cmd = f"""
        /sc local surface = game.surfaces[1]
        surface.create_entity{{
            name = "iron-chest",
            position = {{x = {clean_test_position.x}, y = {clean_test_position.y}}},
            force = "player"
        }}
        """
        rcon_client.send_command(place_cmd)

        # Now validate - should fail
        result = validator.validate_placement(
            "transport-belt", clean_test_position, direction=Direction.EAST, ghost=True
        )

        assert result is False, "Position with existing entity should be invalid"

    def test_validate_placement_different_entity_types(
        self, validator, clean_test_position
    ):
        """Test validation works for different entity types."""
        entities_to_test = [
            ("transport-belt", Direction.EAST),
            ("iron-chest", None),
            ("small-electric-pole", None),
            ("inserter", Direction.NORTH),
            ("pipe", None),
        ]

        for entity_name, direction in entities_to_test:
            result = validator.validate_placement(
                entity_name, clean_test_position, direction=direction, ghost=True
            )
            assert result is True, (
                f"{entity_name} should be placeable on empty position"
            )

    def test_validate_placement_ghost_vs_real(self, validator, clean_test_position):
        """Test difference between ghost and real entity validation."""
        # Both should pass on empty position
        ghost_result = validator.validate_placement(
            "transport-belt", clean_test_position, direction=Direction.EAST, ghost=True
        )

        real_result = validator.validate_placement(
            "transport-belt", clean_test_position, direction=Direction.EAST, ghost=False
        )

        assert ghost_result is True
        # Real placement might differ based on player reach, but position should be valid
        # Note: manual build_check_type doesn't require player reach
        assert real_result is True


class TestBatchValidationRuntime:
    """Runtime tests for batch validation."""

    def test_validate_batch_all_valid(self, validator, clear_line_area):
        """Test batch validation with all valid positions."""
        start = clear_line_area["start"]

        # Create 5 positions in a row
        positions = [MapPosition(x=start.x + i, y=start.y) for i in range(5)]

        results = validator.validate_batch(
            "transport-belt", positions, directions=[Direction.EAST] * 5, ghost=True
        )

        assert len(results) == 5, "Should return 5 results"
        assert all(results), "All positions should be valid"

    def test_validate_batch_mixed_results(
        self, validator, clear_line_area, rcon_client
    ):
        """Test batch validation with some blocked positions."""
        start = clear_line_area["start"]

        # Place an obstacle at position 2
        obstacle_x = start.x + 2
        place_cmd = f"""
        /sc game.surfaces[1].create_entity{{
            name = "stone-wall",
            position = {{x = {obstacle_x}, y = {start.y}}},
            force = "player"
        }}
        """
        rcon_client.send_command(place_cmd)

        # Create 5 positions in a row
        positions = [MapPosition(x=start.x + i, y=start.y) for i in range(5)]

        results = validator.validate_batch(
            "transport-belt", positions, directions=[Direction.EAST] * 5, ghost=True
        )

        assert len(results) == 5
        # Position at index 2 should be blocked
        assert results[0] is True, "Position 0 should be valid"
        assert results[1] is True, "Position 1 should be valid"
        assert results[2] is False, "Position 2 should be blocked by wall"
        assert results[3] is True, "Position 3 should be valid"
        assert results[4] is True, "Position 4 should be valid"

    def test_validate_batch_empty_list(self, validator):
        """Test batch validation with empty list returns empty list."""
        results = validator.validate_batch("transport-belt", [], ghost=True)
        assert results == []

    def test_validate_batch_large_batch(self, validator, clear_line_area):
        """Test batch validation with larger number of positions."""
        start = clear_line_area["start"]

        # Create 15 positions
        positions = [MapPosition(x=start.x + i, y=start.y) for i in range(15)]

        results = validator.validate_batch(
            "transport-belt", positions, directions=[Direction.EAST] * 15, ghost=True
        )

        assert len(results) == 15, "Should return 15 results"


class TestLineValidationRuntime:
    """Runtime tests for line validation."""

    def test_validate_line_horizontal(self, validator, clear_line_area):
        """Test line validation for horizontal line."""
        start = clear_line_area["start"]
        end = MapPosition(x=start.x + 5, y=start.y)

        results = validator.validate_line(
            "transport-belt", start, end, direction=Direction.EAST, ghost=True
        )

        assert len(results) == 6, (
            "Should include start and end positions (0..5 = 6 positions)"
        )

        # Each result should be (position, can_place)
        for pos, can_place in results:
            assert isinstance(pos, MapPosition)
            assert can_place is True

    def test_validate_line_vertical(self, validator, clean_test_position, rcon_client):
        """Test line validation for vertical line."""
        start = clean_test_position
        end = MapPosition(x=start.x, y=start.y + 4)

        # Clear area for vertical line
        clear_cmd = f"""
        /sc local surface = game.surfaces[1]
        local area = {{left_top = {{x = {start.x - 2}, y = {start.y - 2}}}, right_bottom = {{x = {start.x + 2}, y = {end.y + 2}}}}}
        for _, entity in pairs(surface.find_entities_filtered{{area = area}}) do
            if entity.name ~= "character" then entity.destroy() end
        end
        """
        rcon_client.send_command(clear_cmd)

        results = validator.validate_line("pipe", start, end, ghost=True)

        assert len(results) == 5, "Vertical line should have 5 positions"
        assert all(can_place for _, can_place in results)


class TestGridValidationRuntime:
    """Runtime tests for grid validation."""

    def test_validate_grid_small(self, validator, clean_test_position, rcon_client):
        """Test grid validation for small 3x3 area."""
        # Clear a 5x5 area for the grid test
        clear_cmd = f"""
        /sc local surface = game.surfaces[1]
        local area = {{left_top = {{x = {clean_test_position.x - 1}, y = {clean_test_position.y - 1}}}, right_bottom = {{x = {clean_test_position.x + 4}, y = {clean_test_position.y + 4}}}}}
        for _, entity in pairs(surface.find_entities_filtered{{area = area}}) do
            if entity.name ~= "character" then entity.destroy() end
        end
        """
        rcon_client.send_command(clear_cmd)

        top_left = clean_test_position
        bottom_right = MapPosition(
            x=clean_test_position.x + 2, y=clean_test_position.y + 2
        )

        results = validator.validate_grid(
            "transport-belt",
            top_left,
            bottom_right,
            direction=Direction.EAST,
            ghost=True,
        )

        # 3x3 grid should have 9 results
        assert len(results) == 9, f"3x3 grid should have 9 results, got {len(results)}"
        assert all(can_place for can_place in results.values()), (
            "All positions should be valid"
        )


# =============================================================================
# PLACEMENTHINTS TESTS
# =============================================================================


class TestPlacementHintsRuntime:
    """Runtime tests for PlacementHints."""

    def test_get_placement_line_belt_horizontal(self, hints, clear_line_area):
        """Test generating a horizontal belt line."""
        start = clear_line_area["start"]
        end = MapPosition(x=start.x + 4, y=start.y)

        plan = hints.get_placement_line("transport-belt", start, end, validate=True)

        assert plan.entity_name == "transport-belt"
        assert len(plan.positions) == 5, "Line should have 5 positions"
        assert plan.valid is True, "Plan should be valid on empty area"

        # All belts should face EAST
        for pos, direction in plan.positions:
            assert direction == Direction.EAST
            assert pos.y == start.y

    def test_get_placement_line_belt_vertical(
        self, hints, clean_test_position, rcon_client
    ):
        """Test generating a vertical belt line (facing south)."""
        start = clean_test_position
        end = MapPosition(x=start.x, y=start.y + 4)

        # Clear area
        clear_cmd = f"""
        /sc local surface = game.surfaces[1]
        local area = {{left_top = {{x = {start.x - 2}, y = {start.y - 2}}}, right_bottom = {{x = {start.x + 2}, y = {end.y + 2}}}}}
        for _, entity in pairs(surface.find_entities_filtered{{area = area}}) do
            if entity.name ~= "character" then entity.destroy() end
        end
        """
        rcon_client.send_command(clear_cmd)

        plan = hints.get_placement_line("transport-belt", start, end, validate=True)

        assert plan.valid is True
        assert len(plan.positions) == 5

        # All belts should face SOUTH (positive y direction)
        for pos, direction in plan.positions:
            assert direction == Direction.SOUTH
            assert pos.x == start.x

    def test_get_placement_line_pipe(self, hints, clear_line_area):
        """Test generating a pipe line (non-directional entity)."""
        start = clear_line_area["start"]
        end = MapPosition(x=start.x + 3, y=start.y)

        plan = hints.get_placement_line("pipe", start, end, validate=True)

        assert plan.entity_name == "pipe"
        assert len(plan.positions) == 4
        assert plan.valid is True

        # Pipes are non-directional (direction can be None or inferred)
        # The module marks pipes as non-directional
        for pos, _ in plan.positions:
            assert pos.y == start.y

    def test_get_placement_line_invalid_with_obstacle(
        self, hints, clear_line_area, rcon_client
    ):
        """Test that plan validation fails when there's an obstacle."""
        start = clear_line_area["start"]
        end = MapPosition(x=start.x + 5, y=start.y)

        # Place obstacle in the middle
        obstacle_x = start.x + 2
        place_cmd = f"""
        /sc game.surfaces[1].create_entity{{
            name = "iron-chest",
            position = {{x = {obstacle_x}, y = {start.y}}},
            force = "player"
        }}
        """
        rcon_client.send_command(place_cmd)

        plan = hints.get_placement_line("transport-belt", start, end, validate=True)

        # Plan should be marked invalid because one position is blocked
        assert plan.valid is False, "Plan should be invalid with obstacle"

    def test_get_placement_line_no_validation(self, hints, clear_line_area):
        """Test generating line without validation (skip RCON call)."""
        start = clear_line_area["start"]
        end = MapPosition(x=start.x + 3, y=start.y)

        plan = hints.get_placement_line("transport-belt", start, end, validate=False)

        # Should still have positions, marked as valid (assumed)
        assert len(plan.positions) == 4
        assert plan.valid is True  # Assumed valid when validation skipped

    def test_label_uniqueness(self, hints, clear_line_area):
        """Test that plan labels are unique."""
        start = clear_line_area["start"]
        end = MapPosition(x=start.x + 2, y=start.y)

        plan1 = hints.get_placement_line("transport-belt", start, end, validate=False)
        plan2 = hints.get_placement_line("transport-belt", start, end, validate=False)

        assert plan1.label != plan2.label, "Labels should be unique"
        assert "transport-belt" in plan1.label
        assert "line" in plan1.label


# =============================================================================
# GHOSTPLAN TESTS
# =============================================================================


class TestGhostPlanRuntime:
    """Runtime tests for GhostPlan validation."""

    def test_plan_revalidation_after_obstacle_placed(
        self, hints, validator, clear_line_area, rcon_client
    ):
        """Test that plan.validate() returns False after obstacle is placed."""
        start = clear_line_area["start"]
        end = MapPosition(x=start.x + 4, y=start.y)

        # Create valid plan
        plan = hints.get_placement_line("transport-belt", start, end, validate=True)

        assert plan.valid is True, "Initial plan should be valid"

        # Place obstacle after plan creation
        obstacle_x = start.x + 2
        place_cmd = f"""
        /sc game.surfaces[1].create_entity{{
            name = "stone-wall",
            position = {{x = {obstacle_x}, y = {start.y}}},
            force = "player"
        }}
        """
        rcon_client.send_command(place_cmd)

        # Re-validate - should now fail
        result = plan.validate(validator)

        assert result is False, "Plan should be invalid after obstacle placed"
        assert plan.valid is False, "Plan.valid should be updated"

    def test_plan_revalidation_success(
        self, hints, validator, clear_line_area, rcon_client
    ):
        """Test that plan.validate() returns True when area is still clear."""
        start = clear_line_area["start"]
        end = MapPosition(x=start.x + 3, y=start.y)

        # Create valid plan
        plan = hints.get_placement_line("transport-belt", start, end, validate=True)

        assert plan.valid is True

        # Re-validate without changes
        result = plan.validate(validator)

        assert result is True, "Plan should still be valid"
        assert plan.valid is True


# =============================================================================
# INTEGRATION: GHOST PLACEMENT TESTS
# =============================================================================


class TestGhostPlacementIntegration:
    """Integration tests for placing ghosts from validated plans."""

    @pytest.fixture
    def agent_context(self, rcon_client):
        """Create agent and get agent interface name.

        Returns:
            Tuple of (agent_id, RconHandler)
        """
        # Create agent for placement
        from tests.helpers.server import RconConnection

        rcon_conn = RconConnection(rcon_client)
        result = rcon_conn.call(
            "agent", "create_agent", 34202, True, False, "player", {}
        )
        interface_name = result["interface_name"]

        handler = RconHandler(rcon_client, interface_name)

        yield interface_name, handler

        # Cleanup
        rcon_conn.call("agent", "destroy_agents")

    def test_place_ghost_from_plan(
        self, hints, clear_line_area, rcon_client, agent_context
    ):
        """Test placing a single ghost entity at a validated position."""
        agent_id, handler = agent_context

        start = clear_line_area["start"]

        # Create a simple single-position plan
        plan = hints.get_placement_line(
            "transport-belt",
            start,
            start,  # Single position
            validate=True,
        )

        assert plan.valid
        assert len(plan.positions) == 1

        # Place ghost using RCON directly (simulating what GhostBuilder does)
        pos, direction = plan.positions[0]
        place_cmd = f"""
        /sc local result = remote.call('{agent_id}', 'place_entity', 
            'transport-belt', 
            {{x = {pos.x}, y = {pos.y}}}, 
            {direction.value if direction else "nil"},
            true,  -- ghost
            '{plan.label}'  -- label
        )
        rcon.print(helpers.table_to_json(result))
        """
        result = rcon_client.send_command(place_cmd)

        # Verify ghost was placed by checking game state
        check_cmd = f"""
        /sc local surface = game.surfaces[1]
        local ghosts = surface.find_entities_filtered{{
            ghost_name = "transport-belt",
            position = {{x = {pos.x}, y = {pos.y}}},
            radius = 1
        }}
        rcon.print(#ghosts)
        """
        ghost_count = rcon_client.send_command(check_cmd)

        assert ghost_count.strip() == "1", f"Expected 1 ghost, got {ghost_count}"

    def test_place_line_of_ghosts(
        self, hints, clear_line_area, rcon_client, agent_context
    ):
        """Test placing a line of ghost belts from a validated plan."""
        agent_id, handler = agent_context

        start = clear_line_area["start"]
        end = MapPosition(x=start.x + 4, y=start.y)

        # Create line plan
        plan = hints.get_placement_line("transport-belt", start, end, validate=True)

        assert plan.valid
        assert len(plan.positions) == 5

        # Place all ghosts
        placed_count = 0
        for pos, direction in plan.positions:
            place_cmd = f"""
            /sc local result = remote.call('{agent_id}', 'place_entity', 
                'transport-belt', 
                {{x = {pos.x}, y = {pos.y}}}, 
                {direction.value if direction else "nil"},
                true,
                '{plan.label}'
            )
            rcon.print(helpers.table_to_json(result))
            """
            result = rcon_client.send_command(place_cmd)
            if "success" in result and "true" in result.lower():
                placed_count += 1

        # Verify all ghosts were placed
        check_cmd = f"""
        /sc local surface = game.surfaces[1]
        local area = {{
            left_top = {{x = {start.x - 0.5}, y = {start.y - 0.5}}},
            right_bottom = {{x = {end.x + 0.5}, y = {end.y + 0.5}}}
        }}
        local ghosts = surface.find_entities_filtered{{
            ghost_name = "transport-belt",
            area = area
        }}
        rcon.print(#ghosts)
        """
        ghost_count = rcon_client.send_command(check_cmd)

        # All 5 should be placed
        assert ghost_count.strip() == "5", f"Expected 5 ghosts, got {ghost_count}"


# =============================================================================
# EDGE CASES AND ERROR HANDLING
# =============================================================================


class TestEdgeCases:
    """Edge case and error handling tests."""

    def test_validate_invalid_entity_name(self, validator, clean_test_position):
        """Test validation with non-existent entity name."""
        result = validator.validate_placement(
            "not-a-real-entity", clean_test_position, ghost=True
        )

        # Should return False (can't place non-existent entity)
        assert result is False

    def test_validate_batch_mismatched_directions(self, validator, clear_line_area):
        """Test that batch validation raises on mismatched directions length."""
        start = clear_line_area["start"]
        positions = [MapPosition(x=start.x + i, y=start.y) for i in range(5)]

        # Provide wrong number of directions
        with pytest.raises(ValueError, match="must match positions list length"):
            validator.validate_batch(
                "transport-belt",
                positions,
                directions=[Direction.EAST] * 3,  # Only 3, but 5 positions
                ghost=True,
            )

    def test_placement_line_direction_inference(
        self, hints, clean_test_position, rcon_client
    ):
        """Test that line direction is correctly inferred from vector."""
        # Clear area
        clear_cmd = f"""
        /sc local surface = game.surfaces[1]
        local area = {{left_top = {{x = {clean_test_position.x - 10}, y = {clean_test_position.y - 10}}}, right_bottom = {{x = {clean_test_position.x + 10}, y = {clean_test_position.y + 10}}}}}
        for _, entity in pairs(surface.find_entities_filtered{{area = area}}) do
            if entity.name ~= "character" then entity.destroy() end
        end
        """
        rcon_client.send_command(clear_cmd)

        # Test WEST direction (negative x)
        start = MapPosition(x=clean_test_position.x + 5, y=clean_test_position.y)
        end = MapPosition(x=clean_test_position.x, y=clean_test_position.y)

        plan = hints.get_placement_line(
            "transport-belt",
            start,
            end,
            validate=False,  # Skip validation for direction test
        )

        # Belt should face WEST (going from +x to -x)
        for _, direction in plan.positions:
            assert direction == Direction.WEST

        # Test NORTH direction (negative y)
        start = MapPosition(x=clean_test_position.x, y=clean_test_position.y + 5)
        end = MapPosition(x=clean_test_position.x, y=clean_test_position.y)

        plan = hints.get_placement_line("transport-belt", start, end, validate=False)

        # Belt should face NORTH
        for _, direction in plan.positions:
            assert direction == Direction.NORTH


# =============================================================================
# PERFORMANCE TESTS
# =============================================================================


class TestPerformance:
    """Performance tests for batch validation."""

    @pytest.mark.slow
    def test_large_batch_validation_performance(self, validator, rcon_client):
        """Test that batch validation handles 100+ positions efficiently."""
        import time

        # Clear large area
        clear_cmd = """
        /sc local surface = game.surfaces[1]
        local area = {left_top = {x = 200, y = 200}, right_bottom = {x = 250, y = 210}}
        for _, entity in pairs(surface.find_entities_filtered{area = area}) do
            if entity.name ~= "character" then entity.destroy() end
        end
        """
        rcon_client.send_command(clear_cmd)

        # Create 100 positions (10x10 grid conceptually, but as a long line)
        positions = [MapPosition(x=200.0 + i, y=200.0) for i in range(100)]

        start_time = time.time()
        results = validator.validate_batch(
            "transport-belt", positions, directions=[Direction.EAST] * 100, ghost=True
        )
        elapsed = time.time() - start_time

        assert len(results) == 100
        print(f"\nBatch validation of 100 positions took {elapsed:.3f}s")

        # Should complete in reasonable time (< 5s even with RCON overhead)
        assert elapsed < 5.0, f"Batch validation took too long: {elapsed}s"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
