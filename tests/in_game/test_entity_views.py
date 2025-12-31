"""
In-game tests for entity placement and properties.

These tests validate entity placement via TestGround and basic
entity property verification. They follow the FactoryVerse testing
conventions documented in tests/README.md.

Uses root conftest fixtures: test_ground, clean_area, agent, admin
"""

import pytest
from FactoryVerse.factory.types import Direction


class TestEntityPlacement:
    """Test entity placement via TestGround helper."""

    def test_place_stone_furnace(self, clean_area):
        """Can place a stone-furnace at origin."""
        entity = clean_area.place_entity(
            entity_name="stone-furnace",
            x=0,
            y=0,
            direction=Direction.NORTH.value,
        )

        assert entity is not None
        assert entity.name == "stone-furnace"

    def test_place_inserter_with_direction(self, clean_area):
        """Inserter placement respects direction."""
        entity = clean_area.place_entity(
            entity_name="inserter",
            x=3,
            y=0,
            direction=Direction.EAST.value,
        )

        assert entity is not None
        assert entity.direction == Direction.EAST.value

    def test_place_transport_belt_line(self, clean_area):
        """Can place multiple belts in a line."""
        belts = []
        for i in range(5):
            belt = clean_area.place_entity(
                entity_name="transport-belt",
                x=i,
                y=5,
                direction=Direction.EAST.value,
            )
            belts.append(belt)

        assert len(belts) == 5
        assert all(b.name == "transport-belt" for b in belts)

    def test_place_electric_mining_drill(self, clean_area):
        """Electric mining drill can be placed on ore."""
        clean_area.place_resource_patch(
            resource_name="iron-ore",
            center_x=0,
            center_y=0,
            size=5,
            amount=1000,
        )

        drill = clean_area.place_entity(
            entity_name="electric-mining-drill",
            x=0,
            y=0,
            direction=Direction.SOUTH.value,
        )

        assert drill is not None
        assert drill.name == "electric-mining-drill"


class TestEntityProperties:
    """Test entity properties on placed entities."""

    def test_placed_entity_has_name(self, clean_area):
        """Placed entity should have name property."""
        furnace = clean_area.place_entity(
            entity_name="stone-furnace",
            x=0,
            y=0,
        )

        assert furnace.name == "stone-furnace"

    def test_placed_entity_has_position(self, clean_area):
        """Placed entity should have position property."""
        furnace = clean_area.place_entity(
            entity_name="stone-furnace",
            x=5,
            y=5,
        )

        assert furnace.position is not None
        # Position is a tuple (x, y) from PlacedEntity
        assert furnace.position[0] == 5
        assert furnace.position[1] == 5

    def test_placed_entity_has_direction(self, clean_area):
        """Placed entity with direction should store it."""
        inserter = clean_area.place_entity(
            entity_name="inserter",
            x=0,
            y=0,
            direction=Direction.EAST.value,
        )

        assert inserter.direction == Direction.EAST.value


class TestAgentInspection:
    """Test entity inspection via agent interface."""

    def test_agent_can_get_reachable(self, clean_area, agent):
        """Agent can query reachable entities."""
        clean_area.place_entity(
            entity_name="stone-furnace",
            x=50,
            y=50,
        )

        # Teleport agent near the entity
        agent.teleport(50, 50)

        # Get reachable entities
        reachable = agent.get_reachable()
        assert reachable is not None


class TestAgentOperations:
    """Test entity operations via agent interface."""

    @pytest.mark.skip(
        reason="Agent placement requires complex setup: reachability, inventory state, and position validation"
    )
    def test_agent_can_place_entity(self, clean_area, agent, admin, agent_id):
        """Agent can place items from inventory."""
        # Extract numeric ID from agent_id string (e.g., "agent_1" -> 1)
        numeric_id = int(agent_id.split("_")[1])

        # Give agent a furnace
        admin.add_items(numeric_id, {"stone-furnace": 1})

        # Teleport agent to placement location
        agent.teleport(60, 60)

        # Place the entity
        result = agent.place_entity(
            entity_name="stone-furnace",
            x=60,
            y=60,
        )

        assert result is not None


@pytest.mark.slow
class TestSnapshotBehavior:
    """Test snapshot-related behavior."""

    def test_placed_entity_persists(self, clean_area):
        """Placed entity should exist after placement."""
        furnace = clean_area.place_entity(
            entity_name="stone-furnace",
            x=70,
            y=70,
        )

        # Force snapshot update
        clean_area.force_resnapshot()

        # Verify entity was placed
        assert furnace is not None
        assert furnace.name == "stone-furnace"

    def test_clean_area_resets_successfully(self, clean_area):
        """clean_area fixture should provide cleared area."""
        # The clean_area fixture already resets the area
        # Just verify we can place without collision
        furnace = clean_area.place_entity(
            entity_name="stone-furnace",
            x=80,
            y=80,
        )

        assert furnace is not None
