"""Example DSL test showing fixture usage with new AgentRuntime pattern.

This test validates the new factory-based architecture.
"""

import pytest
from FactoryVerse.factory.types import MapPosition


class TestAgentRuntimeFixture:
    """Tests that validate AgentRuntime fixture setup."""

    async def test_runtime_available(self, agent_runtime):
        """AgentRuntime should be started and have all affordances."""
        # Verify runtime is started
        assert agent_runtime._started

        # Verify all affordances available
        assert hasattr(agent_runtime, "walking")
        assert hasattr(agent_runtime, "mining")
        assert hasattr(agent_runtime, "crafting")
        assert hasattr(agent_runtime, "inventory")
        assert hasattr(agent_runtime, "reachable")
        assert hasattr(agent_runtime, "resources")
        assert hasattr(agent_runtime, "research")

    async def test_dsl_context_available(self, dsl_context):
        """DSLTestContext should provide all helpers."""
        # Verify all components available
        assert hasattr(dsl_context, "test_ground")
        assert hasattr(dsl_context, "admin")
        assert hasattr(dsl_context, "runtime")

        # Verify convenience accessors
        assert dsl_context.reachable is dsl_context.runtime.reachable
        assert dsl_context.walking is dsl_context.runtime.walking


class TestEntityInspection:
    """Tests for entity inspection through AgentRuntime."""

    async def test_get_reachable_entity(self, dsl_context):
        """reachable.get_entity() should find placed entities."""
        # Arrange
        dsl_context.test_ground.place_entity("stone-furnace", 2, 2)

        # Act - use runtime directly
        runtime = dsl_context.runtime
        furnace = runtime.reachable.get_entity("stone-furnace")

        # Assert
        assert furnace is not None
        assert furnace.name == "stone-furnace"
        assert furnace.position.x == 2
        assert furnace.position.y == 2

    async def test_furnace_inspection(self, dsl_context):
        """Furnace inspection should return formatted string."""
        # Arrange
        dsl_context.test_ground.place_entity("stone-furnace", 2, 2)

        # Act
        furnace = dsl_context.reachable.get_entity("stone-furnace")
        info = furnace.inspect()

        # Assert
        assert isinstance(info, str)
        assert "Furnace" in info or "stone-furnace" in info


class TestInventoryOperations:
    """Tests for inventory operations through AgentRuntime."""

    async def test_inventory_query(self, dsl_context):
        """inventory.item_stacks should return inventory data."""
        # Arrange
        dsl_context.admin.add_items(1, {"iron-plate": 100})

        # Act
        inventory = dsl_context.inventory
        stacks = inventory.item_stacks

        # Assert - basic check that we get some response
        assert stacks is not None
        assert isinstance(stacks, list)


class TestReachable:
    """Tests for reachable entity queries."""

    async def test_get_entities_filter(self, dsl_context):
        """reachable.get_entities() should filter by name."""
        # Arrange
        dsl_context.test_ground.place_entity("stone-furnace", 2, 2)
        dsl_context.test_ground.place_entity("stone-furnace", 4, 4)
        dsl_context.test_ground.place_entity("iron-chest", 6, 6)

        # Act
        furnaces = dsl_context.reachable.get_entities("stone-furnace")

        # Assert
        assert len(furnaces) >= 2
        assert all(f.name == "stone-furnace" for f in furnaces)

    async def test_get_entity_by_position(self, dsl_context):
        """reachable.get_entity() should filter by position."""
        # Arrange
        dsl_context.test_ground.place_entity("stone-furnace", 2, 2)
        dsl_context.test_ground.place_entity("stone-furnace", 4, 4)

        # Act - get by name AND position
        furnace = dsl_context.reachable.get_entity(
            "stone-furnace", position=MapPosition(4, 4)
        )

        # Assert
        assert furnace is not None
        assert furnace.position.x == 4
        assert furnace.position.y == 4


class TestEntityViews:
    """Tests for entity view wrappers (Reachable, RemoteView, Ghost)."""

    async def test_reachable_view_has_full_access(self, dsl_context):
        """Reachable view should allow all operations."""
        # Arrange
        dsl_context.test_ground.place_entity("stone-furnace", 2, 2)

        # Act
        furnace = dsl_context.reachable.get_entity("stone-furnace")

        # Assert - Reachable should have all methods
        assert hasattr(furnace, "inspect")
        assert hasattr(furnace, "add_fuel")
        assert hasattr(furnace, "add_ingredients")
        assert hasattr(furnace, "pickup")

        # Can call inspect (read operation)
        info = furnace.inspect()
        assert info is not None


@pytest.mark.slow
class TestPrototypes:
    """Tests for prototype loading."""

    def test_prototypes_loaded(self, with_prototypes):
        """Prototype data should be available."""
        from FactoryVerse.factory.prototypes import (
            get_entity_prototypes,
            get_item_prototypes,
        )

        entity_protos = get_entity_prototypes()
        item_protos = get_item_prototypes()

        # Check some known entities/items - use get_prototype for entities
        stone_furnace_proto = entity_protos.get_prototype("stone-furnace")
        assert stone_furnace_proto is not None
        assert len(stone_furnace_proto) > 0
        # Items are stored in .items dict
        assert "iron-plate" in item_protos.items

        # Verify fuel categories
        assert item_protos.is_fuel("coal")
        assert item_protos.get_fuel_category("coal") == "chemical"
