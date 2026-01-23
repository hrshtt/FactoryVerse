"""Tests for crafting queue API in Lua mod.

Tests the get_crafting_queue remote interface method.

NOTE: Mod changes require server restart. If tests fail, restart the Factorio server
to load the latest mod code from src/fv_embodied_agent/.
"""

import pytest
import json


class TestCraftingQueueAPI:
    """Test get_crafting_queue remote interface."""
    
    def setup_method(self):
        """Reload scripts to pick up mod changes."""
        # Note: This will only work if the mod files have been copied to the Factorio mod directory
        # For full mod changes, the server needs to be restarted
        pass

    def test_get_crafting_queue_interface_exists(self, rcon, agent_id):
        """Verify get_crafting_queue remote interface is registered."""
        # Check that the per-agent interface exists
        # The agent_id is the interface name (e.g., "agent_1")
        cmd = f'/c rcon.print(helpers.table_to_json(remote.interfaces["{agent_id}"]))'
        result = rcon.client.send_command(cmd)
        agent_interface = json.loads(result)
        
        # Verify get_crafting_queue method exists in the per-agent interface
        assert "get_crafting_queue" in agent_interface, \
            f"get_crafting_queue method should be registered in {agent_id} interface. Found: {list(agent_interface.keys())}"
        
        print(f"✅ get_crafting_queue interface found in {agent_id}")

    def test_get_crafting_queue_empty_queue(self, rcon, agent_id):
        """Test get_crafting_queue with empty queue."""
        # Call get_crafting_queue via RCON
        cmd = f'/c rcon.print(helpers.table_to_json(remote.call("{agent_id}", "get_crafting_queue")))'
        result = rcon.client.send_command(cmd)
        queue_data = json.loads(result)
        
        # Verify structure
        assert "queue" in queue_data, "Should have 'queue' field"
        assert "queue_size" in queue_data, "Should have 'queue_size' field"
        assert "progress" in queue_data, "Should have 'progress' field"
        
        # Verify empty queue
        assert queue_data["queue_size"] == 0, "Queue should be empty"
        assert len(queue_data["queue"]) == 0, "Queue array should be empty"
        assert queue_data["progress"] == 0.0, "Progress should be 0.0"
        
        print(f"✅ Empty queue test passed: {queue_data}")

    def test_get_crafting_queue_with_items(self, rcon, agent_id, admin):
        """Test get_crafting_queue with items in queue."""
        agent_idx = int(agent_id.split("_")[1])
        
        # Give agent ingredients
        admin.add_items(agent_idx, {"iron-plate": 20})
        
        # Enqueue crafting
        enqueue_cmd = f'/c rcon.print(helpers.table_to_json(remote.call("{agent_id}", "craft_enqueue", "iron-gear-wheel", 5)))'
        enqueue_result = rcon.client.send_command(enqueue_cmd)
        enqueue_data = json.loads(enqueue_result)
        
        assert enqueue_data.get("queued") == True, "Crafting should be queued"
        
        # Wait a brief moment for queue to update
        import time
        time.sleep(0.1)
        
        # Get queue status
        queue_cmd = f'/c rcon.print(helpers.table_to_json(remote.call("{agent_id}", "get_crafting_queue")))'
        queue_result = rcon.client.send_command(queue_cmd)
        queue_data = json.loads(queue_result)
        
        # Debug: Print the actual structure
        print(f"DEBUG: Queue data: {queue_data}")
        
        # Verify structure
        assert "queue" in queue_data, "Should have 'queue' field"
        assert "queue_size" in queue_data, "Should have 'queue_size' field"
        assert "progress" in queue_data, "Should have 'progress' field"
        
        # Verify queue has items
        assert queue_data["queue_size"] > 0, "Queue should have items"
        assert len(queue_data["queue"]) > 0, "Queue array should have items"
        
        # Verify queue item structure
        if len(queue_data["queue"]) > 0:
            item = queue_data["queue"][0]
            print(f"DEBUG: Queue item: {item}")
            assert "index" in item, "Queue item should have 'index'"
            assert "count" in item, "Queue item should have 'count'"
            assert "prerequisite" in item, "Queue item should have 'prerequisite'"
            # Recipe might be empty if queue item structure is different
            if "recipe" in item:
                assert item["recipe"] == "iron-gear-wheel", f"Recipe should match, got: {item.get('recipe')}"
            else:
                # Debug: Check what the actual queue item looks like in Lua
                debug_cmd = f'/c local agent = remote.call("agent", "get_agent", {agent_idx}); local char = agent.character; local q = char.crafting_queue; if q and q[1] then local item = q[1]; rcon.print(helpers.table_to_json({{recipe_obj = tostring(item.recipe), recipe_name = item.recipe and item.recipe.name or "nil", has_recipe = item.recipe ~= nil, recipe_type = type(item.recipe), index = item.index, count = item.count}})) else rcon.print(helpers.table_to_json({{error = "no queue"}})) end'
                debug_result = rcon.client.send_command(debug_cmd)
                debug_data = json.loads(debug_result)
                print(f"DEBUG: Queue item structure: {debug_data}")
                pytest.fail(f"Recipe field missing from queue item. Debug: {debug_data}")
        
        print(f"✅ Queue with items test passed: {queue_data}")
