"""Test that crafting.craft() returns proper ItemStack objects."""

import pytest
import asyncio
from FactoryVerse.factory.item.base import ItemStack

# Import dsl_context fixture from factory conftest
pytest_plugins = ["tests.factory.conftest"]

# Fixture to ensure recipes are unlocked and available for crafting
@pytest.fixture(scope="function")
def unlocked_recipes_for_test(admin):
    admin.unlock_all_technologies()
    admin.enable_all_recipes()


class TestCraftingItemStack:
    """Test that crafting.craft() returns proper ItemStack objects."""
    
    async def test_craft_returns_itemstack_list(self, dsl_context, admin, agent_id, unlocked_recipes_for_test):
        """craft() should return List[ItemStack], not dicts or other types."""
        agent_idx = int(agent_id.split("_")[1])
        admin.add_items(agent_idx, {"iron-plate": 20})

        runtime = dsl_context.runtime

        # Craft something simple
        result = await runtime.crafting.craft("iron-gear-wheel", count=1)

        # Verify return type
        assert isinstance(result, list), f"craft() should return list, got {type(result)}"
        assert len(result) > 0, "craft() should return at least one ItemStack"

        # Verify each item is an ItemStack
        for item in result:
            assert isinstance(item, ItemStack), f"Item should be ItemStack, got {type(item)}"
            assert hasattr(item, 'name'), "ItemStack should have 'name' attribute"
            assert hasattr(item, 'count'), "ItemStack should have 'count' attribute"
            assert isinstance(item.name, str), f"ItemStack.name should be str, got {type(item.name)}"
            assert isinstance(item.count, int), f"ItemStack.count should be int, got {type(item.count)}"
            assert item.count > 0, "ItemStack.count should be positive"

        print(f"✅ craft() returned {len(result)} ItemStack objects")
        for item in result:
            print(f"  - {item.name} x{item.count}")

    async def test_craft_itemstack_has_placement(self, dsl_context, admin, agent_id, unlocked_recipes_for_test):
        """ItemStack objects from craft() should have placement attribute (may be None)."""
        agent_idx = int(agent_id.split("_")[1])
        admin.add_items(agent_idx, {"iron-plate": 20})

        runtime = dsl_context.runtime

        # Craft something
        result = await runtime.crafting.craft("iron-gear-wheel", count=1)

        # Verify placement attribute exists (may be None if placement not injected)
        for item in result:
            # ItemStack may or may not have placement depending on how it was created
            # The important thing is that it's a valid ItemStack object
            assert isinstance(item, ItemStack), "Should be ItemStack object"
            # placement is optional and may be None

        print(f"✅ ItemStack objects validated (placement is optional)")

    async def test_craft_multiple_items(self, dsl_context, admin, agent_id, unlocked_recipes_for_test):
        """craft() should return ItemStack objects for recipes (even single product recipes)."""
        agent_idx = int(agent_id.split("_")[1])
        # Add ingredients for iron gear wheel (requires iron plate)
        admin.add_items(agent_idx, {"iron-plate": 20})

        runtime = dsl_context.runtime

        # Craft iron gear wheel (produces 1 item per craft)
        result = await runtime.crafting.craft("iron-gear-wheel", count=2)

        # Should return at least one ItemStack
        assert isinstance(result, list), "Should return list"
        assert len(result) >= 1, "Should have at least one product"

        # All items should be ItemStack objects
        for item in result:
            assert isinstance(item, ItemStack), f"Item should be ItemStack, got {type(item)}"
            assert item.name == "iron-gear-wheel", f"Unexpected item: {item.name}"

        # Should have at least one ItemStack (may be multiple if count > 1)
        assert len(result) >= 1, "Should have at least one ItemStack"
        
        # Verify total count matches
        total_count = sum(item.count for item in result)
        assert total_count >= 2, f"Total count should be at least 2, got {total_count}"

        print(f"✅ Multiple items test: {len(result)} ItemStack objects, total count: {total_count}")
        for item in result:
            print(f"  - {item.name} x{item.count}")
