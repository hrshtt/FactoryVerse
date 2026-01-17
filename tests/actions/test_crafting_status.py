import pytest
import asyncio
import json
from FactoryVerse.environment.environment import Environment


@pytest.mark.asyncio
class TestCraftingStatus:
    """Test crafting.status() returns proper queue information."""

    async def test_status_returns_typed_queue(self, environment: Environment):
        """status() should return CraftingQueueStatus with queue details."""
        # Setup: Ensure agent has items
        agent_id_str = environment.tier4.agent_id
        # Extract ID number (legacy admin.add_items expects integer index)
        agent_index = int(agent_id_str.split("_")[-1]) if "_" in agent_id_str else 1

        items = {"iron-plate": 20}

        # Add items via RCON admin interface
        # admin.add_items takes positional args: agent_id, items_table
        # Use direct Lua table syntax and wrap in rcon.print to verify success
        # The return value from add_items is a table {success=true, ...}
        # We need to print it as JSON to receive it back
        cmd = f"/c rcon.print(helpers.table_to_json(remote.call('admin', 'add_items', {agent_index}, {{['iron-plate'] = 20}})))"
        res = environment.tier3.rcon_helper.rcon_client.send_command(cmd)
        print(f"DEBUG add_items result: {res}")
        assert "success" in res, f"add_items failed: {res}"

        crafting_action = environment.tier4.embodied_actions["crafting"]

        # Get initial status (should be empty)
        status = crafting_action.status()

        # Verify type structure
        assert isinstance(status, dict), "Should return a dict"
        assert "queue" in status, "Should have 'queue' field"
        assert len(status["queue"]) == 0, "Queue should be empty initially"

    async def test_status_with_queued_items(self, environment: Environment):
        """status() should return queue items when crafting is queued."""
        agent_id_str = environment.tier4.agent_id
        agent_index = int(agent_id_str.split("_")[-1]) if "_" in agent_id_str else 1

        # Add ingredients for gears
        # Use direct Lua table syntax
        cmd = f"/c rcon.print(helpers.table_to_json(remote.call('admin', 'add_items', {agent_index}, {{['iron-plate'] = 20}})))"
        res = environment.tier3.rcon_helper.rcon_client.send_command(cmd)
        print(f"DEBUG add_items result: {res}")
        assert "success" in res, f"add_items failed: {res}"

        crafting_action = environment.tier4.embodied_actions["crafting"]

        # Enqueue crafting
        # Note: enqueue returns a dict, we need to inspect it
        result = crafting_action.enqueue("iron-gear-wheel", count=5)
        # enqueue result is typically {'queued': True} or error
        assert result.get("queued") is True, f"Enqueue failed: {result}"

        # Wait for queue update (Factorio tick cycle)
        await asyncio.sleep(0.5)

        # Get status
        status = crafting_action.status()

        # Verify queue has items
        assert "queue" in status
        # Note: If crafting is very fast, queue might be empty again.
        # But iron-gear-wheel takes 0.5s, 5 of them takes 2.5s.
        # So we should see them in queue.
        assert len(status["queue"]) > 0, "Queue shouldn't be empty while crafting"
        item = status["queue"][0]
        # Check recipe name (might be normalized)
        assert item["recipe"] == "iron-gear-wheel"
        assert item["count"] > 0
