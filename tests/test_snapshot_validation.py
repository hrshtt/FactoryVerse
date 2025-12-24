"""
Snapshot Validation Tests

Tests that verify snapshot system accurately reflects game state.
Tests resource snapshots, entity snapshots, and metadata tracking.
"""

import pytest
import time
from FactoryVerse.dsl.agent import PlayingFactory
from helpers.test_ground import TestGround


@pytest.mark.snapshot
class TestSnapshotValidation:
    """Test snapshot system accuracy."""
    
    def test_snapshot_metadata_tracks_resources(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that metadata tracks placed resources."""
        test_ground.reset_test_area()
        
        # Place resources
        test_ground.place_iron_patch(x=50, y=50, size=16, amount=5000)
        test_ground.place_copper_patch(x=-50, y=-50, size=16, amount=5000)
        
        # Get metadata
        metadata = test_ground.get_test_metadata()
        
        # Verify resources tracked
        assert metadata["resource_count"] >= 2
        assert len(metadata["resources"]) >= 2
    
    def test_snapshot_metadata_tracks_entities(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that metadata tracks placed entities."""
        test_ground.reset_test_area()
        
        # Place entities
        test_ground.place_entity("stone-furnace", x=10, y=10)
        test_ground.place_entity("burner-inserter", x=15, y=10)
        
        # Get metadata
        metadata = test_ground.get_test_metadata()
        
        # Verify entities tracked
        assert metadata["entity_count"] >= 2
        assert len(metadata["entities"]) >= 2
    
    def test_snapshot_force_resnapshot_enqueues_chunks(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that force_resnapshot enqueues chunks."""
        test_ground.reset_test_area()
        
        # Force resnapshot
        result = test_ground.force_resnapshot()
        
        assert result["success"]
        assert result["chunks_enqueued"] > 0
        assert result["total_chunks"] > 0
    
    def test_snapshot_specific_chunks(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test forcing resnapshot of specific chunks."""
        # Force resnapshot of 2 specific chunks
        result = test_ground.force_resnapshot(chunk_coords=[(0, 0), (1, 0)])
        
        assert result["success"]
        assert result["chunks_enqueued"] == 2
        assert result["total_chunks"] == 2
    
    def test_snapshot_reflects_area_reset(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that snapshot reflects area reset."""
        # Place stuff
        test_ground.place_iron_patch(x=0, y=0, size=16, amount=5000)
        test_ground.place_entity("stone-furnace", x=10, y=10)
        
        metadata_before = test_ground.get_test_metadata()
        assert metadata_before["resource_count"] > 0
        assert metadata_before["entity_count"] > 0
        
        # Reset
        test_ground.reset_test_area()
        
        metadata_after = test_ground.get_test_metadata()
        assert metadata_after["resource_count"] == 0
        assert metadata_after["entity_count"] == 0
    
    def test_snapshot_metadata_structure(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that metadata has correct structure."""
        metadata = test_ground.get_test_metadata()
        
        # Verify structure
        assert "metadata" in metadata
        assert "resources" in metadata
        assert "entities" in metadata
        assert "resource_count" in metadata
        assert "entity_count" in metadata
        
        # Verify types (resources and entities are dicts, not lists)
        assert isinstance(metadata["resources"], dict)
        assert isinstance(metadata["entities"], dict)
        assert isinstance(metadata["resource_count"], int)
        assert isinstance(metadata["entity_count"], int)
    
    def test_snapshot_bounds_match_test_area(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that snapshot bounds match test area."""
        bounds = test_ground.get_test_bounds()
        
        assert bounds["left_top"]["x"] == -256
        assert bounds["left_top"]["y"] == -256
        assert bounds["right_bottom"]["x"] == 256
        assert bounds["right_bottom"]["y"] == 256
    
    def test_snapshot_area_size_correct(self, factory_instance: PlayingFactory, test_ground: TestGround):
        """Test that test area size is correct."""
        size = test_ground.get_test_area_size()
        assert size == 512
