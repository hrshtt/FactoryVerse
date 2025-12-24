"""
Asynchronous DSL Crafting Operation Tests

Tests for crafting operations using the async/await pattern.
Verifies that the DSL correctly awaits game completion events.
"""

import pytest
import asyncio
from FactoryVerse.dsl.agent import PlayingFactory
from helpers.test_ground import TestGround


def get_inventory_count(factory: PlayingFactory, item_name: str) -> int:
    """Helper to get inventory count via agent remote interface."""
    result = factory._rcon.send_command(
        f'/c rcon.print(helpers.table_to_json(remote.call("{factory._agent_id}", "get_inventory_items")))'
    )
    if not result or result.strip() == "":
        return 0
    
    import json
    inventory_data = json.loads(result)
    total = sum(stack.get("count", 0) for stack in inventory_data if stack.get("name") == item_name)
    return total


def add_items(factory: PlayingFactory, items: dict):
    """Helper to add items to inventory via admin interface."""
    items_lua = ", ".join(f'["{name}"]={count}' for name, count in items.items())
    factory._rcon.send_command(
        f'/c remote.call("admin", "add_items", {factory._numeric_agent_id}, {{{items_lua}}})'
    )


def clear_inventory(factory: PlayingFactory):
    """Helper to clear agent inventory."""
    factory._rcon.send_command(
        f'/c remote.call("admin", "clear_inventory", {factory._numeric_agent_id})'
    )


@pytest.mark.asyncio
@pytest.mark.dsl
class TestAsyncCrafting:
    """Test DSL crafting operations using async/await."""
    @pytest.fixture(autouse=True)
    async def speed_up_game(self, factory_instance: PlayingFactory):
        """Speed up game during tests."""
        factory_instance._rcon.send_command("/c game.speed = 100.0")
        yield
        factory_instance._rcon.send_command("/c game.speed = 1.0")


    async def test_async_craft_iron_gear_wheel(self, factory_instance: PlayingFactory):
        """Test basic async crafting of iron gear wheels."""
        clear_inventory(factory_instance)
        add_items(factory_instance, {"iron-plate": 4})
        
        # Await async crafting operation
        # One gear wheel = 2 iron plates
        # Crafting 2 gear wheels = 4 iron plates
        crafted_items = await factory_instance.crafting.craft("iron-gear-wheel", count=2)
        
        assert len(crafted_items) == 1
        assert crafted_items[0].name == "iron-gear-wheel"
        assert crafted_items[0].count == 2
        
        # Verify inventory state
        assert get_inventory_count(factory_instance, "iron-gear-wheel") == 2
        assert get_inventory_count(factory_instance, "iron-plate") == 0

    async def test_async_craft_copper_cable(self, factory_instance: PlayingFactory):
        """Test async crafting of copper cables (1 plate -> 2 cables)."""
        clear_inventory(factory_instance)
        add_items(factory_instance, {"copper-plate": 2})
        
        # 1 copper plate = 2 copper cables
        # 2 copper plates = 4 copper cables
        await factory_instance.crafting.craft("copper-cable", count=4)
        
        assert get_inventory_count(factory_instance, "copper-cable") == 4
        assert get_inventory_count(factory_instance, "copper-plate") == 0

    async def test_async_craft_electronic_circuit(self, factory_instance: PlayingFactory):
        """Test async crafting with multiple ingredients."""
        clear_inventory(factory_instance)
        # 1 electronic circuit = 3 copper cables + 1 iron plate
        add_items(factory_instance, {
            "copper-cable": 6,
            "iron-plate": 2
        })
        
        await factory_instance.crafting.craft("electronic-circuit", count=2)
        
        assert get_inventory_count(factory_instance, "electronic-circuit") == 2
        assert get_inventory_count(factory_instance, "copper-cable") == 0
        assert get_inventory_count(factory_instance, "iron-plate") == 0

    async def test_async_recursive_crafting(self, factory_instance: PlayingFactory):
        """
        Test recursive crafting (crafting intermediate products automatically).
        Note: The DSL's craft_item remote call in Factorio should handle this
        if the agent has the raw ingredients.
        """
        clear_inventory(factory_instance)
        # Electronic circuit from raw:
        # 3 copper cables (1.5 copper plates) + 1 iron plate
        # To craft 2: 3 copper plates + 2 iron plates
        add_items(factory_instance, {
            "copper-plate": 3,
            "iron-plate": 2
        })
        
        # We need to ensure the Factorio-side craft_item handles recursion.
        # If it doesn't, this test will fail or the DSL needs to handle it.
        await factory_instance.crafting.craft("electronic-circuit", count=2)
        
        assert get_inventory_count(factory_instance, "electronic-circuit") == 2
        assert get_inventory_count(factory_instance, "copper-plate") == 0
        assert get_inventory_count(factory_instance, "iron-plate") == 0

    async def test_async_craft_insufficient_resources(self, factory_instance: PlayingFactory):
        """Test behavior when resources are insufficient."""
        clear_inventory(factory_instance)
        add_items(factory_instance, {"iron-plate": 1}) # Needs 2 for 1 gear wheel
        
        # Depending on implementation, this might raise an exception or return an error.
        # Let's see what happens.
        with pytest.raises(Exception) as excinfo:
            await factory_instance.crafting.craft("iron-gear-wheel", count=1)
        
        # We want to check if the error message is helpful.
        assert "ingredients" in str(excinfo.value).lower() or "failed" in str(excinfo.value).lower()

    async def test_async_batch_crafting(self, factory_instance: PlayingFactory):
        """Test crafting a large batch of items."""
        clear_inventory(factory_instance)
        add_items(factory_instance, {"iron-plate": 100})
        
        # 50 gear wheels
        await factory_instance.crafting.craft("iron-gear-wheel", count=50)
        
        assert get_inventory_count(factory_instance, "iron-gear-wheel") == 50
        assert get_inventory_count(factory_instance, "iron-plate") == 0
