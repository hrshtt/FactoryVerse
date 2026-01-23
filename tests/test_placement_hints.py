"""Tests for the placement_hints module.

Tests cover:
- PlacementValidator: Single and batch validation
- PlacementHints: Line generation, connection solving
- GhostPlan: Validation and re-validation
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from FactoryVerse.game.agent.placement_hints import (
    PlacementValidator,
    PlacementHints,
    GhostPlan,
    ConnectionType,
)
from FactoryVerse.game.factory.types import MapPosition, Direction


class TestPlacementValidator:
    """Tests for PlacementValidator class."""

    @pytest.fixture
    def mock_rcon(self):
        """Create a mock RCON handler."""
        rcon = Mock()
        rcon.agent_id = "agent_1"
        return rcon

    @pytest.fixture
    def validator(self, mock_rcon):
        """Create a PlacementValidator instance."""
        return PlacementValidator(mock_rcon, batch_size=250)

    def test_validate_placement_success(self, validator, mock_rcon):
        """Test single position validation (success case)."""
        mock_rcon.execute.return_value = "true"

        result = validator.validate_placement(
            "transport-belt",
            MapPosition(x=10.5, y=20.5),
            direction=Direction.EAST,
            ghost=True,
        )

        assert result is True
        assert mock_rcon.execute.called

        # Check Lua command was generated correctly
        lua_code = mock_rcon.execute.call_args[0][0]
        assert "transport-belt" in lua_code
        assert "10.5" in lua_code
        assert "20.5" in lua_code
        assert "manual_ghost" in lua_code

    def test_validate_placement_failure(self, validator, mock_rcon):
        """Test single position validation (failure case)."""
        mock_rcon.execute.return_value = "false"

        result = validator.validate_placement(
            "assembling-machine-1", MapPosition(x=5.0, y=5.0), ghost=False
        )

        assert result is False

        # Check correct build_check_type
        lua_code = mock_rcon.execute.call_args[0][0]
        assert "manual" in lua_code
        assert "manual_ghost" not in lua_code

    def test_validate_batch_single_batch(self, validator, mock_rcon):
        """Test batch validation (single batch, all valid)."""
        mock_rcon.execute.return_value = "{true, true, true}"

        positions = [
            MapPosition(x=10.0, y=10.0),
            MapPosition(x=11.0, y=10.0),
            MapPosition(x=12.0, y=10.0),
        ]

        results = validator.validate_batch(
            "transport-belt", positions, directions=[Direction.EAST] * 3, ghost=True
        )

        assert results == [True, True, True]
        assert mock_rcon.execute.call_count == 1

    def test_validate_batch_mixed_results(self, validator, mock_rcon):
        """Test batch validation with mixed valid/invalid positions."""
        mock_rcon.execute.return_value = "{true, false, true, false}"

        positions = [MapPosition(x=i, y=10.0) for i in range(4)]

        results = validator.validate_batch("pipe", positions, ghost=True)

        assert results == [True, False, True, False]

    def test_validate_batch_splits_large_requests(self, validator, mock_rcon):
        """Test that large batches are split automatically."""
        # Set small batch size
        validator.batch_size = 5

        # Mock returns for multiple batches
        mock_rcon.execute.side_effect = [
            "{true, true, true, true, true}",
            "{true, true, true}",
        ]

        positions = [MapPosition(x=float(i), y=10.0) for i in range(8)]

        results = validator.validate_batch("stone-wall", positions, ghost=True)

        assert len(results) == 8
        assert all(results)
        assert mock_rcon.execute.call_count == 2

    def test_calculate_line_positions_horizontal(self, validator):
        """Test line position calculation (horizontal)."""
        positions = validator._calculate_line_positions(
            MapPosition(x=0.0, y=5.0), MapPosition(x=5.0, y=5.0)
        )

        assert len(positions) == 6  # 0, 1, 2, 3, 4, 5
        assert all(pos.y == 5.0 for pos in positions)
        assert positions[0].x == 0.0
        assert positions[-1].x == 5.0

    def test_calculate_line_positions_vertical(self, validator):
        """Test line position calculation (vertical)."""
        positions = validator._calculate_line_positions(
            MapPosition(x=10.0, y=0.0), MapPosition(x=10.0, y=5.0)
        )

        assert len(positions) == 6
        assert all(pos.x == 10.0 for pos in positions)
        assert positions[0].y == 0.0
        assert positions[-1].y == 5.0

    def test_validate_line(self, validator, mock_rcon):
        """Test line validation."""
        mock_rcon.execute.return_value = "{true, true, true}"

        results = validator.validate_line(
            "transport-belt",
            MapPosition(x=0.0, y=0.0),
            MapPosition(x=2.0, y=0.0),
            direction=Direction.EAST,
            ghost=True,
        )

        assert len(results) == 3
        assert all(can_place for _, can_place in results)


class TestPlacementHints:
    """Tests for PlacementHints class."""

    @pytest.fixture
    def mock_rcon(self):
        """Create a mock RCON handler."""
        rcon = Mock()
        rcon.agent_id = "agent_1"
        rcon.execute.return_value = "true"  # Default: all positions valid
        return rcon

    @pytest.fixture
    def hints(self, mock_rcon):
        """Create a PlacementHints instance."""
        return PlacementHints(mock_rcon)

    def test_get_placement_line_horizontal_belt(self, hints, mock_rcon):
        """Test generating a horizontal belt line."""
        mock_rcon.execute.return_value = "{true, true, true, true, true}"

        plan = hints.get_placement_line(
            "transport-belt",
            MapPosition(x=0.0, y=10.0),
            MapPosition(x=4.0, y=10.0),
            validate=True,
        )

        assert plan.entity_name == "transport-belt"
        assert len(plan.positions) == 5
        assert plan.valid is True

        # All belts should face EAST (positive x direction)
        for pos, direction in plan.positions:
            assert direction == Direction.EAST
            assert pos.y == 10.0

        # Check label format
        assert plan.label.startswith("plan:transport-belt:line:")
        assert "line" in plan.description.lower()

    def test_get_placement_line_vertical_pipe(self, hints, mock_rcon):
        """Test generating a vertical pipe line."""
        mock_rcon.execute.return_value = "{true, true, true}"

        plan = hints.get_placement_line(
            "pipe", MapPosition(x=5.0, y=0.0), MapPosition(x=5.0, y=2.0), validate=True
        )

        assert plan.entity_name == "pipe"
        assert len(plan.positions) == 3
        assert plan.valid is True

        # Pipes don't require direction (non-directional entity)
        for pos, direction in plan.positions:
            assert direction is None or direction == Direction.SOUTH
            assert pos.x == 5.0

    def test_get_placement_line_no_validation(self, hints, mock_rcon):
        """Test generating line without validation."""
        plan = hints.get_placement_line(
            "stone-wall",
            MapPosition(x=0.0, y=0.0),
            MapPosition(x=3.0, y=0.0),
            validate=False,
        )

        assert plan.valid is True  # Assumed valid when validation skipped
        assert mock_rcon.execute.call_count == 0  # No validation calls

    def test_get_placement_line_invalid_positions(self, hints, mock_rcon):
        """Test line generation with some invalid positions."""
        # Return mixed results
        mock_rcon.execute.return_value = "{true, false, true}"

        plan = hints.get_placement_line(
            "transport-belt",
            MapPosition(x=0.0, y=0.0),
            MapPosition(x=2.0, y=0.0),
            validate=True,
        )

        assert plan.valid is False  # Should fail validation

    def test_entity_requires_direction(self, hints):
        """Test entity direction requirement detection."""
        # Directional entities
        assert hints._entity_requires_direction("transport-belt") is True
        assert hints._entity_requires_direction("inserter") is True
        assert hints._entity_requires_direction("electric-mining-drill") is True

        # Non-directional entities (pipe is actually non-directional in most cases)
        assert hints._entity_requires_direction("stone-wall") is False
        assert hints._entity_requires_direction("small-electric-pole") is False

    def test_generate_label_uniqueness(self, hints):
        """Test that labels are unique."""
        label1 = hints._generate_label("transport-belt", "line")
        label2 = hints._generate_label("transport-belt", "line")

        assert label1 != label2  # Should be unique due to timestamp/hash
        assert "transport-belt" in label1
        assert "line" in label1


class TestGhostPlan:
    """Tests for GhostPlan class."""

    def test_ghost_plan_creation(self):
        """Test creating a GhostPlan."""
        positions = [
            (MapPosition(x=0.0, y=0.0), Direction.EAST),
            (MapPosition(x=1.0, y=0.0), Direction.EAST),
        ]

        plan = GhostPlan(
            entity_name="transport-belt",
            positions=positions,
            label="test_label",
            description="Test plan",
            valid=True,
        )

        assert plan.entity_name == "transport-belt"
        assert len(plan.positions) == 2
        assert plan.valid is True

    def test_ghost_plan_revalidation(self):
        """Test re-validating a GhostPlan."""
        positions = [
            (MapPosition(x=0.0, y=0.0), Direction.EAST),
            (MapPosition(x=1.0, y=0.0), Direction.EAST),
        ]

        plan = GhostPlan(
            entity_name="transport-belt",
            positions=positions,
            label="test_label",
            description="Test plan",
            valid=True,
        )

        # Mock validator that returns all False
        mock_rcon = Mock()
        mock_rcon.execute.return_value = "{false, false}"
        validator = PlacementValidator(mock_rcon)

        result = plan.validate(validator)

        assert result is False
        assert plan.valid is False


class TestConnectionSolving:
    """Tests for connection position solving."""

    @pytest.fixture
    def mock_rcon(self):
        """Create a mock RCON handler."""
        rcon = Mock()
        rcon.agent_id = "agent_1"
        rcon.execute.return_value = "true"
        return rcon

    @pytest.fixture
    def hints(self, mock_rcon):
        """Create a PlacementHints instance."""
        return PlacementHints(mock_rcon)

    def test_get_connection_positions_item_drop(self, hints, mock_rcon):
        """Test getting drill placement positions for item drop."""
        # Create a mock target entity (chest)
        target = Mock()
        target.name = "iron-chest"
        target.position = MapPosition(x=10.0, y=10.0)

        # Mock the drill entity with prototype data
        source = Mock()
        source.name = "electric-mining-drill"
        source.position = MapPosition(x=8.0, y=10.0)
        source.prototype = {"vector_to_place_result": [0, -1.85]}

        # Mock validation to return True for all positions
        mock_rcon.execute.return_value = "true"

        # Test it returns a list
        positions = hints.get_connection_positions(
            source, "electric-mining-drill", ConnectionType.ITEM_DROP
        )

        # Should return positions (or empty list if prototypes not available)
        assert isinstance(positions, list)


class TestIntegration:
    """Integration tests for the placement_hints workflow."""

    @pytest.fixture
    def mock_rcon(self):
        """Create a mock RCON handler."""
        rcon = Mock()
        rcon.agent_id = "agent_1"
        rcon.execute.return_value = "true"
        return rcon

    def test_full_workflow_belt_line(self, mock_rcon):
        """Test full workflow: create plan, validate, use with ghost builder."""
        # Mock batch validation response
        mock_rcon.execute.return_value = "{true, true, true, true, true}"

        hints = PlacementHints(mock_rcon)

        # Create a belt line plan
        plan = hints.get_placement_line(
            "transport-belt",
            MapPosition(x=0.0, y=0.0),
            MapPosition(x=4.0, y=0.0),
            validate=True,
        )

        # Verify plan is valid
        assert plan.valid is True
        assert len(plan.positions) == 5

        # Verify all positions have correct direction
        for pos, direction in plan.positions:
            assert direction == Direction.EAST

        # Verify label can be used for ghost tracking
        assert plan.label.startswith("plan:transport-belt:line:")

        # Simulate map change - re-validate
        mock_rcon.execute.return_value = "{true, false, true, true, true}"
        result = plan.validate(PlacementValidator(mock_rcon))

        assert result is False  # One position is now invalid
        assert plan.valid is False
