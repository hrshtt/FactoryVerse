"""
Integration tests for CLI commands.

Tests that the CLI correctly invokes ClusterManager methods.
"""

import pytest
from FactoryVerse.cli import SimpleExperimentTracker


class TestSimpleExperimentTracker:
    """Tests for file-based experiment tracking."""
    
    def test_tracker_initialization(self, tmp_path):
        """Test that tracker initializes correctly."""
        tracker = SimpleExperimentTracker(tmp_path)
        
        assert tracker.experiments == {}
        assert tracker.experiments_file.parent == tmp_path / ".fv-output"
    
    def test_add_experiment(self, tmp_path):
        """Test adding an experiment."""
        tracker = SimpleExperimentTracker(tmp_path)
        
        tracker.add_experiment("exp_1", "test_exp", 2, "test_scenario")
        
        assert "exp_1" in tracker.experiments
        assert tracker.experiments["exp_1"]["name"] == "test_exp"
        assert tracker.experiments["exp_1"]["num_servers"] == 2
    
    def test_list_experiments(self, tmp_path):
        """Test listing experiments."""
        tracker = SimpleExperimentTracker(tmp_path)
        
        tracker.add_experiment("exp_1", "test1", 1, "scenario1")
        tracker.add_experiment("exp_2", "test2", 2, "scenario2")
        
        experiments = tracker.list_experiments()
        assert len(experiments) == 2
    
    def test_persistence(self, tmp_path):
        """Test that experiments persist across instances."""
        tracker1 = SimpleExperimentTracker(tmp_path)
        tracker1.add_experiment("exp_1", "test_exp", 1, "test_scenario")
        
        # Create new tracker instance
        tracker2 = SimpleExperimentTracker(tmp_path)
        
        assert "exp_1" in tracker2.experiments
        assert tracker2.experiments["exp_1"]["name"] == "test_exp"

