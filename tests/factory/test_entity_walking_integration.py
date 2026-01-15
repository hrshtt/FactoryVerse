"""Tests for entity walking integration.

Validates that entities and resources from RemoteView have functional walk_to() methods
and that the Dependency Injection pipeline properly passes walking actions through
the query system.

Based on: docs/implementation_summaries/entity_walking_integration.md
"""

import pytest
import asyncio
from FactoryVerse.factory.types import MapPosition
from FactoryVerse.agent.actions.walking import (
    WalkingUnreachableError,
    WalkingEntityNotFoundError,
    WalkingNoStandableTilesError,
)


class TestRemoteEntityWalking:
    """Tests for walk_to() on entities from RemoteView queries."""

    async def test_remote_entity_has_walk_to_method(self, dsl_context):
        """Remote entities from remote_view queries should have walk_to() method."""
        # Arrange - place an entity far from agent
        dsl_context.test_ground.place_entity("stone-furnace", 50, 50)
        dsl_context.test_ground.force_resnapshot()  # Trigger snapshot for RemoteView
        
        # Wait for snapshots to be written (async process)
        await asyncio.sleep(2)
        
        # Reload RemoteView to get fresh data
        dsl_context.runtime.remote_view.rebuild()
        
        # Act - query via RemoteView
        entities = dsl_context.runtime.remote_view.get_entities(
            "SELECT * FROM map_entity WHERE entity_name = 'stone-furnace' LIMIT 1"
        )
        
        # Assert - should have walk_to method
        assert len(entities) > 0
        entity = entities[0]
        assert hasattr(entity, "walk_to")
        assert callable(entity.walk_to)

    @pytest.mark.skip(reason="Need agent teleport method in TestGround")
    async def test_remote_entity_walk_to_success(self, dsl_context):
        """walk_to() on remote entity should navigate to the entity."""
        # Arrange - place entity and teleport agent far away
        dsl_context.test_ground.place_entity("iron-chest", 30, 30)
        # TODO: Add teleport_agent method to TestGround helper
        # dsl_context.test_ground.teleport_agent(0, 0)
        dsl_context.test_ground.force_resnapshot()
        
        # Reload RemoteView
        dsl_context.runtime.remote_view.rebuild()
        
        # Query entity via RemoteView
        entities = dsl_context.runtime.remote_view.get_entities(
            "SELECT * FROM map_entity WHERE entity_name = 'iron-chest' LIMIT 1"
        )
        assert len(entities) > 0
        chest = entities[0]
        
        # Act - walk to the entity
        # final_pos = await chest.walk_to(timeout=10)
        
        # Assert - agent should be near the chest
        # assert final_pos is not None
        # Check that we're within reach of the entity (default reach is 10)
        # distance = ((final_pos.x - 30) ** 2 + (final_pos.y - 30) ** 2) ** 0.5
        # assert distance < 10, f"Agent too far from entity: {distance}"

    @pytest.mark.skip(reason="Need entity removal method in TestGround")
    async def test_remote_entity_walk_to_nonexistent(self, dsl_context):
        """walk_to() should raise error when entity no longer exists."""
        # Arrange - place and snapshot entity
        dsl_context.test_ground.place_entity("stone-furnace", 40, 40)
        dsl_context.test_ground.force_resnapshot()
        dsl_context.runtime.remote_view.rebuild()
        
        # Query entity
        entities = dsl_context.runtime.remote_view.get_entities(
            "SELECT * FROM map_entity WHERE entity_name = 'stone-furnace' LIMIT 1"
        )
        assert len(entities) > 0
        furnace = entities[0]
        
        # TODO: Add remove_entity method to TestGround helper
        # Remove the entity from the game (but RemoteView still has it)
        # dsl_context.test_ground.remove_entity("stone-furnace", 40, 40)
        
        # Act & Assert - should raise WalkingEntityNotFoundError
        # with pytest.raises(WalkingEntityNotFoundError):
        #     await furnace.walk_to(timeout=5)

    @pytest.mark.skip(reason="Need tile placement and agent teleport methods")
    async def test_remote_entity_walk_to_unreachable(self, dsl_context):
        """walk_to() should raise error when entity is unreachable."""
        # Arrange - place entity and surround with water
        dsl_context.test_ground.place_entity("iron-chest", 100, 100)
        # TODO: Add set_tile method to TestGround helper
        # Surround with water tiles (create barrier)
        # for dx in range(-3, 4):
        #     for dy in range(-3, 4):
        #         if abs(dx) == 3 or abs(dy) == 3:
        #             dsl_context.test_ground.set_tile("water", 100 + dx, 100 + dy)
        
        # dsl_context.test_ground.force_resnapshot()
        # dsl_context.runtime.remote_view.rebuild()
        
        # TODO: Add teleport_agent method to TestGround helper
        # Teleport agent outside the water barrier
        # dsl_context.test_ground.teleport_agent(90, 90)
        
        # Query entity
        # entities = dsl_context.runtime.remote_view.get_entities(
        #     "SELECT * FROM map_entity WHERE entity_name = 'iron-chest' LIMIT 1"
        # )
        # assert len(entities) > 0
        # chest = entities[0]
        
        # Act & Assert - should raise WalkingUnreachableError
        # with pytest.raises(WalkingUnreachableError):
        #     await chest.walk_to(timeout=5)


class TestRemoteResourceWalking:
    """Tests for walk_to() on resources from RemoteView queries."""

    async def test_remote_resource_has_walk_to_method(self, dsl_context):
        """Remote resources from remote_view queries should have walk_to() method."""
        # Arrange - place resource patch
        dsl_context.test_ground.place_resource_patch("iron-ore", 60, 60, size=10)
        dsl_context.test_ground.force_resnapshot()
        
        # Wait for snapshots to be written
        await asyncio.sleep(2)
        
        dsl_context.runtime.remote_view.rebuild()
        
        # Act - query via RemoteView
        resources = dsl_context.runtime.remote_view.get_resources(
            "SELECT * FROM resource_tile WHERE name = 'iron-ore' LIMIT 1"
        )
        
        # Assert - should have walk_to method
        assert len(resources) > 0
        resource = resources[0]
        assert hasattr(resource, "walk_to")
        assert callable(resource.walk_to)

    @pytest.mark.skip(reason="Need agent teleport method in TestGround")
    async def test_remote_resource_walk_to_success(self, dsl_context):
        """walk_to() on remote resource should navigate to the resource."""
        # Arrange - place resource patch and teleport agent away
        dsl_context.test_ground.place_resource_patch("coal", 70, 70, size=10)
        # TODO: Add teleport_agent method to TestGround helper
        # dsl_context.test_ground.teleport_agent(0, 0)
        dsl_context.test_ground.force_resnapshot()
        dsl_context.runtime.remote_view.rebuild()
        
        # Query resource via RemoteView
        resources = dsl_context.runtime.remote_view.get_resources(
            "SELECT * FROM resource_tile WHERE name = 'coal' LIMIT 1"
        )
        assert len(resources) > 0
        coal = resources[0]
        
        # Act - walk to the resource
        # final_pos = await coal.walk_to(timeout=10)
        
        # Assert - agent should be near the resource
        # assert final_pos is not None
        # coal_pos = coal.position
        # distance = ((final_pos.x - coal_pos.x) ** 2 + (final_pos.y - coal_pos.y) ** 2) ** 0.5
        # assert distance < 10, f"Agent too far from resource: {distance}"

    async def test_remote_resource_mining_blocked(self, dsl_context):
        """Remote resources should not allow mining directly."""
        # Arrange - place resource patch
        dsl_context.test_ground.place_resource_patch("iron-ore", 80, 80, size=10)
        dsl_context.test_ground.force_resnapshot()
        dsl_context.runtime.remote_view.rebuild()
        
        # Query resource
        resources = dsl_context.runtime.remote_view.get_resources(
            "SELECT * FROM resource_tile WHERE name = 'iron-ore' LIMIT 1"
        )
        assert len(resources) > 0
        iron = resources[0]
        
        # Act & Assert - mining should be blocked
        with pytest.raises(AttributeError) as exc_info:
            await iron.mine()
        
        assert "does not support 'mine'" in str(exc_info.value)
        assert "read-only view" in str(exc_info.value)


class TestReachableEntityNoWalking:
    """Tests verifying reachable entities don't encourage redundant walking."""

    async def test_reachable_entity_is_already_reachable(self, dsl_context):
        """Reachable entities are by definition already in range."""
        # Arrange - place entity near agent (agent starts at origin by default)
        dsl_context.test_ground.place_entity("stone-furnace", 2, 2)
        
        # Act - get reachable entity
        furnace = dsl_context.reachable.get_entity("stone-furnace")
        
        # Assert - entity is in reachable range
        assert furnace is not None
        assert furnace.position.x == 2
        assert furnace.position.y == 2
        
        # Note: Reachable entities may still have walk_to() injected,
        # but the implementation summary says they should not expose it.
        # This test documents expected behavior - calling walk_to on a
        # reachable entity should be discouraged (or blocked).


class TestWalkingActionInjection:
    """Tests verifying DI pipeline passes walking_action through query system."""

    async def test_remote_view_injects_walking_action(self, dsl_context):
        """QueryExecutor should inject walking_action into entities."""
        # Arrange - place entity
        dsl_context.test_ground.place_entity("iron-chest", 50, 50)
        dsl_context.test_ground.force_resnapshot()
        dsl_context.runtime.remote_view.rebuild()
        
        # Act - query entity
        entities = dsl_context.runtime.remote_view.get_entities(
            "SELECT * FROM map_entity WHERE entity_name = 'iron-chest' LIMIT 1"
        )
        
        # Assert - entity should have walking_action injected
        assert len(entities) > 0
        entity = entities[0]
        
        # Check that _walking_action is properly injected
        assert hasattr(entity, "_walking_action")
        assert entity._walking_action is not None
        
        # Verify it's the same instance from runtime
        assert entity._walking_action is dsl_context.runtime.walking

    async def test_resource_query_injects_walking_action(self, dsl_context):
        """QueryExecutor should inject walking_action into resources."""
        # Arrange - place resource
        dsl_context.test_ground.place_resource_patch("copper-ore", 60, 60, size=10)
        dsl_context.test_ground.force_resnapshot()
        dsl_context.runtime.remote_view.rebuild()
        
        # Act - query resource
        resources = dsl_context.runtime.remote_view.get_resources(
            "SELECT * FROM resource_tile WHERE name = 'copper-ore' LIMIT 1"
        )
        
        # Assert - resource wrapper should have walking_action
        assert len(resources) > 0
        resource = resources[0]
        
        # Resources with REMOTE view have _walking_action
        assert hasattr(resource, "_walking_action")
        assert resource._walking_action is not None
        assert resource._walking_action is dsl_context.runtime.walking


class TestWalkingErrorHandling:
    """Tests for walking failure diagnostics."""

    @pytest.mark.skip(reason="Need entity removal method in TestGround")
    async def test_entity_not_found_error_message(self, dsl_context):
        """WalkingEntityNotFoundError should have helpful message."""
        # Arrange - create stale entity reference
        dsl_context.test_ground.place_entity("stone-furnace", 45, 45)
        dsl_context.test_ground.force_resnapshot()
        dsl_context.runtime.remote_view.rebuild()
        
        entities = dsl_context.runtime.remote_view.get_entities(
            "SELECT * FROM map_entity WHERE entity_name = 'stone-furnace' LIMIT 1"
        )
        furnace = entities[0]
        
        # TODO: Add remove_entity method to TestGround helper
        # Remove entity
        # dsl_context.test_ground.remove_entity("stone-furnace", 45, 45)
        
        # Act & Assert
        # with pytest.raises(WalkingEntityNotFoundError) as exc_info:
        #     await furnace.walk_to(timeout=5)
        
        # error = exc_info.value
        # assert "stone-furnace" in str(error) or "entity" in str(error).lower()

    @pytest.mark.skip(reason="Need tile placement and agent teleport methods")
    async def test_unreachable_error_message(self, dsl_context):
        """WalkingUnreachableError should have helpful message."""
        # Arrange - create unreachable entity
        dsl_context.test_ground.place_entity("iron-chest", 120, 120)
        # TODO: Add set_tile and teleport_agent methods to TestGround helper
        # Surround with impassable terrain
        # for dx in range(-5, 6):
        #     for dy in range(-5, 6):
        #         if abs(dx) >= 4 or abs(dy) >= 4:
        #             dsl_context.test_ground.set_tile("water", 120 + dx, 120 + dy)
        
        # dsl_context.test_ground.teleport_agent(100, 100)
        # dsl_context.test_ground.force_resnapshot()
        # dsl_context.runtime.remote_view.rebuild()
        
        # entities = dsl_context.runtime.remote_view.get_entities(
        #     "SELECT * FROM map_entity WHERE entity_name = 'iron-chest' LIMIT 1"
        # )
        # chest = entities[0]
        
        # Act & Assert
        # with pytest.raises(WalkingUnreachableError) as exc_info:
        #     await chest.walk_to(timeout=5)
        
        # error = exc_info.value
        # Error should contain helpful message
        # assert error is not None


class TestMultipleEntityQueries:
    """Tests for bulk entity queries with walking."""

    async def test_multiple_entities_all_have_walk_to(self, dsl_context):
        """All entities from bulk query should have walk_to() method."""
        # Arrange - place multiple entities
        for i in range(5):
            dsl_context.test_ground.place_entity("iron-chest", 50 + i * 5, 50)
        
        dsl_context.test_ground.force_resnapshot()
        dsl_context.runtime.remote_view.rebuild()
        
        # Act - query all chests
        chests = dsl_context.runtime.remote_view.get_entities(
            "SELECT * FROM map_entity WHERE entity_name = 'iron-chest'"
        )
        
        # Assert - all should have walk_to
        assert len(chests) >= 5
        for chest in chests:
            assert hasattr(chest, "walk_to")
            assert callable(chest.walk_to)

    @pytest.mark.skip(reason="Need agent teleport method in TestGround")
    async def test_walk_to_multiple_entities_sequentially(self, dsl_context):
        """Should be able to walk to multiple entities in sequence."""
        # Arrange - place multiple entities in a line
        positions = [(30, 30), (40, 30), (50, 30)]
        for x, y in positions:
            dsl_context.test_ground.place_entity("iron-chest", x, y)
        
        # TODO: Add teleport_agent method to TestGround helper
        # dsl_context.test_ground.teleport_agent(20, 30)
        dsl_context.test_ground.force_resnapshot()
        dsl_context.runtime.remote_view.rebuild()
        
        # Query entities
        chests = dsl_context.runtime.remote_view.get_entities(
            "SELECT * FROM map_entity WHERE entity_name = 'iron-chest' ORDER BY x"
        )
        
        assert len(chests) >= 3
        
        # Act - walk to each chest in sequence
        # for i, chest in enumerate(chests[:3]):
        #     final_pos = await chest.walk_to(timeout=10)
        #     
        #     # Assert - should be near the target
        #     target_x, target_y = positions[i]
        #     distance = ((final_pos.x - target_x) ** 2 + (final_pos.y - target_y) ** 2) ** 0.5
        #     assert distance < 10, f"Agent too far from chest {i}: {distance}"


class TestCrossModuleIntegration:
    """Integration tests verifying the full DI pipeline."""

    async def test_runtime_to_remote_view_pipeline(self, dsl_context):
        """Verify actions flow from AgentRuntime -> RemoteView -> QueryExecutor -> Entity."""
        # This test validates the full dependency injection chain:
        # 1. AgentRuntime creates actions
        # 2. RemoteView receives actions in constructor
        # 3. QueryExecutor receives actions from RemoteView
        # 4. Factory functions inject actions into entities
        
        # Arrange
        runtime = dsl_context.runtime
        
        # Assert - runtime has walking action
        assert hasattr(runtime, "walking")
        walking_action = runtime.walking
        
        # Assert - remote_view has reference to walking_action
        assert hasattr(runtime.remote_view, "_walking_action")
        assert runtime.remote_view._walking_action is walking_action
        
        # Assert - query executor has walking_action
        query_executor = runtime.remote_view._query
        if query_executor:  # May be None if not loaded yet
            assert hasattr(query_executor, "_walking_action")
            assert query_executor._walking_action is walking_action

    @pytest.mark.skip(reason="Need agent teleport method in TestGround")
    async def test_end_to_end_workflow(self, dsl_context):
        """Full workflow: query remote entity, walk to it, then interact with it."""
        # Arrange - place entity far away
        dsl_context.test_ground.place_entity("stone-furnace", 80, 80)
        # TODO: Add teleport_agent method to TestGround helper
        # dsl_context.test_ground.teleport_agent(0, 0)
        dsl_context.test_ground.force_resnapshot()
        dsl_context.runtime.remote_view.rebuild()
        
        # Step 1: Query via RemoteView
        remote_entities = dsl_context.runtime.remote_view.get_entities(
            "SELECT * FROM map_entity WHERE entity_name = 'stone-furnace' LIMIT 1"
        )
        assert len(remote_entities) > 0
        remote_furnace = remote_entities[0]
        
        # Step 2: Walk to remote entity
        # await remote_furnace.walk_to(timeout=10)
        
        # Step 3: Now get it as reachable entity for interaction
        # reachable_furnace = dsl_context.reachable.get_entity("stone-furnace")
        # assert reachable_furnace is not None
        
        # Step 4: Interact with reachable entity
        # info = reachable_furnace.inspect()
        # assert info is not None
        # assert "furnace" in info.lower() or "stone-furnace" in info.lower()
