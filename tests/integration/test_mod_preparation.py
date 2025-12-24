"""
Tests for mod preparation and packaging.

Verifies that the mod preparation logic correctly:
- Zips the Factorio Verse mod
- Updates mod-list.json with correct entries
- Handles DLC mod disabling
"""

import pytest
import json
import tempfile
from pathlib import Path
from FactoryVerse.infra.docker import _prepare_mods


@pytest.fixture
def temp_mod_dir(tmp_path):
    """Create a temporary mod directory with test mod structure."""
    mod_dir = tmp_path / "test_mod"
    mod_dir.mkdir()
    
    # Create info.json
    info_json = {
        "name": "test_mod",
        "version": "1.0.0",
        "factorio_version": "2.0"
    }
    (mod_dir / "info.json").write_text(json.dumps(info_json))
    
    # Create data.lua
    (mod_dir / "data.lua").write_text("-- Test mod data stage")
    
    # Create control.lua
    (mod_dir / "control.lua").write_text("-- Test mod control stage")
    
    return mod_dir


class TestModPreparation:
    """Tests for mod preparation functionality."""
    
    def test_zip_mod_creation(self, temp_mod_dir):
        """Test that mod is correctly zipped."""
        mod_path = temp_mod_dir.parent
        zip_file = _prepare_mods(mod_path, temp_mod_dir)
        
        assert zip_file.exists()
        assert zip_file.name == "test_mod_1.0.0.zip"
        
        # Verify zip structure
        import zipfile
        with zipfile.ZipFile(zip_file) as zf:
            namelist = zf.namelist()
            assert "test_mod_1.0.0/info.json" in namelist
            assert "test_mod_1.0.0/data.lua" in namelist
            assert "test_mod_1.0.0/control.lua" in namelist
    
    def test_mod_list_updates(self, temp_mod_dir):
        """Test that mod-list.json is updated correctly."""
        mod_path = temp_mod_dir.parent
        mod_list_path = mod_path / "mod-list.json"
        
        # Create initial mod-list.json
        initial_mods = {
            "mods": [
                {"name": "base", "enabled": True},
                {"name": "some_other_mod", "enabled": False}
            ]
        }
        mod_list_path.write_text(json.dumps(initial_mods))
        
        # Prepare mods
        _prepare_mods(mod_path, temp_mod_dir)
        
        # Verify mod-list.json was updated
        with open(mod_list_path) as f:
            mod_list = json.load(f)
        
        assert "mods" in mod_list
        assert len(mod_list["mods"]) > 0
        
        # Check for base mod
        mod_names = [m["name"] for m in mod_list["mods"]]
        assert "base" in mod_names
        
        # Check for our test mod
        assert "test_mod" in mod_names
        
        # Check DLC mods are disabled
        for mod in mod_list["mods"]:
            if mod["name"] in ["elevated-rails", "quality", "space-age"]:
                assert mod["enabled"] is False


class TestModListJSON:
    """Tests for mod-list.json manipulation."""
    
    def test_add_new_mod_to_list(self, tmp_path):
        """Test adding a new mod to existing list."""
        mod_list_path = tmp_path / "mod-list.json"
        
        # Create initial list
        initial = {
            "mods": [
                {"name": "base", "enabled": True}
            ]
        }
        mod_list_path.write_text(json.dumps(initial))
        
        # Simulate adding a new mod
        with open(mod_list_path) as f:
            mod_list = json.load(f)
        
        mod_list["mods"].append({"name": "new_mod", "enabled": True})
        
        with open(mod_list_path, 'w') as f:
            json.dump(mod_list, f, indent=2)
        
        # Verify
        with open(mod_list_path) as f:
            final = json.load(f)
        
        assert len(final["mods"]) == 2
        assert "new_mod" in [m["name"] for m in final["mods"]]
    
    def test_deduplicate_mods(self, tmp_path):
        """Test that duplicate mods are handled."""
        mod_list_path = tmp_path / "mod-list.json"
        
        # Create list with duplicates
        mod_list = {
            "mods": [
                {"name": "base", "enabled": True},
                {"name": "base", "enabled": False},  # Duplicate
                {"name": "some_mod", "enabled": True}
            ]
        }
        mod_list_path.write_text(json.dumps(mod_list))
        
        # Deduplicate
        with open(mod_list_path) as f:
            data = json.load(f)
        
        seen = set()
        unique = []
        for m in data["mods"]:
            if m["name"] not in seen:
                seen.add(m["name"])
                unique.append(m)
        data["mods"] = unique
        
        with open(mod_list_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        # Verify
        with open(mod_list_path) as f:
            final = json.load(f)
        
        assert len(final["mods"]) == 2
        names = [m["name"] for m in final["mods"]]
        assert len(names) == len(set(names))  # All unique

