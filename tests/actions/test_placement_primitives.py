"""Tests for new placement hint primitives.

Tests:
- get_inserter_placement_positions()
- get_pole_line()
- get_pole_coverage_position()
- get_pole_coverage_plan()
- get_underground_segment()

Requirements:
- Factorio server running with test-ground scenario on port 27100
"""

import pytest
from factorio_rcon import RCONClient

from FactoryVerse.factory.prototypes import get_entity_prototypes
from FactoryVerse.factory.types import MapPosition, Direction
from FactoryVerse.agent.infra.rcon_handler import RconHandler
from FactoryVerse.agent.embodied_actions.placement_hints import (
    PlacementValidator,
    PlacementHints,
    GhostPlan,
    INSERTER_ENTITIES,
    ELECTRIC_POLE_ENTITIES,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(scope="module")
def rcon_client():
    """RCON client for test-ground scenario."""
    client = RCONClient("localhost", 27100, "factorio")
    yield client


@pytest.fixture(scope="module")
def rcon_handler(rcon_client):
    """RconHandler for PlacementValidator."""
    return RconHandler(rcon_client, agent_id="test_placement_hints")


@pytest.fixture(scope="module")
def validator(rcon_handler):
    """PlacementValidator instance."""
    return PlacementValidator(rcon_handler)


@pytest.fixture(scope="module")
def hints(rcon_handler):
    """PlacementHints instance."""
    return PlacementHints(rcon_handler)


@pytest.fixture(scope="module")
def prototypes():
    """Entity prototypes for static data lookup."""
    return get_entity_prototypes()


@pytest.fixture(scope="function")
def clear_area(rcon_client):
    """Clear test area and return center position."""
    base_x = 120
    base_y = 120

    clear_cmd = f"""
    /sc local surface = game.surfaces[1]
    local area = {{left_top = {{x = {base_x - 20}, y = {base_y - 20}}}, right_bottom = {{x = {base_x + 20}, y = {base_y + 20}}}}}
    for _, entity in pairs(surface.find_entities_filtered{{area = area}}) do
        if entity.name ~= "character" then entity.destroy() end
    end
    """
    rcon_client.send_command(clear_cmd)

    yield MapPosition(x=float(base_x), y=float(base_y))

    rcon_client.send_command(clear_cmd)


# =============================================================================
# ENTITY SETS TESTS
# =============================================================================


class TestEntitySets:
    """Tests for entity set definitions."""

    def test_inserter_entities_complete(self):
        """Verify INSERTER_ENTITIES contains all inserter types."""
        assert "inserter" in INSERTER_ENTITIES
        assert "long-handed-inserter" in INSERTER_ENTITIES
        assert "fast-inserter" in INSERTER_ENTITIES
        assert "burner-inserter" in INSERTER_ENTITIES
        assert "bulk-inserter" in INSERTER_ENTITIES

    def test_electric_pole_entities_complete(self):
        """Verify ELECTRIC_POLE_ENTITIES contains all pole types."""
        assert "small-electric-pole" in ELECTRIC_POLE_ENTITIES
        assert "medium-electric-pole" in ELECTRIC_POLE_ENTITIES
        assert "big-electric-pole" in ELECTRIC_POLE_ENTITIES
        assert "substation" in ELECTRIC_POLE_ENTITIES

    def test_entity_sets_are_frozen(self):
        """Verify entity sets are immutable."""
        with pytest.raises(AttributeError):
            INSERTER_ENTITIES.add("fake-entity")
        with pytest.raises(AttributeError):
            ELECTRIC_POLE_ENTITIES.add("fake-entity")


# =============================================================================
# get_pole_line() TESTS
# =============================================================================


class TestGetPoleLine:
    """Tests for get_pole_line() method."""

    def test_pole_line_basic(self, hints, clear_area):
        """Test basic pole line generation."""
        start = clear_area
        end = MapPosition(x=start.x + 30, y=start.y)

        plan = hints.get_pole_line(start, end, pole_name="medium-electric-pole")

        assert isinstance(plan, GhostPlan)
        assert plan.entity_name == "medium-electric-pole"
        assert len(plan.positions) > 0
        assert "pole_line" in plan.label

    def test_pole_line_spacing(self, hints, prototypes, clear_area):
        """Test that poles are spaced by maximum_wire_distance."""
        start = clear_area
        end = MapPosition(x=start.x + 50, y=start.y)

        plan = hints.get_pole_line(start, end, pole_name="medium-electric-pole")

        # Medium pole max wire distance is 9
        max_wire = prototypes.get_prototype("medium-electric-pole")[
            "maximum_wire_distance"
        ]

        # Check spacing between consecutive poles
        prev_pos = None
        for pos, _ in plan.positions:
            if prev_pos is not None:
                distance = (
                    (pos.x - prev_pos.x) ** 2 + (pos.y - prev_pos.y) ** 2
                ) ** 0.5
                # Distance should not exceed max wire distance
                assert distance <= max_wire + 0.1, (
                    f"Pole spacing {distance} exceeds max {max_wire}"
                )
            prev_pos = pos

    def test_pole_line_big_pole(self, hints, prototypes, clear_area):
        """Test pole line with big-electric-pole (32 tile wire reach)."""
        start = clear_area
        end = MapPosition(x=start.x + 100, y=start.y)

        plan = hints.get_pole_line(start, end, pole_name="big-electric-pole")

        # Big poles should require fewer poles than medium for same distance
        max_wire = prototypes.get_prototype("big-electric-pole")[
            "maximum_wire_distance"
        ]
        assert max_wire == 32

        # ~100 tiles with 32 reach = 4 poles minimum
        assert len(plan.positions) <= 6

    def test_pole_line_single_point(self, hints, clear_area):
        """Test pole line with start == end."""
        start = clear_area

        plan = hints.get_pole_line(start, start, pole_name="small-electric-pole")

        assert len(plan.positions) == 1

    def test_pole_line_diagonal(self, hints, clear_area):
        """Test pole line on diagonal path."""
        start = clear_area
        end = MapPosition(x=start.x + 20, y=start.y + 20)

        plan = hints.get_pole_line(start, end)

        assert len(plan.positions) > 0
        # First should be at start, last at end
        assert plan.positions[0][0].distance(start) < 1
        assert plan.positions[-1][0].distance(end) < 1


# =============================================================================
# get_pole_coverage_position() TESTS
# =============================================================================


class TestGetPoleCoveragePosition:
    """Tests for get_pole_coverage_position() method."""

    def test_single_entity_coverage(self, hints, clear_area):
        """Test coverage for a single entity."""

        class MockEntity:
            def __init__(self, x, y):
                self.position = MapPosition(x=x, y=y)

        entity = MockEntity(clear_area.x, clear_area.y)

        pos = hints.get_pole_coverage_position([entity])

        assert pos is not None
        # Position should be near the entity
        assert pos.distance(entity.position) < 5

    def test_close_entities_coverage(self, hints, clear_area):
        """Test coverage for entities within supply area."""

        class MockEntity:
            def __init__(self, x, y):
                self.position = MapPosition(x=x, y=y)

        # All entities within 3.5 radius (medium pole supply)
        entities = [
            MockEntity(clear_area.x, clear_area.y),
            MockEntity(clear_area.x + 2, clear_area.y),
            MockEntity(clear_area.x, clear_area.y + 2),
        ]

        pos = hints.get_pole_coverage_position(entities, "medium-electric-pole")

        assert pos is not None

    def test_distant_entities_no_coverage(self, hints, clear_area):
        """Test that distant entities cannot be covered by single pole."""

        class MockEntity:
            def __init__(self, x, y):
                self.position = MapPosition(x=x, y=y)

        # Entities too far apart (10+ tiles, exceeds 3.5 radius)
        entities = [
            MockEntity(clear_area.x, clear_area.y),
            MockEntity(clear_area.x + 20, clear_area.y),  # Too far
        ]

        pos = hints.get_pole_coverage_position(entities, "medium-electric-pole")

        assert pos is None

    def test_substation_larger_coverage(self, hints, clear_area):
        """Test that substation can cover larger area."""

        class MockEntity:
            def __init__(self, x, y):
                self.position = MapPosition(x=x, y=y)

        # Entities within substation range (9 supply radius)
        entities = [
            MockEntity(clear_area.x, clear_area.y),
            MockEntity(clear_area.x + 8, clear_area.y),
            MockEntity(clear_area.x, clear_area.y + 8),
        ]

        pos = hints.get_pole_coverage_position(entities, "substation")

        assert pos is not None


# =============================================================================
# get_pole_coverage_plan() TESTS
# =============================================================================


class TestGetPoleCoveragePlan:
    """Tests for get_pole_coverage_plan() method."""

    def test_empty_entities(self, hints):
        """Test with no entities."""
        plan, uncovered = hints.get_pole_coverage_plan([])

        assert len(plan.positions) == 0
        assert len(uncovered) == 0

    def test_single_cluster(self, hints, clear_area):
        """Test entities that can be covered by single pole."""

        class MockEntity:
            def __init__(self, x, y):
                self.position = MapPosition(x=x, y=y)

        entities = [
            MockEntity(clear_area.x, clear_area.y),
            MockEntity(clear_area.x + 2, clear_area.y),
        ]

        plan, uncovered = hints.get_pole_coverage_plan(entities, "medium-electric-pole")

        assert len(plan.positions) >= 1
        assert len(uncovered) == 0  # All covered


# =============================================================================
# get_underground_segment() TESTS
# =============================================================================


class TestGetUndergroundSegment:
    """Tests for get_underground_segment() method."""

    def test_underground_belt_basic(self, hints, clear_area):
        """Test basic underground belt segment."""
        start = clear_area
        end = MapPosition(x=start.x + 4, y=start.y)  # Within max distance (5)

        plan = hints.get_underground_segment(
            "underground-belt", start, end, Direction.EAST
        )

        assert isinstance(plan, GhostPlan)
        assert plan.entity_name == "underground-belt"
        assert len(plan.positions) == 2  # Entrance and exit

    def test_underground_belt_max_distance(self, hints, prototypes, clear_area):
        """Test underground belt at max distance."""
        max_dist = prototypes.get_prototype("underground-belt")["max_distance"]
        assert max_dist == 5

        start = clear_area
        end = MapPosition(x=start.x + max_dist, y=start.y)

        # Should work at max distance
        plan = hints.get_underground_segment(
            "underground-belt", start, end, Direction.EAST
        )
        assert len(plan.positions) == 2

    def test_underground_belt_exceeds_max(self, hints, clear_area):
        """Test underground belt exceeding max distance raises error."""
        start = clear_area
        end = MapPosition(x=start.x + 10, y=start.y)  # Exceeds 5

        with pytest.raises(ValueError, match="exceeds max_underground_distance"):
            hints.get_underground_segment(
                "underground-belt", start, end, Direction.EAST
            )

    def test_pipe_to_ground_basic(self, hints, clear_area):
        """Test pipe-to-ground segment."""
        start = clear_area
        end = MapPosition(x=start.x, y=start.y + 8)  # Within max distance (10)

        plan = hints.get_underground_segment(
            "pipe-to-ground", start, end, Direction.SOUTH
        )

        assert len(plan.positions) == 2

    def test_pipe_to_ground_max_distance(self, hints, clear_area):
        """Test pipe-to-ground at max distance (10)."""
        start = clear_area
        end = MapPosition(x=start.x, y=start.y + 10)

        plan = hints.get_underground_segment(
            "pipe-to-ground", start, end, Direction.SOUTH
        )
        assert len(plan.positions) == 2

    def test_pipe_to_ground_exceeds_max(self, hints, clear_area):
        """Test pipe-to-ground exceeding max distance."""
        start = clear_area
        end = MapPosition(x=start.x, y=start.y + 15)  # Exceeds 10

        with pytest.raises(ValueError, match="exceeds max_underground_distance"):
            hints.get_underground_segment("pipe-to-ground", start, end, Direction.SOUTH)


# =============================================================================
# get_inserter_placement_positions() TESTS
# =============================================================================


class TestGetInserterPlacementPositions:
    """Tests for get_inserter_placement_positions() method."""

    def test_inserter_between_adjacent_entities(self, hints, rcon_client, clear_area):
        """Test finding inserter position between two adjacent entities."""
        # Place two chests adjacent to each other
        chest1_pos = clear_area
        chest2_pos = MapPosition(x=clear_area.x + 2, y=clear_area.y)

        place_cmd = f"""
        /sc local s = game.surfaces[1]
        s.create_entity{{name="iron-chest", position={{x={chest1_pos.x}, y={chest1_pos.y}}}, force="player"}}
        s.create_entity{{name="iron-chest", position={{x={chest2_pos.x}, y={chest2_pos.y}}}, force="player"}}
        rcon.print("placed")
        """
        result = rcon_client.send_command(place_cmd)

        if "placed" not in result:
            pytest.skip("Could not place test entities")

        class MockEntity:
            def __init__(self, x, y, name="iron-chest"):
                self.position = MapPosition(x=x, y=y)
                self.name = name

        source = MockEntity(chest1_pos.x, chest1_pos.y)
        target = MockEntity(chest2_pos.x, chest2_pos.y)

        positions = hints.get_inserter_placement_positions(source, target)

        # Should return list (may or may not have valid positions depending on spacing)
        assert isinstance(positions, list)

    def test_inserter_prototype_data(self, prototypes):
        """Verify inserter prototype has required position data."""
        inserter = prototypes.get_prototype("inserter")

        assert "pickup_position" in inserter
        assert "insert_position" in inserter

        pickup = inserter["pickup_position"]
        insert = inserter["insert_position"]

        # Default inserter: pickup behind, drop in front
        assert len(pickup) == 2
        assert len(insert) == 2

    def test_long_handed_inserter_prototype(self, prototypes):
        """Verify long-handed inserter has extended reach."""
        lh_inserter = prototypes.get_prototype("long-handed-inserter")

        pickup = lh_inserter["pickup_position"]
        insert = lh_inserter["insert_position"]

        # Long-handed should have larger distances
        regular = prototypes.get_prototype("inserter")
        assert abs(pickup[1]) > abs(regular["pickup_position"][1])


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================


class TestHelperFunctions:
    """Tests for internal helper functions."""

    def test_rotate_vector_north(self):
        """Test vector rotation for NORTH (no change)."""
        result = PlacementHints._rotate_vector((1, 0), Direction.NORTH)
        assert result == (1, 0)

    def test_rotate_vector_east(self):
        """Test vector rotation 90 degrees for EAST."""
        result = PlacementHints._rotate_vector((0, 1), Direction.EAST)
        assert result == (-1, 0)

    def test_rotate_vector_south(self):
        """Test vector rotation 180 degrees for SOUTH."""
        result = PlacementHints._rotate_vector((1, 0), Direction.SOUTH)
        assert result == (-1, 0)

    def test_rotate_vector_west(self):
        """Test vector rotation 270 degrees for WEST."""
        result = PlacementHints._rotate_vector((0, 1), Direction.WEST)
        assert result == (1, 0)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
