"""
DSL Placement Operation Tests

Tests for entity placement operations.
Tests placement, direction, validation, and metadata.
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
class TestPlacementOperations:
    """Test entity placement operations."""
    
    def test_place_furnace_via_test_ground(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test placing a furnace using test_ground helper."""
        test_ground.reset_test_area()
        
        # Place furnace at origin
        result = test_ground.place_entity("stone-furnace", x=0, y=0)
        
        assert result["success"]
        assert result["metadata"]["name"] == "stone-furnace"
        assert result["metadata"]["position"]["x"] == 0
        assert result["metadata"]["position"]["y"] == 0
        
        # Verify it exists
        assert test_ground.validate_entity_at("stone-furnace", x=0, y=0)
    
    def test_place_drill_with_direction(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test placing drill with specific direction."""
        test_ground.reset_test_area()
        
        # Place iron ore for the drill
        test_ground.place_iron_patch(x=50, y=50, size=16, amount=10000)
        
        # Place drill facing north (direction=0)
        result = test_ground.place_entity("burner-mining-drill", x=50, y=50, direction=0)
        
        assert result["success"]
        assert result["metadata"]["direction"] == 0
        assert test_ground.validate_entity_at("burner-mining-drill", x=50, y=50)
    
    def test_place_inserter_all_directions(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test placing inserters in all 4 cardinal directions."""
        test_ground.reset_test_area()
        
        # North (0), East (2), South (4), West (6)
        directions = [0, 2, 4, 6]
        positions = [(0, -5), (5, 0), (0, 5), (-5, 0)]
        
        for direction, (x, y) in zip(directions, positions):
            result = test_ground.place_entity("burner-inserter", x=x, y=y, direction=direction)
            assert result["success"]
            assert result["metadata"]["direction"] == direction
            assert test_ground.validate_entity_at("burner-inserter", x=x, y=y)
    
    def test_place_multiple_furnaces_grid(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test placing furnaces in grid pattern."""
        test_ground.reset_test_area()
        
        # Place 3x3 grid of furnaces
        result = test_ground.place_entity_grid(
            entity_name="stone-furnace",
            start_x=20,
            start_y=20,
            rows=3,
            cols=3,
            spacing_x=3,
            spacing_y=3
        )
        
        assert result["success"]
        assert result["count"] == 9
        
        # Verify corners exist
        assert test_ground.validate_entity_at("stone-furnace", x=20, y=20)  # Top-left
        assert test_ground.validate_entity_at("stone-furnace", x=26, y=26)  # Bottom-right
    
    def test_place_transport_belt_line(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test placing line of transport belts."""
        test_ground.reset_test_area()
        
        # Place 5 belts in a row
        for i in range(5):
            result = test_ground.place_entity("transport-belt", x=i*2, y=0, direction=2)  # East-facing
            assert result["success"]
        
        # Verify all exist
        for i in range(5):
            assert test_ground.validate_entity_at("transport-belt", x=i*2, y=0)
    
    def test_place_entity_updates_metadata(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that placing entities updates test metadata."""
        test_ground.reset_test_area()
        
        initial_metadata = test_ground.get_test_metadata()
        initial_count = initial_metadata["entity_count"]
        
        # Place 3 entities
        test_ground.place_entity("stone-furnace", x=10, y=10)
        test_ground.place_entity("burner-inserter", x=15, y=10)
        test_ground.place_entity("transport-belt", x=20, y=10)
        
        final_metadata = test_ground.get_test_metadata()
        final_count = final_metadata["entity_count"]
        
        assert final_count == initial_count + 3
    
    def test_place_drill_on_ore_patch(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test placing drill on ore patch (valid placement)."""
        test_ground.reset_test_area()
        
        # Place copper ore patch
        test_ground.place_copper_patch(x=100, y=100, size=16, amount=10000)
        
        # Place drill on the patch
        result = test_ground.place_entity("burner-mining-drill", x=100, y=100)
        
        assert result["success"]
        assert test_ground.validate_entity_at("burner-mining-drill", x=100, y=100)
        
        # Verify ore still exists under drill
        assert test_ground.validate_resource_at("copper-ore", x=100, y=100)
    
    def test_place_multiple_entity_types(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test placing various entity types."""
        test_ground.reset_test_area()
        
        entities = [
            ("stone-furnace", 0, 0),
            ("burner-inserter", 5, 0),
            ("transport-belt", 10, 0),
            ("wooden-chest", 15, 0),
        ]
        
        for entity_name, x, y in entities:
            result = test_ground.place_entity(entity_name, x=x, y=y)
            assert result["success"], f"Failed to place {entity_name}"
            assert test_ground.validate_entity_at(entity_name, x=x, y=y)
    
    def test_place_entity_returns_correct_metadata(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that placement returns correct entity metadata."""
        test_ground.reset_test_area()
        
        result = test_ground.place_entity("stone-furnace", x=25, y=25, direction=0)
        
        assert result["success"]
        metadata = result["metadata"]
        assert metadata["name"] == "stone-furnace"
        assert metadata["position"]["x"] == 25
        assert metadata["position"]["y"] == 25
        assert metadata["direction"] == 0
        assert "entity_id" in metadata  # Changed from entity_number
    
    def test_clear_area_removes_entities(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that clear_area removes placed entities."""
        test_ground.reset_test_area()
        
        # Place entities in area
        test_ground.place_entity("stone-furnace", x=50, y=50)
        test_ground.place_entity("stone-furnace", x=52, y=50)
        test_ground.place_entity("stone-furnace", x=54, y=50)
        
        # Verify they exist
        assert test_ground.validate_entity_at("stone-furnace", x=50, y=50)
        
        # Clear area
        result = test_ground.clear_area(
            left_top_x=49,
            left_top_y=49,
            right_bottom_x=56,
            right_bottom_y=51
        )
        
        assert result["success"]
        assert result["cleared_count"] >= 3
        
        # Verify they're gone
        assert not test_ground.validate_entity_at("stone-furnace", x=50, y=50)
        assert not test_ground.validate_entity_at("stone-furnace", x=52, y=50)
