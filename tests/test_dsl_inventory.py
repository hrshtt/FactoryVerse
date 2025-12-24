"""
DSL Inventory Operation Tests

Tests for inventory query operations.
Tests inventory tracking across mining, crafting, and placement.
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
class TestInventoryOperations:
    """Test inventory query and tracking operations."""
    
    def test_get_inventory_count_returns_correct_value(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that inventory count query returns correct value."""
        clear_inventory(factory_instance)
        
        # Add known quantity
        add_items(factory_instance, {"iron-plate": 42})
        
        # Verify count
        count = get_inventory_count(factory_instance, "iron-plate")
        assert count == 42
    
    def test_get_inventory_count_for_missing_item_returns_zero(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test querying non-existent item returns 0."""
        clear_inventory(factory_instance)
        
        count = get_inventory_count(factory_instance, "nuclear-reactor")
        assert count == 0
    
    def test_inventory_tracks_item_addition(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test inventory updates when items are added."""
        clear_inventory(factory_instance)
        
        initial = get_inventory_count(factory_instance, "copper-plate")
        
        add_items(factory_instance, {"copper-plate": 10})
        
        final = get_inventory_count(factory_instance, "copper-plate")
        assert final == initial + 10
    
    def test_inventory_tracks_multiple_item_types(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test tracking multiple item types simultaneously."""
        clear_inventory(factory_instance)
        
        # Add various items
        add_items(factory_instance, {
            "iron-plate": 20,
            "copper-plate": 15,
            "coal": 30,
            "stone": 10
        })
        
        # Verify all tracked correctly
        assert get_inventory_count(factory_instance, "iron-plate") == 20
        assert get_inventory_count(factory_instance, "copper-plate") == 15
        assert get_inventory_count(factory_instance, "coal") == 30
        assert get_inventory_count(factory_instance, "stone") == 10
    
    def test_clear_inventory_removes_all_items(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that clear_inventory removes all items."""
        # Add items
        add_items(factory_instance, {
            "iron-plate": 50,
            "copper-plate": 30
        })
        
        # Clear
        clear_inventory(factory_instance)
        
        # Verify empty
        assert get_inventory_count(factory_instance, "iron-plate") == 0
        assert get_inventory_count(factory_instance, "copper-plate") == 0
    
    def test_inventory_accumulates_same_item(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test adding same item multiple times accumulates."""
        clear_inventory(factory_instance)
        
        add_items(factory_instance, {"iron-ore": 10})
        add_items(factory_instance, {"iron-ore": 15})
        add_items(factory_instance, {"iron-ore": 5})
        
        total = get_inventory_count(factory_instance, "iron-ore")
        assert total == 30
