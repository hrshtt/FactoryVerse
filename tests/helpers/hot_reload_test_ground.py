#!/usr/bin/env python3
"""Hot-reload helper for test-ground scenario during test development."""

import shutil
import time
from pathlib import Path
from factorio_rcon import RCONClient

# Configuration
RCON_HOST = "localhost"
RCON_PORT = 27100
RCON_PASSWORD = "factorio"

def get_factorio_dir() -> Path:
    """Get Factorio directory."""
    return Path.home() / "Library" / "Application Support" / "factorio"

def hot_reload_test_ground():
    """
    Hot-reload test-ground scenario.
    
    Steps:
    1. Copy scenario to temp/currently-playing
    2. Trigger game.reload_script() via RCON
    3. Re-register remote interfaces
    """
    factorio_dir = get_factorio_dir()
    # Go up from tests/helpers to project root, then to scenario
    project_scenario_dir = Path(__file__).parent.parent.parent / "src" / "factorio" / "scenarios" / "test-ground"
    temp_dir = factorio_dir / "temp" / "currently-playing"
    
    print("🔄 Hot-reloading test-ground scenario...")
    print(f"   Source: {project_scenario_dir}")
    print(f"   Target: {temp_dir}")
    
    # Copy scenario to temp/currently-playing (for running scenario)
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    shutil.copytree(project_scenario_dir, temp_dir)
    print(f"✓ Scenario copied to {temp_dir}")

    # ALSO copy to scenarios/test-ground (for standard load)
    scenarios_dir = factorio_dir / "scenarios" / "test-ground"
    if scenarios_dir.exists():
        shutil.rmtree(scenarios_dir)
    shutil.copytree(project_scenario_dir, scenarios_dir)
    print(f"✓ Scenario copied to {scenarios_dir}")
    
    # Wait for filesystem
    time.sleep(0.5)
    
    # Trigger reload via RCON
    try:
        print("🔌 Connecting to RCON...")
        rcon = RCONClient(RCON_HOST, RCON_PORT, RCON_PASSWORD)
        print("✓ RCON connected")
        
        # Reload scripts
        print("🔄 Triggering game.reload_script()...")
        response = rcon.send_command("/c game.reload_script()")
        print(f"✓ Scripts reloaded")
        
        # Wait a moment for reload
        time.sleep(0.5)
        
        # Verify test_ground interface is available
        print("🔍 Verifying test_ground interface...")
        response = rcon.send_command("/c rcon.print(remote.interfaces.test_ground and 'OK' or 'MISSING')")
        if response == "OK":
            print("✅ test_ground interface registered successfully")
        else:
            print("⚠️  test_ground interface not found - may need manual restart")
        
        rcon.close()
        
    except Exception as e:
        print(f"❌ RCON error: {e}")
        print("   Try restarting Factorio or running `/c game.reload_script()` manually")
        return False
    
    return True

if __name__ == "__main__":
    success = hot_reload_test_ground()
    exit(0 if success else 1)
