"""
Example tests demonstrating test-ground infrastructure.

These tests show how to:
- Use resource fixtures
- Place entities programmatically
- Validate snapshot accuracy
- Test DSL operations with known state
"""

import pytest
from FactoryVerse.dsl.agent import PlayingFactory
from helpers.test_ground import TestGround


class TestResourcePlacement:
    """Test resource placement and snapshot accuracy."""
    
    def test_iron_ore_patch_in_snapshot(self, factory_instance: PlayingFactory, iron_ore_patch):
        """Test that placed iron ore patch appears in snapshot."""
        # Load latest snapshot
        factory_instance.map_db.load_latest_snapshot()
        
        # Query for iron ore in the patch area
        patch_center_x = iron_ore_patch["center"]["x"]
        patch_center_y = iron_ore_patch["center"]["y"]
        patch_size = iron_ore_patch["size"]
        half_size = patch_size / 2
        
        result = factory_instance.map_db.query(f"""
            SELECT COUNT(*) as tile_count, SUM(amount) as total_amount
            FROM resource_tiles
            WHERE resource_name = 'iron-ore'
            AND position_x BETWEEN {patch_center_x - half_size} AND {patch_center_x + half_size}
            AND position_y BETWEEN {patch_center_y - half_size} AND {patch_center_y + half_size}
        """)
        
        assert len(result) == 1
        assert result[0]["tile_count"] > 0, "No iron ore tiles found in snapshot"
        assert result[0]["total_amount"] > 0, "Iron ore has zero amount"
        
        # Verify total amount matches expected
        expected_total = iron_ore_patch["total_amount"]
        actual_total = result[0]["total_amount"]
        
        # Allow small tolerance for edge tiles
        tolerance = 0.1 * expected_total
        assert abs(actual_total - expected_total) < tolerance, (
            f"Iron ore amount mismatch: expected ~{expected_total}, got {actual_total}"
        )
    
    def test_multiple_resource_patches_in_snapshot(self, factory_instance: PlayingFactory, all_resource_patches):
        """Test that all resource patches appear in snapshot."""
        factory_instance.map_db.load_latest_snapshot()
        
        # Check each resource type
        for resource_type, patch_info in all_resource_patches.items():
            resource_name = patch_info["resource_name"]
            
            result = factory_instance.map_db.query(f"""
                SELECT COUNT(*) as tile_count
                FROM resource_tiles
                WHERE resource_name = '{resource_name}'
            """)
            
            assert len(result) == 1
            assert result[0]["tile_count"] > 0, f"No {resource_name} tiles found in snapshot"


class TestEntityPlacement:
    """Test entity placement and snapshot accuracy."""
    
    def test_place_furnace_at_origin(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test placing a furnace at origin."""
        # Place furnace
        result = test_ground.place_entity("stone-furnace", x=0, y=0)
        
        assert result["success"], "Failed to place furnace"
        assert result["metadata"]["name"] == "stone-furnace"
        assert result["metadata"]["position"]["x"] == 0
        assert result["metadata"]["position"]["y"] == 0
        
        # Validate it exists
        assert test_ground.validate_entity_at("stone-furnace", x=0, y=0)
        
        # Force re-snapshot and check database
        test_ground.force_resnapshot()
        import time
        time.sleep(2)
        
        factory_instance.map_db.load_latest_snapshot()
        
        db_result = factory_instance.map_db.query("""
            SELECT * FROM entities
            WHERE name = 'stone-furnace'
            AND ABS(position_x - 0) < 0.5
            AND ABS(position_y - 0) < 0.5
        """)
        
        assert len(db_result) == 1, "Furnace not found in snapshot"
    
    def test_place_entity_grid(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test placing entities in a grid pattern."""
        # Place 3x3 grid of furnaces
        result = test_ground.place_entity_grid(
            entity_name="stone-furnace",
            start_x=10,
            start_y=10,
            rows=3,
            cols=3,
            spacing_x=3,
            spacing_y=3
        )
        
        assert result["success"], "Failed to place entity grid"
        assert result["count"] == 9, f"Expected 9 entities, got {result['count']}"
        
        # Force re-snapshot
        test_ground.force_resnapshot()
        import time
        time.sleep(2)
        
        factory_instance.map_db.load_latest_snapshot()
        
        # Check all furnaces are in snapshot
        db_result = factory_instance.map_db.query("""
            SELECT COUNT(*) as count FROM entities
            WHERE name = 'stone-furnace'
            AND position_x BETWEEN 10 AND 16
            AND position_y BETWEEN 10 AND 16
        """)
        
        assert db_result[0]["count"] == 9, "Not all furnaces found in snapshot"


class TestDSLOperations:
    """Test DSL operations with known map state."""
    
    def test_walk_to_iron_patch(self, factory_instance: PlayingFactory, iron_ore_patch):
        """Test walking to a known iron ore patch."""
        patch_x = iron_ore_patch["center"]["x"]
        patch_y = iron_ore_patch["center"]["y"]
        
        # Walk to patch
        factory_instance.walking.to(patch_x, patch_y)
        
        # Verify position
        pos = factory_instance.walking.get_position()
        assert abs(pos["x"] - patch_x) < 1.0, f"X position mismatch: {pos['x']} vs {patch_x}"
        assert abs(pos["y"] - patch_y) < 1.0, f"Y position mismatch: {pos['y']} vs {patch_y}"
    
    def test_mine_from_known_patch(self, factory_instance: PlayingFactory, iron_ore_patch):
        """Test mining from a known iron ore patch."""
        patch_x = iron_ore_patch["center"]["x"]
        patch_y = iron_ore_patch["center"]["y"]
        
        # Walk to patch
        factory_instance.walking.to(patch_x, patch_y)
        
        # Get initial inventory
        initial_iron = factory_instance.inventory.get_total("iron-ore")
        
        # Mine iron ore
        factory_instance.mining.resource(
            resource_name="iron-ore",
            quantity=10
        )
        
        # Verify inventory increased
        final_iron = factory_instance.inventory.get_total("iron-ore")
        assert final_iron == initial_iron + 10, (
            f"Expected {initial_iron + 10} iron ore, got {final_iron}"
        )


class TestSnapshotControl:
    """Test snapshot control and validation."""
    
    def test_force_resnapshot(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test forcing a re-snapshot."""
        # Place a resource
        test_ground.place_iron_patch(x=100, y=100, size=16, amount=5000)
        
        # Force re-snapshot
        result = test_ground.force_resnapshot()
        
        assert result["success"], "Force resnapshot failed"
        assert result["chunks_enqueued"] > 0, "No chunks enqueued for snapshot"
        
        # Wait for snapshot to complete
        import time
        time.sleep(2)
        
        # Load snapshot and verify
        factory_instance.map_db.load_latest_snapshot()
        
        db_result = factory_instance.map_db.query("""
            SELECT COUNT(*) as count FROM resource_tiles
            WHERE resource_name = 'iron-ore'
            AND position_x BETWEEN 92 AND 108
            AND position_y BETWEEN 92 AND 108
        """)
        
        assert db_result[0]["count"] > 0, "Resource not found in snapshot after force resnapshot"


class TestAreaManagement:
    """Test area clearing and reset."""
    
    def test_clear_area(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test clearing a specific area."""
        # Place some entities
        test_ground.place_entity("stone-furnace", x=50, y=50)
        test_ground.place_entity("stone-furnace", x=52, y=50)
        test_ground.place_entity("stone-furnace", x=54, y=50)
        
        # Verify they exist
        assert test_ground.validate_entity_at("stone-furnace", x=50, y=50)
        assert test_ground.validate_entity_at("stone-furnace", x=52, y=50)
        assert test_ground.validate_entity_at("stone-furnace", x=54, y=50)
        
        # Clear area
        result = test_ground.clear_area(
            left_top_x=49,
            left_top_y=49,
            right_bottom_x=56,
            right_bottom_y=51
        )
        
        assert result["success"], "Clear area failed"
        assert result["cleared_count"] >= 3, f"Expected to clear at least 3 entities, cleared {result['cleared_count']}"
        
        # Verify they're gone
        assert not test_ground.validate_entity_at("stone-furnace", x=50, y=50)
        assert not test_ground.validate_entity_at("stone-furnace", x=52, y=50)
        assert not test_ground.validate_entity_at("stone-furnace", x=54, y=50)
    
    def test_reset_test_area(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test resetting entire test area."""
        # Place resources and entities
        test_ground.place_iron_patch(x=0, y=0, size=16, amount=5000)
        test_ground.place_entity("stone-furnace", x=10, y=10)
        
        # Reset
        result = test_ground.reset_test_area()
        
        assert result["success"], "Reset test area failed"
        
        # Verify everything is cleared
        metadata = test_ground.get_test_metadata()
        assert metadata["resource_count"] == 0, "Resources not cleared after reset"
        assert metadata["entity_count"] == 0, "Entities not cleared after reset"
