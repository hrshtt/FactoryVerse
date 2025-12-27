"""Example DSL test showing fixture usage.

This test validates the DSL fixtures and serves as a reference implementation.
"""

import pytest
from FactoryVerse.dsl.dsl import reachable, inventory


class TestDSLFixtures:
    """Tests that validate DSL fixture setup."""

    def test_dsl_context_available(self, dsl_context):
        """DSLTestContext should provide all helpers."""
        # Verify all components available
        assert hasattr(dsl_context, "test_ground")
        assert hasattr(dsl_context, "admin")
        assert hasattr(dsl_context, "playing")

        # Verify playing() returns context manager
        assert callable(dsl_context.playing)

    def test_playing_context_works(self, dsl_context):
        """playing_factorio() context should activate DSL."""
        # Setup
        dsl_context.test_ground.place_entity("stone-furnace", 10, 10)

        # Act - use playing() context
        with dsl_context.playing():
            # DSL affordances should work
            furnace = reachable.get_entity("stone-furnace")

            # Assert
            assert furnace is not None
            assert furnace.name == "stone-furnace"
            assert furnace.position.x == 10
            assert furnace.position.y == 10


class TestEntityInspection:
    """Tests for entity inspection through DSL."""

    def test_furnace_inspection(self, dsl_context):
        """Furnace inspection should return formatted string."""
        # Arrange
        dsl_context.test_ground.place_entity("stone-furnace", 10, 10)
        dsl_context.admin.add_items(1, {"coal": 10, "iron-ore": 10})

        # Act
        with dsl_context.playing():
            furnace = reachable.get_entity("stone-furnace")
            info = furnace.inspect()

        # Assert
        assert isinstance(info, str)
        assert "Furnace" in info or "stone-furnace" in info
        assert "Status:" in info

    def test_furnace_add_fuel(self, dsl_context):
        """Furnace should accept fuel through DSL."""
        # Arrange
        dsl_context.test_ground.place_entity("stone-furnace", 10, 10)
        dsl_context.admin.add_items(1, {"coal": 50})

        # Act
        with dsl_context.playing():
            furnace = reachable.get_entity("stone-furnace")
            coal_stacks = inventory.get_item_stacks("coal", 10)
            result = furnace.add_fuel(coal_stacks)

        # Assert
        assert result is not None
        assert len(result) > 0


class TestInventoryHelpers:
    """Tests for inventory helper methods."""

    def test_get_total(self, dsl_context):
        """inventory.get_total() should count items."""
        # Arrange
        dsl_context.admin.add_items(1, {"iron-plate": 100, "copper-plate": 50})

        # Act
        with dsl_context.playing():
            iron_count = inventory.get_total("iron-plate")
            copper_count = inventory.get_total("copper-plate")

        # Assert
        assert iron_count == 100
        assert copper_count == 50

    def test_get_item_stacks(self, dsl_context):
        """inventory.get_item_stacks() should create stacks."""
        # Arrange
        dsl_context.admin.add_items(1, {"coal": 100})

        # Act
        with dsl_context.playing():
            # Get 2 stacks of 10 coal each
            stacks = inventory.get_item_stacks("coal", count=10, number_of_stacks=2)

        # Assert
        assert len(stacks) == 2
        assert all(s.name == "coal" for s in stacks)
        assert all(s.count == 10 for s in stacks)


class TestReachableAccessors:
    """Tests for reachable entity/resource accessors."""

    def test_get_entity(self, dsl_context):
        """reachable.get_entity() should find placed entities."""
        # Arrange
        dsl_context.test_ground.place_entity("iron-chest", 20, 20)

        # Act
        with dsl_context.playing():
            chest = reachable.get_entity("iron-chest")

        # Assert
        assert chest is not None
        assert chest.name == "iron-chest"
        assert chest.position.x == 20
        assert chest.position.y == 20

    def test_get_entities_filter(self, dsl_context):
        """reachable.get_entities() should filter by name."""
        # Arrange
        dsl_context.test_ground.place_entity("stone-furnace", 10, 10)
        dsl_context.test_ground.place_entity("stone-furnace", 15, 15)
        dsl_context.test_ground.place_entity("iron-chest", 20, 20)

        # Act
        with dsl_context.playing():
            furnaces = reachable.get_entities("stone-furnace")

        # Assert
        assert len(furnaces) >= 2
        assert all(f.name == "stone-furnace" for f in furnaces)


@pytest.mark.slow
class TestPrototypes:
    """Tests for prototype loading."""

    def test_prototypes_loaded(self, with_prototypes):
        """Prototype data should be available."""
        from FactoryVerse.dsl.prototypes import (
            get_entity_prototypes,
            get_item_prototypes,
        )

        entity_protos = get_entity_prototypes()
        item_protos = get_item_prototypes()

        # Check some known entities/items
        assert entity_protos.get("stone-furnace") is not None
        assert item_protos.get("iron-plate") is not None

        # Verify fuel categories
        assert item_protos.is_fuel("coal")
        assert item_protos.get_fuel_category("coal") == "chemical"
