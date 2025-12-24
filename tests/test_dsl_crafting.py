"""
DSL Crafting Operation Tests

Tests for crafting operations for handcraftable items.
Tests ingredient consumption, output production, and error handling.
"""

import pytest
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


@pytest.mark.dsl
class TestCraftingOperations:
    """Test DSL crafting operations for handcraftable items."""
    
    def test_craft_iron_gear_wheel(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test crafting iron gear wheels consumes ingredients and produces output."""
        clear_inventory(factory_instance)
        
        # Give 4 iron plates (2 per gear wheel)
        add_items(factory_instance, {"iron-plate": 4})
        
        initial_plates = get_inventory_count(factory_instance, "iron-plate")
        initial_gears = get_inventory_count(factory_instance, "iron-gear-wheel")
        
        # Craft 2 gear wheels (consumes 4 iron plates)
        result = factory_instance._rcon.send_command(
            f'/c local success, err = xpcall(function() '
            f'return remote.call("{factory_instance._agent_id}", "craft_item", "iron-gear-wheel", 2) '
            f'end, debug.traceback); '
            f'if success then rcon.print("SUCCESS") else rcon.print("ERROR: " .. tostring(err)) end'
        )
        
        # Verify ingredients consumed
        final_plates = get_inventory_count(factory_instance, "iron-plate")
        assert final_plates == initial_plates - 4, f"Expected {initial_plates - 4} plates, got {final_plates}"
        
        # Verify output produced
        final_gears = get_inventory_count(factory_instance, "iron-gear-wheel")
        assert final_gears == initial_gears + 2, f"Expected {initial_gears + 2} gears, got {final_gears}"
    
    def test_craft_copper_cable(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test crafting copper cable (2:1 ratio) produces correct output."""
        clear_inventory(factory_instance)
        
        # Give 10 copper plates
        add_items(factory_instance, {"copper-plate": 10})
        
        initial_plates = get_inventory_count(factory_instance, "copper-plate")
        
        # Craft 20 copper cables (consumes 10 copper plates, 2:1 ratio)
        factory_instance._rcon.send_command(
            f'/c remote.call("{factory_instance._agent_id}", "craft_item", "copper-cable", 20)'
        )
        
        # Verify 10 plates consumed
        final_plates = get_inventory_count(factory_instance, "copper-plate")
        assert final_plates == initial_plates - 10
        
        # Verify 20 cables produced
        final_cables = get_inventory_count(factory_instance, "copper-cable")
        assert final_cables == 20
    
    def test_craft_electronic_circuit(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test crafting electronic circuits with multiple ingredients."""
        clear_inventory(factory_instance)
        
        # Give ingredients: 3 copper cables + 1 iron plate per circuit
        add_items(factory_instance, {
            "copper-cable": 6,
            "iron-plate": 2
        })
        
        initial_cables = get_inventory_count(factory_instance, "copper-cable")
        initial_plates = get_inventory_count(factory_instance, "iron-plate")
        
        # Craft 2 electronic circuits
        factory_instance._rcon.send_command(
            f'/c remote.call("{factory_instance._agent_id}", "craft_item", "electronic-circuit", 2)'
        )
        
        # Verify ingredients consumed
        final_cables = get_inventory_count(factory_instance, "copper-cable")
        final_plates = get_inventory_count(factory_instance, "iron-plate")
        assert final_cables == initial_cables - 6
        assert final_plates == initial_plates - 2
        
        # Verify output produced
        final_circuits = get_inventory_count(factory_instance, "electronic-circuit")
        assert final_circuits == 2
    
    def test_craft_stone_furnace(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test crafting stone furnace from stone."""
        clear_inventory(factory_instance)
        
        # Give 5 stone
        add_items(factory_instance, {"stone": 5})
        
        initial_stone = get_inventory_count(factory_instance, "stone")
        
        # Craft 1 stone furnace
        factory_instance._rcon.send_command(
            f'/c remote.call("{factory_instance._agent_id}", "craft_item", "stone-furnace", 1)'
        )
        
        # Verify stone consumed
        final_stone = get_inventory_count(factory_instance, "stone")
        assert final_stone == initial_stone - 5
        
        # Verify furnace produced
        final_furnaces = get_inventory_count(factory_instance, "stone-furnace")
        assert final_furnaces == 1
    
    def test_craft_transport_belt(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test crafting transport belts."""
        clear_inventory(factory_instance)
        
        # Give ingredients: 1 iron plate + 1 iron gear wheel per 2 belts
        add_items(factory_instance, {
            "iron-plate": 2,
            "iron-gear-wheel": 2
        })
        
        # Craft 4 transport belts
        factory_instance._rcon.send_command(
            f'/c remote.call("{factory_instance._agent_id}", "craft_item", "transport-belt", 4)'
        )
        
        # Verify output
        final_belts = get_inventory_count(factory_instance, "transport-belt")
        assert final_belts == 4
    
    def test_craft_burner_mining_drill(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test crafting burner mining drill (complex recipe)."""
        clear_inventory(factory_instance)
        
        # Give ingredients: 3 iron gear wheels + 3 iron plates + 1 stone furnace
        add_items(factory_instance, {
            "iron-gear-wheel": 3,
            "iron-plate": 3,
            "stone-furnace": 1
        })
        
        initial_gears = get_inventory_count(factory_instance, "iron-gear-wheel")
        initial_plates = get_inventory_count(factory_instance, "iron-plate")
        initial_furnaces = get_inventory_count(factory_instance, "stone-furnace")
        
        # Craft 1 burner mining drill
        factory_instance._rcon.send_command(
            f'/c remote.call("{factory_instance._agent_id}", "craft_item", "burner-mining-drill", 1)'
        )
        
        # Verify ingredients consumed
        assert get_inventory_count(factory_instance, "iron-gear-wheel") == initial_gears - 3
        assert get_inventory_count(factory_instance, "iron-plate") == initial_plates - 3
        assert get_inventory_count(factory_instance, "stone-furnace") == initial_furnaces - 1
        
        # Verify drill produced
        assert get_inventory_count(factory_instance, "burner-mining-drill") == 1
    
    def test_craft_multiple_items_batch(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test crafting multiple items in one batch."""
        clear_inventory(factory_instance)
        
        # Give enough iron plates for 10 gear wheels
        add_items(factory_instance, {"iron-plate": 20})
        
        # Craft 10 gear wheels at once
        factory_instance._rcon.send_command(
            f'/c remote.call("{factory_instance._agent_id}", "craft_item", "iron-gear-wheel", 10)'
        )
        
        # Verify all produced
        final_gears = get_inventory_count(factory_instance, "iron-gear-wheel")
        assert final_gears == 10
    
    def test_craft_consumes_exact_ingredients(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that crafting consumes exact ingredient amounts."""
        clear_inventory(factory_instance)
        
        # Give exact ingredients for 3 gear wheels (6 iron plates)
        add_items(factory_instance, {"iron-plate": 6})
        
        # Craft 3 gear wheels
        factory_instance._rcon.send_command(
            f'/c remote.call("{factory_instance._agent_id}", "craft_item", "iron-gear-wheel", 3)'
        )
        
        # Verify exactly 0 plates remain
        final_plates = get_inventory_count(factory_instance, "iron-plate")
        assert final_plates == 0, f"Expected 0 plates remaining, got {final_plates}"
        
        # Verify exactly 3 gears produced
        final_gears = get_inventory_count(factory_instance, "iron-gear-wheel")
        assert final_gears == 3
    
    def test_craft_updates_inventory_correctly(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test comprehensive inventory state after crafting."""
        clear_inventory(factory_instance)
        
        # Start with known state
        add_items(factory_instance, {
            "iron-plate": 10,
            "copper-plate": 5,
            "stone": 5
        })
        
        # Craft various items
        factory_instance._rcon.send_command(
            f'/c remote.call("{factory_instance._agent_id}", "craft_item", "iron-gear-wheel", 2)'  # -4 iron
        )
        factory_instance._rcon.send_command(
            f'/c remote.call("{factory_instance._agent_id}", "craft_item", "copper-cable", 4)'  # -2 copper
        )
        factory_instance._rcon.send_command(
            f'/c remote.call("{factory_instance._agent_id}", "craft_item", "stone-furnace", 1)'  # -5 stone
        )
        
        # Verify final state
        assert get_inventory_count(factory_instance, "iron-plate") == 6  # 10 - 4
        assert get_inventory_count(factory_instance, "copper-plate") == 3  # 5 - 2
        assert get_inventory_count(factory_instance, "stone") == 0  # 5 - 5
        assert get_inventory_count(factory_instance, "iron-gear-wheel") == 2
        assert get_inventory_count(factory_instance, "copper-cable") == 4
        assert get_inventory_count(factory_instance, "stone-furnace") == 1
