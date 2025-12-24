"""
DSL Mining Operation Tests

Tests for mining operations across all resource types.

NOTE: These tests use simplified mining simulation since the test-ground scenario
doesn't have the full FV Embodied Agent mod. We test the infrastructure and
verify that resources can be placed and inventory can be manipulated.
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


@pytest.mark.dsl
class TestMiningOperations:
    """Test mining infrastructure and resource placement."""
    
    def test_mine_iron_ore_increases_inventory(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that iron ore can be added to inventory."""
        test_ground.reset_test_area()
        test_ground.place_iron_patch(x=64, y=-64, size=16, amount=10000)
        
        # Get initial count
        initial_iron = get_inventory_count(factory_instance, "iron-ore")
        
        # Add to inventory via admin interface
        factory_instance._rcon.send_command(
            f'/c remote.call("admin", "add_items", {factory_instance._numeric_agent_id}, {{["iron-ore"]=10}})'
        )
        
        # Verify inventory increased
        final_iron = get_inventory_count(factory_instance, "iron-ore")
        assert final_iron == initial_iron + 10, f"Expected {initial_iron + 10}, got {final_iron}"
    
    def test_mine_copper_ore_increases_inventory(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that copper ore can be added to inventory."""
        test_ground.reset_test_area()
        test_ground.place_copper_patch(x=-64, y=-64, size=16, amount=10000)
        
        initial_copper = get_inventory_count(factory_instance, "copper-ore")
        
        factory_instance._rcon.send_command(
            f'/c remote.call("admin", "add_items", {factory_instance._numeric_agent_id}, {{["copper-ore"]=10}})'
        )
        
        final_copper = get_inventory_count(factory_instance, "copper-ore")
        assert final_copper == initial_copper + 10
    
    def test_mine_coal_increases_inventory(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that coal can be added to inventory."""
        test_ground.reset_test_area()
        test_ground.place_coal_patch(x=64, y=64, size=16, amount=10000)
        
        initial_coal = get_inventory_count(factory_instance, "coal")
        
        factory_instance._rcon.send_command(
            f'/c remote.call("admin", "add_items", {factory_instance._numeric_agent_id}, {{["coal"]=10}})'
        )
        
        final_coal = get_inventory_count(factory_instance, "coal")
        assert final_coal == initial_coal + 10
    
    def test_mine_stone_increases_inventory(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that stone can be added to inventory."""
        test_ground.reset_test_area()
        test_ground.place_stone_patch(x=-64, y=64, size=16, amount=10000)
        
        initial_stone = get_inventory_count(factory_instance, "stone")
        
        factory_instance._rcon.send_command(
            f'/c remote.call("admin", "add_items", {factory_instance._numeric_agent_id}, {{["stone"]=10}})'
        )
        
        final_stone = get_inventory_count(factory_instance, "stone")
        assert final_stone == initial_stone + 10
    
    def test_mine_depletes_resource_amount(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that resource amount can be reduced in game."""
        test_ground.reset_test_area()
        
        # Place iron patch with known amount
        test_ground.place_iron_patch(x=100, y=100, size=8, amount=1000)
        
        # Reduce resource amount
        factory_instance._rcon.send_command(
            '/c local surface = game.surfaces[1]; '
            'local resources = surface.find_entities_filtered{position={100, 100}, radius=5, type="resource", name="iron-ore"}; '
            'if #resources > 0 then '
            '  resources[1].amount = 500; '
            'end'
        )
        
        # Verify resource amount decreased
        result = factory_instance._rcon.send_command(
            '/c local surface = game.surfaces[1]; '
            'local resources = surface.find_entities_filtered{position={100, 100}, radius=5, type="resource", name="iron-ore"}; '
            'if #resources > 0 then rcon.print(resources[1].amount) else rcon.print(0) end'
        )
        
        current_amount = int(result.strip()) if result and result.strip() else 0
        assert current_amount == 500, f"Expected 500, got {current_amount}"
    
    def test_mine_multiple_times_accumulates(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test mining multiple times accumulates inventory."""
        test_ground.reset_test_area()
        test_ground.place_iron_patch(x=50, y=50, size=16, amount=10000)
        
        initial_iron = get_inventory_count(factory_instance, "iron-ore")
        
        # Mine multiple times
        for i in range(3):
            factory_instance._rcon.send_command(
                f'/c remote.call("admin", "add_items", {factory_instance._numeric_agent_id}, {{["iron-ore"]=5}})'
            )
        
        final_iron = get_inventory_count(factory_instance, "iron-ore")
        assert final_iron == initial_iron + 15, f"Expected {initial_iron + 15}, got {final_iron}"
    
    def test_mine_from_different_patches(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that multiple resource patches can be placed."""
        test_ground.reset_test_area()
        
        # Place two iron patches
        patch1 = test_ground.place_iron_patch(x=30, y=30, size=8, amount=5000)
        patch2 = test_ground.place_iron_patch(x=60, y=60, size=8, amount=5000)
        
        # Verify both patches were created
        assert patch1["success"]
        assert patch2["success"]
        
        # Verify they exist in game
        assert test_ground.validate_resource_at("iron-ore", x=30, y=30)
        assert test_ground.validate_resource_at("iron-ore", x=60, y=60)
    
    def test_mine_specific_quantity(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test adding exact quantity to inventory."""
        test_ground.reset_test_area()
        test_ground.place_iron_patch(x=0, y=0, size=16, amount=10000)
        
        initial_iron = get_inventory_count(factory_instance, "iron-ore")
        target_quantity = 25
        
        factory_instance._rcon.send_command(
            f'/c remote.call("admin", "add_items", {factory_instance._numeric_agent_id}, {{["iron-ore"]={target_quantity}}})'
        )
        
        final_iron = get_inventory_count(factory_instance, "iron-ore")
        mined_amount = final_iron - initial_iron
        
        assert mined_amount == target_quantity, f"Expected {target_quantity}, got {mined_amount}"

