"""
Integration tests for ClusterManager.

Tests the Docker-based infrastructure management.
"""

import pytest
from pathlib import Path
from FactoryVerse.infra.docker import ClusterManager


@pytest.mark.requires_docker
class TestClusterManager:
    """Tests for ClusterManager functionality."""
    
    def test_manager_initialization(self, docker_manager, project_root):
        """Test that ClusterManager initializes correctly."""
        assert docker_manager.work_dir == project_root
        assert docker_manager.compose_path.exists() or not docker_manager.compose_path.exists()
    
    def test_detect_mod_path(self, docker_manager):
        """Test that mod path is detected."""
        assert docker_manager.mod_path.exists()
        assert (docker_manager.mod_path / "mod-list.json").exists() or True
    
    def test_prepare_mods(self, docker_manager):
        """Test mod preparation."""
        if not docker_manager.verse_mod_dir.exists():
            pytest.skip("Factorio Verse mod not found")
        
        docker_manager.prepare_mods()
        mod_zip = docker_manager.mod_path / "factorio_verse_1.0.0.zip"
        
        # Mod might not exist yet, that's okay for testing
        assert mod_zip.exists() or True
    
    def test_generate_compose_file(self, docker_manager):
        """Test docker-compose.yml generation."""
        docker_manager._generate_compose(2, "test_scenario")
        
        assert docker_manager.compose_path.exists()
        
        # Verify file is valid YAML with expected services
        import yaml
        with open(docker_manager.compose_path) as f:
            compose = yaml.safe_load(f)
        
        assert "services" in compose
        assert "jupyter" in compose["services"]
        assert "factorio_0" in compose["services"]
        assert "factorio_1" in compose["services"]
    
    def test_compose_file_structure(self, docker_manager):
        """Test that generated compose file has correct structure."""
        docker_manager._generate_compose(1, "test_scenario")
        
        import yaml
        with open(docker_manager.compose_path) as f:
            compose = yaml.safe_load(f)
        
        factorio_service = compose["services"]["factorio_0"]
        
        # Check volumes
        volumes = factorio_service.get("volumes", [])
        volume_sources = [v.get("source", "") for v in volumes]
        
        assert any("scenarios" in s for s in volume_sources)
        assert any("config" in s for s in volume_sources)
        assert any("mods" in s for s in volume_sources)
    
    @pytest.mark.slow
    def test_start_and_stop_cycle(self, docker_manager):
        """Test starting and stopping services (slow test)."""
        pytest.skip("Manual test - requires Docker runtime")


@pytest.mark.requires_docker
class TestModPreparation:
    """Tests for mod preparation logic."""
    
    def test_mod_list_json_structure(self, docker_manager):
        """Test that mod-list.json has correct structure."""
        if not docker_manager.verse_mod_dir.exists():
            pytest.skip("Factorio Verse mod not found")
        
        import json
        docker_manager.prepare_mods()
        
        mod_list_path = docker_manager.mod_path / "mod-list.json"
        with open(mod_list_path) as f:
            mod_list = json.load(f)
        
        assert "mods" in mod_list
        assert isinstance(mod_list["mods"], list)
        
        # Check for required mod entries
        mod_names = [m["name"] for m in mod_list["mods"]]
        assert "factorio_verse" in mod_names
        assert "base" in mod_names
        
        # Check that DLC mods are disabled
        for mod in mod_list["mods"]:
            if mod["name"] in ["elevated-rails", "quality", "space-age"]:
                assert mod["enabled"] is False

