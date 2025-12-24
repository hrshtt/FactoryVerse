"""
Asynchronous DSL Walking/Movement Operation Tests

Tests for movement operations using the async/await pattern.
Verifies that the agent can navigate to target positions.
"""

import pytest
import math
import json
from FactoryVerse.dsl.agent import PlayingFactory

def get_agent_position(factory: PlayingFactory):
    """Helper to get agent position."""
    res_str = factory.inspect(attach_state=False)
    res = json.loads(res_str)
    return res["position"]

def calculate_distance(pos1, pos2):
    """Helper to calculate Euclidean distance."""
    return math.sqrt((pos1["x"] - pos2["x"])**2 + (pos1["y"] - pos2["y"])**2)

@pytest.mark.asyncio
@pytest.mark.dsl
class TestAsyncWalking:
    """Test DSL walking operations using async/await."""

    async def test_async_walk_simple(self, factory_instance: PlayingFactory):
        """Test simple walking to a nearby coordinate."""
        # Start at (0, 0) - teleport to ensure clean state
        factory_instance._rcon.send_command('/c remote.call("agent_1", "teleport", {x=0, y=0})')
        
        target = {"x": 10, "y": 10}
        await factory_instance.walking.to(target)
        
        current_pos = get_agent_position(factory_instance)
        # Factorio walking isn't always pixel-perfect, allow small epsilon
        assert calculate_distance(current_pos, target) < 1.0

    async def test_async_walk_long_distance(self, factory_instance: PlayingFactory):
        """Test walking to a further coordinate."""
        factory_instance._rcon.send_command('/c remote.call("agent_1", "teleport", {x=0, y=0})')
        
        target = {"x": 50, "y": -50}
        # This will take several seconds
        await factory_instance.walking.to(target)
        
        current_pos = get_agent_position(factory_instance)
        assert calculate_distance(current_pos, target) < 1.5

    async def test_async_walk_with_obstacles(self, factory_instance: PlayingFactory, test_ground):
        """Test walking when there are obstacles in the way."""
        factory_instance._rcon.send_command('/c remote.call("agent_1", "teleport", {x=0, y=0})')
        
        # Place a wall of entities
        for y in range(-5, 6):
            test_ground.place_entity("stone-wall", x=5, y=y)
        
        # Target is on the other side of the wall
        target = {"x": 10, "y": 0}
        await factory_instance.walking.to(target)
        
        current_pos = get_agent_position(factory_instance)
        assert calculate_distance(current_pos, target) < 1.5
        
        # Cleanup walls
        factory_instance._rcon.send_command('/c for _, e in pairs(game.surfaces[1].find_entities_filtered{name="stone-wall"}) do e.destroy() end')

    async def test_async_walk_to_entity(self, factory_instance: PlayingFactory, test_ground):
        """Test walking to a specific entity."""
        factory_instance._rcon.send_command('/c remote.call("agent_1", "teleport", {x=0, y=0})')
        
        # Place a furnace at (20, 20)
        test_ground.place_entity("stone-furnace", x=20, y=20)
        
        # In DSL, we usually find the entity first. For now, we'll walk to its position.
        target = {"x": 20, "y": 20}
        await factory_instance.walking.to(target)
        
        current_pos = get_agent_position(factory_instance)
        # Should be at the edge of the furnace (size 2x2)
        assert calculate_distance(current_pos, target) < 3.0
        
        # Cleanup
        factory_instance._rcon.send_command('/c for _, e in pairs(game.surfaces[1].find_entities_filtered{name="stone-furnace"}) do e.destroy() end')
