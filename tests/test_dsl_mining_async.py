"""
Asynchronous DSL Mining Operation Tests

Tests for mining operations using the async/await pattern.
Verifies that the agent can mine resources and receive completion notifications via UDP.
"""

import pytest
import json
import time
import asyncio
from FactoryVerse.dsl.agent import PlayingFactory
from FactoryVerse.dsl.agent import MapPosition

@pytest.mark.asyncio
@pytest.mark.dsl
class TestAsyncMining:
    """Test DSL mining operations using async/await."""

    async def test_async_mine_simple(self, factory_instance: PlayingFactory, test_ground):
        """Test mining a nearby resource (tree)."""
        # Place a tree
        test_ground.place_entity("tree-01", x=0, y=1)
        factory_instance._rcon.send_command('/c remote.call("agent_1", "teleport", {x=0, y=0})')
        
        # Mine it
        # Clear inventory first
        factory_instance._rcon.send_command('/c remote.call("agent_1", "clear_inventory")')
        
        # Use generic "tree" name or specific prototype
        result = await factory_instance.mining.mine("tree-01", timeout=30)
        
        # Check result payload
        assert len(result) > 0
        assert result[0].name == "wood"
        
        # Verify inventory
        inv = factory_instance.inventory.get_total("wood")
        assert inv > 0

    async def test_async_mine_until_depleted(self, factory_instance: PlayingFactory, test_ground):
        """Test mining a small resource until it is gone."""
        # Create a tiny 1x1 rock - use correct name 'huge-rock'
        test_ground.place_entity("huge-rock", x=5, y=5)
        factory_instance._rcon.send_command('/c remote.call("agent_1", "teleport", {x=5, y=5})')
        
        # Mine it
        await factory_instance.mining.mine("huge-rock") # No max_count = deplete
        
        # Verify it's gone
        res = factory_instance._rcon.send_command('/c rcon.print(#game.surfaces[1].find_entities_filtered{name="huge-rock", position={5,5}})')
        assert int(res) == 0

    async def test_async_mine_cancel(self, factory_instance: PlayingFactory, test_ground):
        """Test cancelling a mining operation."""
        # Place iron-ore
        test_ground.place_iron_patch(x=10, y=10, size=2, amount=1000)
        factory_instance._rcon.send_command('/c remote.call("agent_1", "teleport", {x=10, y=10})')
        
        # We'll use a larger count to ensure it's in progress
        resp = factory_instance.mining._factory.mine_resource("iron-ore", max_count=100)
        assert resp["queued"] is True
        
        # Stop mining immediately
        stop_resp = factory_instance.mining._factory.stop_mining()
        assert stop_resp["reason"] == "cancelled"
        # success is False for cancellation in the mod
        assert stop_resp["success"] is False
