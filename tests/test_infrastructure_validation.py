"""
Infrastructure validation tests.

These tests verify that the test-ground scenario and testing infrastructure
are working correctly before writing more complex tests.
"""

import pytest
import time
from FactoryVerse.dsl.agent import PlayingFactory
from helpers.test_ground import TestGround


class TestScenarioConnectivity:
    """Verify test-ground scenario is loaded and accessible."""
    
    def test_scenario_loaded(self, test_ground: TestGround):
        """Test that test-ground scenario is loaded."""
        size = test_ground.get_test_area_size()
        assert size == 512, f"Expected test area size 512, got {size}"
    
    def test_get_test_bounds(self, test_ground: TestGround):
        """Test getting test area bounds."""
        bounds = test_ground.get_test_bounds()
        
        assert bounds is not None
        assert "left_top" in bounds
        assert "right_bottom" in bounds
        assert bounds["left_top"]["x"] == -256
        assert bounds["left_top"]["y"] == -256
        assert bounds["right_bottom"]["x"] == 256
        assert bounds["right_bottom"]["y"] == 256
    
    def test_get_initial_metadata(self, test_ground: TestGround):
        """Test getting test metadata."""
        metadata = test_ground.get_test_metadata()
        
        # Verify metadata structure (don't assume clean state since auto-reset is disabled)
        assert metadata is not None
        assert "metadata" in metadata
        assert "resources" in metadata
        assert "entities" in metadata
        assert "resource_count" in metadata
        assert "entity_count" in metadata


class TestResourcePlacement:
    """Verify resource placement helpers work correctly."""
    
    def test_place_iron_patch_square(self, test_ground: TestGround):
        """Test placing a square iron ore patch."""
        result = test_ground.place_iron_patch(x=64, y=-64, size=32, amount=10000)
        
        assert result["success"] is True
        assert result["resource_name"] == "iron-ore"
        assert result["center"]["x"] == 64
        assert result["center"]["y"] == -64
        assert result["size"] == 32
        assert result["amount_per_tile"] == 10000
        assert result["total_tiles"] == 32 * 32  # 1024 tiles
        assert result["total_amount"] == 32 * 32 * 10000
        
        # Validate it exists
        assert test_ground.validate_resource_at("iron-ore", x=64, y=-64)
    
    def test_place_copper_patch_square(self, test_ground: TestGround):
        """Test placing a square copper ore patch."""
        result = test_ground.place_copper_patch(x=-64, y=-64, size=16, amount=5000)
        
        assert result["success"] is True
        assert result["resource_name"] == "copper-ore"
        assert result["total_tiles"] == 16 * 16
        
        # Validate it exists
        assert test_ground.validate_resource_at("copper-ore", x=-64, y=-64)
    
    def test_place_resource_patch_circle(self, test_ground: TestGround):
        """Test placing a circular resource patch."""
        result = test_ground.place_resource_patch_circle(
            resource_name="coal",
            center_x=0,
            center_y=0,
            radius=10,
            amount=8000
        )
        
        assert result["success"] is True
        assert result["resource_name"] == "coal"
        assert result["radius"] == 10
        assert result["total_tiles"] > 0  # Should place some tiles
        
        # Validate center tile exists
        assert test_ground.validate_resource_at("coal", x=0, y=0)
    
    def test_metadata_tracks_placed_resources(self, test_ground: TestGround):
        """Test that metadata tracks placed resources."""
        # Place multiple patches
        test_ground.place_iron_patch(x=50, y=50, size=8, amount=5000)
        test_ground.place_copper_patch(x=-50, y=50, size=8, amount=5000)
        
        # Get metadata
        metadata = test_ground.get_test_metadata()
        
        # Should have resources tracked
        assert metadata["resource_count"] > 0
        assert len(metadata["resources"]) > 0


class TestEntityPlacement:
    """Verify entity placement helpers work correctly."""
    
    def test_place_single_entity(self, test_ground: TestGround):
        """Test placing a single entity."""
        result = test_ground.place_entity("stone-furnace", x=0, y=0)
        
        assert result["success"] is True
        assert result["metadata"]["name"] == "stone-furnace"
        assert result["metadata"]["position"]["x"] == 0
        assert result["metadata"]["position"]["y"] == 0
        
        # Validate it exists
        assert test_ground.validate_entity_at("stone-furnace", x=0, y=0)
    
    def test_place_entity_with_direction(self, test_ground: TestGround):
        """Test placing an entity with direction."""
        result = test_ground.place_entity("burner-mining-drill", x=10, y=10, direction=2)
        
        assert result["success"] is True
        assert result["metadata"]["direction"] == 2
        
        # Validate it exists
        assert test_ground.validate_entity_at("burner-mining-drill", x=10, y=10)
    
    def test_place_entity_grid(self, test_ground: TestGround):
        """Test placing entities in a grid pattern."""
        result = test_ground.place_entity_grid(
            entity_name="stone-furnace",
            start_x=20,
            start_y=20,
            rows=3,
            cols=3,
            spacing_x=3,
            spacing_y=3
        )
        
        assert result["success"] is True
        assert result["count"] == 9  # 3x3 grid
        
        # Validate corner entities exist
        assert test_ground.validate_entity_at("stone-furnace", x=20, y=20)  # Top-left
        assert test_ground.validate_entity_at("stone-furnace", x=26, y=26)  # Bottom-right
    
    def test_metadata_tracks_placed_entities(self, test_ground: TestGround):
        """Test that metadata tracks placed entities."""
        # Place multiple entities
        test_ground.place_entity("stone-furnace", x=30, y=30)
        test_ground.place_entity("burner-mining-drill", x=35, y=30)
        
        # Get metadata
        metadata = test_ground.get_test_metadata()
        
        # Should have entities tracked
        assert metadata["entity_count"] >= 2
        assert len(metadata["entities"]) >= 2


class TestAreaManagement:
    """Verify area management helpers work correctly."""
    
    def test_clear_specific_area(self, test_ground: TestGround):
        """Test clearing a specific area."""
        # Place some entities
        test_ground.place_entity("stone-furnace", x=100, y=100)
        test_ground.place_entity("stone-furnace", x=102, y=100)
        test_ground.place_entity("stone-furnace", x=104, y=100)
        
        # Verify they exist
        assert test_ground.validate_entity_at("stone-furnace", x=100, y=100)
        assert test_ground.validate_entity_at("stone-furnace", x=102, y=100)
        
        # Clear area
        result = test_ground.clear_area(
            left_top_x=99,
            left_top_y=99,
            right_bottom_x=106,
            right_bottom_y=101
        )
        
        assert result["success"] is True
        assert result["cleared_count"] >= 3
        
        # Verify they're gone
        assert not test_ground.validate_entity_at("stone-furnace", x=100, y=100)
        assert not test_ground.validate_entity_at("stone-furnace", x=102, y=100)
    
    def test_reset_test_area(self, test_ground: TestGround):
        """Test resetting entire test area."""
        # Place resources and entities
        test_ground.place_iron_patch(x=0, y=0, size=16, amount=5000)
        test_ground.place_entity("stone-furnace", x=10, y=10)
        
        # Verify metadata shows them
        metadata_before = test_ground.get_test_metadata()
        assert metadata_before["resource_count"] > 0
        assert metadata_before["entity_count"] > 0
        
        # Reset
        result = test_ground.reset_test_area()
        assert result["success"] is True
        
        # Verify everything is cleared
        metadata_after = test_ground.get_test_metadata()
        assert metadata_after["resource_count"] == 0
        assert metadata_after["entity_count"] == 0


class TestSnapshotControl:
    """Verify snapshot control functionality."""
    
    def test_force_resnapshot_all_chunks(self, test_ground: TestGround):
        """Test forcing re-snapshot of all test area chunks."""
        # Place a resource
        test_ground.place_iron_patch(x=100, y=100, size=16, amount=5000)
        
        # Force re-snapshot
        result = test_ground.force_resnapshot()
        
        assert result["success"] is True
        assert result["chunks_enqueued"] > 0
        assert result["total_chunks"] > 0
    
    def test_force_resnapshot_specific_chunks(self, test_ground: TestGround):
        """Test forcing re-snapshot of specific chunks."""
        # Force re-snapshot of specific chunks
        result = test_ground.force_resnapshot(chunk_coords=[(0, 0), (1, 0)])
        
        assert result["success"] is True
        assert result["chunks_enqueued"] == 2
        assert result["total_chunks"] == 2


class TestAutoReset:
    """Verify auto-reset between tests works correctly."""
    
    def test_first_test_places_entity(self, test_ground: TestGround):
        """First test places an entity."""
        test_ground.place_entity("stone-furnace", x=50, y=50)
        assert test_ground.validate_entity_at("stone-furnace", x=50, y=50)
    
    def test_second_test_sees_clean_state(self, test_ground: TestGround):
        """Second test should see clean state after manual reset."""
        # Manually reset since auto-reset is disabled
        test_ground.reset_test_area()
        
        # Verify entity from previous test is gone
        assert not test_ground.validate_entity_at("stone-furnace", x=50, y=50)
        
        # Metadata should show empty state
        metadata = test_ground.get_test_metadata()
        assert metadata["entity_count"] == 0
        assert metadata["resource_count"] == 0
