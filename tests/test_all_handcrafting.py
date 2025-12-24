"""
Comprehensive Handcrafting Validation Tests

Tests ALL handcraftable recipes to ensure:
1. Ingredients are correctly consumed
2. Products are correctly produced
3. No errors occur during crafting

This validates the entire handcrafting system end-to-end.
"""

import pytest
import asyncio
import json
from typing import Dict, List, Any
from FactoryVerse.dsl.agent import PlayingFactory
from FactoryVerse.dsl.prototypes import get_recipe_prototypes
from helpers.test_ground import TestGround


def get_inventory_count(factory: PlayingFactory, item_name: str) -> int:
    """Get count of an item in inventory."""
    result = factory._rcon.send_command(
        f'/c rcon.print(helpers.table_to_json(remote.call("{factory._agent_id}", "get_inventory_items")))'
    )
    if not result or result.strip() == "":
        return 0
    
    inventory_data = json.loads(result)
    total = sum(stack.get("count", 0) for stack in inventory_data if stack.get("name") == item_name)
    return total


def add_items(factory: PlayingFactory, items: Dict[str, int]):
    """Add items to inventory via admin interface."""
    if not items:
        return
    items_lua = ", ".join(f'["{name}"]={count}' for name, count in items.items())
    factory._rcon.send_command(
        f'/c remote.call("admin", "add_items", {factory._numeric_agent_id}, {{{items_lua}}})'
    )


def clear_inventory(factory: PlayingFactory):
    """Clear agent inventory."""
    factory._rcon.send_command(
        f'/c remote.call("admin", "clear_inventory", {factory._numeric_agent_id})'
    )


def unlock_all_recipes(factory: PlayingFactory):
    """Unlock ALL recipes for testing."""
    # Unlock all technologies which unlocks all recipes
    factory._rcon.send_command(
        '/c for _, tech in pairs(game.forces.player.technologies) do tech.researched = true end'
    )


def set_game_speed(factory: PlayingFactory, speed: float):
    """Set game speed multiplier."""
    factory._rcon.send_command(f"/c game.speed = {speed}")


def parse_ingredients(recipe_data: Dict[str, Any]) -> Dict[str, int]:
    """Parse ingredients from recipe data into {item_name: count} dict."""
    ingredients = {}
    
    # Handle both old and new ingredient formats
    ingredient_list = recipe_data.get("ingredients", [])
    
    for ingredient in ingredient_list:
        if isinstance(ingredient, dict):
            # New format: {"name": "iron-plate", "amount": 2}
            name = ingredient.get("name")
            amount = ingredient.get("amount", 1)
        elif isinstance(ingredient, list) and len(ingredient) >= 2:
            # Old format: ["iron-plate", 2]
            name = ingredient[0]
            amount = ingredient[1]
        else:
            continue
        
        if name:
            ingredients[name] = amount
    
    return ingredients


def parse_products(recipe_data: Dict[str, Any]) -> Dict[str, int]:
    """Parse products from recipe data into {item_name: count} dict."""
    products = {}
    
    # Check for 'result' (single product, old format)
    if "result" in recipe_data:
        result_name = recipe_data["result"]
        result_count = recipe_data.get("result_count", 1)
        products[result_name] = result_count
        return products
    
    # Check for 'results' (multiple products, new format)
    results_list = recipe_data.get("results", [])
    for result in results_list:
        if isinstance(result, dict):
            name = result.get("name")
            amount = result.get("amount", 1)
            if name:
                products[name] = amount
    
    return products


@pytest.mark.dsl
@pytest.mark.asyncio
class TestAllHandcraftableRecipes:
    """Comprehensive tests for all handcraftable recipes."""
    
    async def test_all_handcraftable_recipes(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that ALL handcraftable recipes work correctly."""
        
        # Setup: unlock all recipes and speed up game
        print("\n" + "="*80)
        print("COMPREHENSIVE HANDCRAFTING VALIDATION")
        print("="*80)
        
        unlock_all_recipes(factory_instance)
        set_game_speed(factory_instance, 100.0)
        
        # Get all handcraftable recipes
        recipe_protos = get_recipe_prototypes()
        handcraftable_recipes = recipe_protos.get_recipes_by_category("crafting")
        
        print(f"\nFound {len(handcraftable_recipes)} handcraftable recipes")
        print(f"Recipes: {', '.join(sorted(handcraftable_recipes))}\n")
        
        passed = 0
        failed = 0
        errors = []
        
        for recipe_name in sorted(handcraftable_recipes):
            try:
                await self._test_single_recipe(factory_instance, recipe_name, recipe_protos)
                passed += 1
                print(f"✓ {recipe_name}")
            except Exception as e:
                failed += 1
                error_msg = f"✗ {recipe_name}: {str(e)}"
                print(error_msg)
                errors.append(error_msg)
        
        # Cleanup
        set_game_speed(factory_instance, 1.0)
        clear_inventory(factory_instance)
        
        # Summary
        print("\n" + "="*80)
        print(f"RESULTS: {passed} passed, {failed} failed out of {len(handcraftable_recipes)} recipes")
        print("="*80)
        
        if errors:
            print("\nFailed recipes:")
            for error in errors:
                print(f"  {error}")
        
        # Assert all passed
        assert failed == 0, f"{failed} recipes failed validation. See output above for details."
    
    async def _test_single_recipe(
        self, 
        factory: PlayingFactory, 
        recipe_name: str,
        recipe_protos
    ):
        """Test a single recipe."""
        
        # Clear inventory before each test
        clear_inventory(factory)
        
        # Get recipe data
        recipe_data = recipe_protos.recipes.get(recipe_name)
        if not recipe_data:
            raise ValueError(f"Recipe {recipe_name} not found in prototypes")
        
        # Parse ingredients and products
        ingredients = parse_ingredients(recipe_data)
        products = parse_products(recipe_data)
        
        if not products:
            raise ValueError(f"Recipe {recipe_name} has no products")
        
        # Add ingredients to inventory
        add_items(factory, ingredients)
        
        # Record initial state
        initial_counts = {}
        for item_name in ingredients.keys():
            initial_counts[item_name] = get_inventory_count(factory, item_name)
        
        # Craft the recipe (count=1)
        try:
            result = await factory.crafting.craft(recipe_name, count=1, timeout=15)
        except Exception as e:
            raise RuntimeError(f"Crafting failed: {e}")
        
        # Verify ingredients consumed
        for item_name, expected_consumed in ingredients.items():
            final_count = get_inventory_count(factory, item_name)
            expected_final = initial_counts[item_name] - expected_consumed
            if final_count != expected_final:
                raise AssertionError(
                    f"Ingredient {item_name}: expected {expected_final}, got {final_count} "
                    f"(started with {initial_counts[item_name]}, should consume {expected_consumed})"
                )
        
        # Verify products produced
        for product_name, expected_count in products.items():
            actual_count = get_inventory_count(factory, product_name)
            if actual_count != expected_count:
                raise AssertionError(
                    f"Product {product_name}: expected {expected_count}, got {actual_count}"
                )
        
        # Clear inventory for next test
        clear_inventory(factory)


@pytest.mark.dsl
class TestSpecificHandcraftableRecipes:
    """Targeted tests for specific important recipes."""
    
    def test_iron_gear_wheel(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test iron gear wheel crafting (most common recipe)."""
        unlock_all_recipes(factory_instance)
        set_game_speed(factory_instance, 100.0)
        clear_inventory(factory_instance)
        
        # Add ingredients
        add_items(factory_instance, {"iron-plate": 2})
        
        # Craft
        factory_instance._rcon.send_command(
            f'/c remote.call("{factory_instance._agent_id}", "craft_item", "iron-gear-wheel", 1)'
        )
        
        # Verify
        assert get_inventory_count(factory_instance, "iron-gear-wheel") == 1
        assert get_inventory_count(factory_instance, "iron-plate") == 0
        
        # Cleanup
        clear_inventory(factory_instance)
        set_game_speed(factory_instance, 1.0)
    
    def test_copper_cable(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test copper cable crafting (2:1 ratio)."""
        unlock_all_recipes(factory_instance)
        set_game_speed(factory_instance, 100.0)
        clear_inventory(factory_instance)
        
        # Add ingredients (1 copper plate makes 2 cables)
        add_items(factory_instance, {"copper-plate": 1})
        
        # Craft
        factory_instance._rcon.send_command(
            f'/c remote.call("{factory_instance._agent_id}", "craft_item", "copper-cable", 2)'
        )
        
        # Verify
        assert get_inventory_count(factory_instance, "copper-cable") == 2
        assert get_inventory_count(factory_instance, "copper-plate") == 0
        
        # Cleanup
        clear_inventory(factory_instance)
        set_game_speed(factory_instance, 1.0)
