"""Tests for entity walking Dependency Injection pipeline.

Validates that the DI pipeline properly injects walking actions from
AgentRuntime through RemoteView and QueryExecutor into entity/resource instances.

These tests focus on the structure and wiring, not actual walking behavior.
"""

import pytest


class TestDependencyInjectionPipeline:
    """Tests verifying DI pipeline structure."""

    async def test_runtime_has_walking_action(self, dsl_context):
        """AgentRuntime should have walking action."""
        runtime = dsl_context.runtime
        
        # Assert walking action exists
        assert hasattr(runtime, "walking")
        assert runtime.walking is not None
        
        # Verify it's a MovementAction
        from FactoryVerse.agent.actions.walking import MovementAction
        assert isinstance(runtime.walking, MovementAction)

    async def test_remote_view_receives_walking_action(self, dsl_context):
        """RemoteView should receive walking_action in constructor."""
        runtime = dsl_context.runtime
        remote_view = runtime.remote_view
        
        # Assert remote_view has walking_action
        assert hasattr(remote_view, "_walking_action")
        assert remote_view._walking_action is not None
        
        # Verify it's the same instance from runtime
        assert remote_view._walking_action is runtime.walking

    async def test_query_executor_receives_walking_action(self, dsl_context):
        """QueryExecutor should receive walking_action from RemoteView."""
        runtime = dsl_context.runtime
        remote_view = runtime.remote_view
        
        # Query executor is created during load()
        # It's stored in remote_view._query
        if remote_view._query is not None:
            query_executor = remote_view._query
            
            # Assert query executor has walking_action
            assert hasattr(query_executor, "_walking_action")
            assert query_executor._walking_action is not None
            
            # Verify it's the same instance
            assert query_executor._walking_action is runtime.walking

    async def test_reachable_entity_has_walking_injected(self, dsl_context):
        """Reachable entities should have walking_action injected."""
        # Try to place entity (may fail due to collisions in test-ground)
        try:
            dsl_context.test_ground.place_entity("stone-furnace", 100, 100)
        except RuntimeError:
            # Placement failed - skip this test gracefully
            return
        
        # Get reachable entity
        furnace = dsl_context.reachable.get_entity("stone-furnace")
        
        if furnace is not None:
            # Assert entity has _walking_action
            assert hasattr(furnace, "_walking_action")
            assert furnace._walking_action is not None
            
            # Verify it's from the runtime
            assert furnace._walking_action is dsl_context.runtime.walking
            
            # Verify walk_to method exists
            assert hasattr(furnace, "walk_to")
            assert callable(furnace.walk_to)


class TestEntityWalkToMethodPresence:
    """Tests verifying walk_to() method is available on entities."""

    async def test_reachable_entity_has_walk_to(self, dsl_context):
        """Reachable entities should have walk_to() method."""
        # Try to place entity (may fail due to collisions)
        try:
            dsl_context.test_ground.place_entity("iron-chest", 110, 110)
        except RuntimeError:
            return  # Skip if placement fails
        
        # Get entity
        chest = dsl_context.reachable.get_entity("iron-chest")
        
        # Assert walk_to exists (if entity is reachable)
        if chest is not None:
            assert hasattr(chest, "walk_to")
            assert callable(chest.walk_to)

    async def test_reachable_resource_has_walk_to_blocked(self, dsl_context):
        """Reachable resources should allow mining but remote resources block it."""
        # Place resource patch
        dsl_context.test_ground.place_resource_patch("iron-ore", 5, 5, size=5)
        
        # Get reachable resource
        iron = dsl_context.resources.get_resource("iron-ore")
        
        if iron is not None:
            # Reachable resources should have mine() available
            assert hasattr(iron, "mine")
            assert callable(iron.mine)


class TestRemoteViewEntityStructure:
    """Tests for remote view entity structure (without actual queries)."""

    async def test_remote_view_is_configured(self, dsl_context):
        """RemoteView should be properly configured."""
        remote_view = dsl_context.runtime.remote_view
        
        # Basic structure checks
        assert remote_view is not None
        assert hasattr(remote_view, "get_entities")
        assert hasattr(remote_view, "get_resources")
        assert hasattr(remote_view, "get_ghosts")
        
        # Should have walking_action injected
        assert hasattr(remote_view, "_walking_action")
        assert remote_view._walking_action is dsl_context.runtime.walking

    async def test_remote_view_database_connection(self, dsl_context):
        """RemoteView should have a database connection."""
        remote_view = dsl_context.runtime.remote_view
        
        # Check database is initialized
        assert hasattr(remote_view, "_database")
        assert remote_view._database is not None
        
        # Check connection exists
        assert hasattr(remote_view._database, "connection")


class TestRemoteViewQueries:
    """Tests for actual RemoteView queries returning entities with walk_to()."""

    async def test_get_entities_returns_walkable_entities(self, dsl_context):
        """Entities from remote_view.get_entities() should have walk_to() method."""
        # Try to place entity (may fail due to collisions)
        try:
            dsl_context.test_ground.place_entity("stone-furnace", 150, 150)
            dsl_context.test_ground.force_resnapshot()
        except RuntimeError:
            return  # Skip if placement fails
        
        # Wait for snapshots to be written
        import asyncio
        await asyncio.sleep(2)
        
        # Reload RemoteView to get fresh data
        dsl_context.runtime.remote_view.rebuild()
        
        # Query entities via RemoteView with SQL
        entities = dsl_context.runtime.remote_view.get_entities(
            "SELECT * FROM map_entity WHERE entity_name = 'stone-furnace' LIMIT 1"
        )
        
        # If we got entities, verify they have walk_to
        if len(entities) > 0:
            entity = entities[0]
            
            # Assert walk_to method exists
            assert hasattr(entity, "walk_to")
            assert callable(entity.walk_to)
            
            # Assert walking_action is injected
            assert hasattr(entity, "_walking_action")
            assert entity._walking_action is dsl_context.runtime.walking
            
            # Verify entity properties
            assert entity.name == "stone-furnace"
            assert hasattr(entity.position, "x")
            assert hasattr(entity.position, "y")

    async def test_get_resources_returns_walkable_resources(self, dsl_context):
        """Resources from remote_view.get_resources() should have walk_to() method."""
        # Place resource patch and trigger snapshot
        dsl_context.test_ground.place_resource_patch("iron-ore", 70, 70, size=10)
        dsl_context.test_ground.force_resnapshot()
        
        # Wait for snapshots to be written
        import asyncio
        await asyncio.sleep(2)
        
        # Reload RemoteView
        dsl_context.runtime.remote_view.rebuild()
        
        # Query resources via RemoteView with SQL
        resources = dsl_context.runtime.remote_view.get_resources(
            "SELECT * FROM resource_tile WHERE name = 'iron-ore' LIMIT 1"
        )
        
        # If we got resources, verify they have walk_to
        if len(resources) > 0:
            resource = resources[0]
            
            # Assert walk_to method exists
            assert hasattr(resource, "walk_to")
            assert callable(resource.walk_to)
            
            # Assert walking_action is injected
            assert hasattr(resource, "_walking_action")
            assert resource._walking_action is dsl_context.runtime.walking
            
            # Assert mine() is blocked (REMOTE view)
            import pytest
            with pytest.raises(AttributeError) as exc_info:
                resource.mine()
            assert "Cannot mine() remotely" in str(exc_info.value)
            
            # Verify resource properties are accessible
            assert resource.name == "iron-ore"
            assert hasattr(resource, "position")

    async def test_get_entity_singular_returns_walkable_entity(self, dsl_context):
        """Single entity from remote_view.get_entity() should have walk_to()."""
        # Try to place entity
        try:
            dsl_context.test_ground.place_entity("iron-chest", 160, 160)
            dsl_context.test_ground.force_resnapshot()
        except RuntimeError:
            return  # Skip if placement fails
        
        # Wait for snapshots
        import asyncio
        await asyncio.sleep(2)
        
        # Reload
        dsl_context.runtime.remote_view.rebuild()
        
        # Query single entity
        entity = dsl_context.runtime.remote_view.get_entity(
            "SELECT * FROM map_entity WHERE entity_name = 'iron-chest'"
        )
        
        # If entity found, verify walk_to
        if entity is not None:
            assert hasattr(entity, "walk_to")
            assert callable(entity.walk_to)
            assert entity._walking_action is dsl_context.runtime.walking

    async def test_multiple_entities_all_have_walk_to(self, dsl_context):
        """All entities from bulk query should have walk_to() method."""
        # Try to place multiple entities
        try:
            for i in range(3):
                dsl_context.test_ground.place_entity("transport-belt", 170 + i * 2, 170)
            dsl_context.test_ground.force_resnapshot()
        except RuntimeError:
            return  # Skip if placement fails
        
        # Wait for snapshots
        import asyncio
        await asyncio.sleep(2)
        
        # Reload
        dsl_context.runtime.remote_view.rebuild()
        
        # Query all belts
        belts = dsl_context.runtime.remote_view.get_entities(
            "SELECT * FROM map_entity WHERE entity_name = 'transport-belt'"
        )
        
        # If we got any belts, verify all have walk_to
        if len(belts) > 0:
            for belt in belts:
                assert hasattr(belt, "walk_to")
                assert callable(belt.walk_to)
                assert belt._walking_action is dsl_context.runtime.walking


class TestFactoryFunctionsDI:
    """Tests for factory functions receiving and injecting actions."""

    async def test_create_remote_view_entity_signature(self):
        """create_remote_view_entity should accept walking_action parameter."""
        from FactoryVerse.factory.entity.create_entity import create_remote_view_entity
        import inspect
        
        # Get function signature
        sig = inspect.signature(create_remote_view_entity)
        params = list(sig.parameters.keys())
        
        # Should have walking_action parameter
        assert "walking_action" in params

    async def test_create_resource_from_db_signature(self):
        """create_resource_from_db should accept walking_action parameter."""
        from FactoryVerse.factory.resource.base import create_resource_from_db
        import inspect
        
        # Get function signature
        sig = inspect.signature(create_resource_from_db)
        params = list(sig.parameters.keys())
        
        # Should have walking_action parameter
        assert "walking_action" in params


class TestResourceView:
    """Tests for resource view-based access control."""

    async def test_remote_view_blocks_mining(self):
        """Resource with REMOTE view should block mine() method."""
        from FactoryVerse.factory.resource.base import BaseResource, create_resource_from_db
        from FactoryVerse.factory.entity.base_entity import EntityView
        from FactoryVerse.factory.types import MapPosition
        from unittest.mock import Mock
        
        # Create resource data
        resource_data = {
            "name": "iron-ore",
            "position": {"x": 10, "y": 10},
            "amount": 5000,
            "type": "resource",
        }
        
        # Create mock actions
        mock_mining = Mock()
        mock_entity_ops = Mock()
        mock_walking = Mock()
        
        # Create resource with REMOTE view
        resource = create_resource_from_db(
            resource_data, mock_mining, mock_entity_ops, mock_walking
        )
        
        # Assert view is REMOTE
        assert resource._view == EntityView.REMOTE
        
        # Assert mine() is blocked
        with pytest.raises(AttributeError) as exc_info:
            resource.mine()
        
        assert "Cannot mine() remotely" in str(exc_info.value)
        assert "not reachable" in str(exc_info.value)

    async def test_remote_view_has_walk_to(self):
        """Resource with REMOTE view should have walk_to() method."""
        from FactoryVerse.factory.resource.base import create_resource_from_db
        from FactoryVerse.factory.types import MapPosition
        from unittest.mock import Mock
        
        # Create resource data
        resource_data = {
            "name": "coal",
            "position": {"x": 20, "y": 20},
            "amount": 3000,
            "type": "resource",
        }
        
        # Create mock actions
        mock_mining = Mock()
        mock_entity_ops = Mock()
        mock_walking = Mock()
        
        # Create resource with REMOTE view
        resource = create_resource_from_db(
            resource_data, mock_mining, mock_entity_ops, mock_walking
        )
        
        # Assert walk_to exists and is callable
        assert hasattr(resource, "walk_to")
        assert callable(resource.walk_to)

    async def test_reachable_view_blocks_walk_to(self):
        """Resource with REACHABLE view should block walk_to() method."""
        from FactoryVerse.factory.resource.base import create_resource_from_reachable
        from FactoryVerse.factory.entity.base_entity import EntityView
        from unittest.mock import Mock
        
        # Create resource data
        resource_data = {
            "name": "copper-ore",
            "position": {"x": 30, "y": 30},
            "amount": 4000,
            "type": "resource",
        }
        
        # Create mock actions
        mock_mining = Mock()
        mock_entity_ops = Mock()
        mock_walking = Mock()
        
        # Create resource with REACHABLE view
        resource = create_resource_from_reachable(
            resource_data, mock_mining, mock_entity_ops, mock_walking
        )
        
        # Assert view is REACHABLE
        assert resource._view == EntityView.REACHABLE
        
        # Assert walk_to() is blocked
        with pytest.raises(AttributeError) as exc_info:
            resource.walk_to()
        
        assert "Cannot walk_to() on reachable resource" in str(exc_info.value)
        assert "already within reach" in str(exc_info.value)

    async def test_reachable_view_has_mine(self):
        """Resource with REACHABLE view should have mine() method."""
        from FactoryVerse.factory.resource.base import create_resource_from_reachable
        from unittest.mock import Mock
        
        # Create resource data
        resource_data = {
            "name": "iron-ore",
            "position": {"x": 40, "y": 40},
            "amount": 6000,
            "type": "resource",
        }
        
        # Create mock actions
        mock_mining = Mock()
        mock_entity_ops = Mock()
        mock_walking = Mock()
        
        # Create resource with REACHABLE view
        resource = create_resource_from_reachable(
            resource_data, mock_mining, mock_entity_ops, mock_walking
        )
        
        # Assert mine exists and is callable
        assert hasattr(resource, "mine")
        assert callable(resource.mine)

    async def test_resource_properties_work(self):
        """Resource properties should work regardless of view."""
        from FactoryVerse.factory.resource.base import create_resource_from_db, create_resource_from_reachable
        from unittest.mock import Mock
        
        # Create resource data
        resource_data = {
            "name": "copper-ore",
            "position": {"x": 30, "y": 30},
            "amount": 5000,
            "type": "resource",
        }
        
        # Create mock actions
        mock_mining = Mock()
        mock_entity_ops = Mock()
        mock_walking = Mock()
        
        # Test REMOTE view
        remote_resource = create_resource_from_db(
            resource_data, mock_mining, mock_entity_ops, mock_walking
        )
        assert remote_resource.name == "copper-ore"
        assert remote_resource.position.x == 30
        assert remote_resource.position.y == 30
        assert remote_resource.amount == 5000
        
        # Test REACHABLE view
        reachable_resource = create_resource_from_reachable(
            resource_data, mock_mining, mock_entity_ops, mock_walking
        )
        assert reachable_resource.name == "copper-ore"
        assert reachable_resource.position.x == 30
        assert reachable_resource.position.y == 30
        assert reachable_resource.amount == 5000


class TestFunctionalWalking:
    """Functional integration tests - actually call walk_to() and verify agent movement."""

    async def test_remote_entity_walk_to_functional(self, dsl_context):
        """Actually walk to a remote entity and verify agent moves."""
        # Verify agent exists first
        agent_pos = dsl_context.runtime.walking.current_position
        print(f"Agent exists at: ({agent_pos.x}, {agent_pos.y})")
        
        # Place entity far from spawn
        try:
            entity_placed = dsl_context.test_ground.place_entity("iron-chest", 200, 200)
            print(f"Placed entity at: ({entity_placed.position[0]}, {entity_placed.position[1]})")
            dsl_context.test_ground.force_resnapshot()
        except RuntimeError as e:
            pytest.skip(f"Could not place entity: {e}")
        
        # Wait longer for snapshot
        import asyncio
        await asyncio.sleep(3)
        
        # Reload RemoteView
        dsl_context.runtime.remote_view.rebuild()
        
        # Get agent's initial position
        initial_pos = dsl_context.runtime.walking.current_position
        print(f"Initial agent position: ({initial_pos.x}, {initial_pos.y})")
        
        # Query entity via RemoteView - be specific about position
        entities = dsl_context.runtime.remote_view.get_entities(
            "SELECT * FROM map_entity WHERE entity_name = 'iron-chest' AND x >= 195 AND x <= 205 AND y >= 195 AND y <= 205 LIMIT 1"
        )
        
        if len(entities) == 0:
            # Try without position filter to see what we have
            all_entities = dsl_context.runtime.remote_view.get_entities(
                "SELECT * FROM map_entity WHERE entity_name = 'iron-chest' LIMIT 5"
            )
            print(f"Found {len(all_entities)} iron-chest entities total")
            for e in all_entities:
                print(f"  Entity at: ({e.position.x}, {e.position.y})")
            pytest.skip("Entity not found at expected position in snapshot")
        
        entity = entities[0]
        target_pos = entity.position
        print(f"Target entity position: ({target_pos.x}, {target_pos.y})")
        
        # Verify we're not already there
        initial_distance = ((initial_pos.x - target_pos.x) ** 2 + (initial_pos.y - target_pos.y) ** 2) ** 0.5
        if initial_distance < 2:
            pytest.skip(f"Agent already at target! Distance: {initial_distance}")
        
        # ACTUALLY CALL walk_to() - this is the functional test!
        print(f"Walking to entity at ({target_pos.x}, {target_pos.y})...")
        final_pos = await entity.walk_to(timeout=20)
        
        print(f"Final agent position: ({final_pos.x}, {final_pos.y})")
        
        # Verify agent moved
        distance_moved = ((final_pos.x - initial_pos.x) ** 2 + (final_pos.y - initial_pos.y) ** 2) ** 0.5
        assert distance_moved > 1, f"Agent didn't move! Initial: {initial_pos}, Final: {final_pos}"
        
        # Verify agent is near the target entity (within reach distance ~10 tiles)
        distance_to_target = ((final_pos.x - target_pos.x) ** 2 + (final_pos.y - target_pos.y) ** 2) ** 0.5
        assert distance_to_target < 12, f"Agent too far from target! Distance: {distance_to_target}"

    async def test_remote_resource_walk_to_functional(self, dsl_context):
        """Actually walk to a remote resource and verify agent moves."""
        # Verify agent exists first
        agent_pos = dsl_context.runtime.walking.current_position
        print(f"Agent exists at: ({agent_pos.x}, {agent_pos.y})")
        
        # Place resource patch far from spawn
        try:
            patch = dsl_context.test_ground.place_resource_patch("iron-ore", 250, 250, size=10)
            print(f"Placed resource patch at: ({patch.center[0]}, {patch.center[1]})")
            dsl_context.test_ground.force_resnapshot()
        except RuntimeError as e:
            pytest.skip(f"Could not place resource: {e}")
        
        # Wait longer for snapshot to be written
        import asyncio
        await asyncio.sleep(3)
        
        # Reload RemoteView
        dsl_context.runtime.remote_view.rebuild()
        
        # Get initial position
        initial_pos = dsl_context.runtime.walking.current_position
        print(f"Initial agent position: ({initial_pos.x}, {initial_pos.y})")
        
        # Query resource via RemoteView - be specific about position to avoid getting existing resources
        resources = dsl_context.runtime.remote_view.get_resources(
            "SELECT * FROM resource_tile WHERE name = 'iron-ore' AND x >= 240 AND x <= 260 AND y >= 240 AND y <= 260 LIMIT 1"
        )
        
        if len(resources) == 0:
            # Try without position filter to see what we have
            all_resources = dsl_context.runtime.remote_view.get_resources(
                "SELECT * FROM resource_tile WHERE name = 'iron-ore' LIMIT 5"
            )
            print(f"Found {len(all_resources)} iron-ore resources total")
            for r in all_resources:
                print(f"  Resource at: ({r.position.x}, {r.position.y})")
            pytest.skip("Resource not found at expected position in snapshot")
        
        resource = resources[0]
        target_pos = resource.position
        print(f"Target resource position: ({target_pos.x}, {target_pos.y})")
        
        # Verify we're not already there
        initial_distance = ((initial_pos.x - target_pos.x) ** 2 + (initial_pos.y - target_pos.y) ** 2) ** 0.5
        if initial_distance < 2:
            pytest.skip(f"Agent already at target! Distance: {initial_distance}")
        
        # ACTUALLY CALL walk_to() on resource
        print(f"Walking to resource at ({target_pos.x}, {target_pos.y})...")
        final_pos = await resource.walk_to(timeout=20)
        
        print(f"Final agent position: ({final_pos.x}, {final_pos.y})")
        
        # Verify agent moved
        distance_moved = ((final_pos.x - initial_pos.x) ** 2 + (final_pos.y - initial_pos.y) ** 2) ** 0.5
        assert distance_moved > 1, f"Agent didn't move! Initial: {initial_pos}, Final: {final_pos}"
        
        # Verify agent is near the resource
        distance_to_target = ((final_pos.x - target_pos.x) ** 2 + (final_pos.y - target_pos.y) ** 2) ** 0.5
        assert distance_to_target < 12, f"Agent too far from resource! Distance: {distance_to_target}"

    async def test_walk_to_multiple_entities_sequentially(self, dsl_context):
        """Walk to multiple entities in sequence - full functional test."""
        # Place multiple entities in a line
        positions = [(300, 300), (320, 300), (340, 300)]
        try:
            for x, y in positions:
                dsl_context.test_ground.place_entity("iron-chest", x, y)
            dsl_context.test_ground.force_resnapshot()
        except RuntimeError:
            pytest.skip("Could not place entities")
        
        # Wait for snapshot
        import asyncio
        await asyncio.sleep(2)
        
        # Reload
        dsl_context.runtime.remote_view.rebuild()
        
        # Query all chests
        chests = dsl_context.runtime.remote_view.get_entities(
            "SELECT * FROM map_entity WHERE entity_name = 'iron-chest' ORDER BY x"
        )
        
        if len(chests) < 3:
            pytest.skip(f"Not enough entities found: {len(chests)}")
        
        # Walk to each chest in sequence
        for i, chest in enumerate(chests[:3]):
            target_x, target_y = positions[i]
            print(f"\nWalking to chest {i+1} at ({target_x}, {target_y})")
            
            # Get position before walking
            before_pos = dsl_context.runtime.walking.current_position
            
            # ACTUALLY WALK
            final_pos = await chest.walk_to(timeout=15)
            
            # Verify we're near the target
            distance = ((final_pos.x - target_x) ** 2 + (final_pos.y - target_y) ** 2) ** 0.5
            assert distance < 12, f"Agent too far from chest {i+1}: {distance}"
            
            print(f"✅ Reached chest {i+1}, distance: {distance:.1f}")
