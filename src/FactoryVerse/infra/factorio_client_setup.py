#!/usr/bin/env python3
"""Factorio client setup for FactoryVerse."""

import os
import platform
import shutil
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ============================================================================
# CONFIGURATION
# ============================================================================

# Client RCON configuration
CLIENT_RCON_HOST = "127.0.0.1"
CLIENT_RCON_PORT = 27100
CLIENT_RCON_PASSWORD = "factorio"

# Enable Lua UDP for client connections
ENABLE_FACTORIO_UDP = True


def _detect_factorio_dir() -> Path:
    """Detect local Factorio directory."""
    os_name = platform.system()
    if os_name == "Darwin":
        return Path.home() / "Library" / "Application Support" / "factorio"
    elif os_name == "Windows":
        appdata = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
        return Path(appdata) / "Factorio"
    else:  # Linux
        return Path.home() / ".factorio"


def _get_mod_path() -> Path:
    """Get local Factorio mod directory."""
    return _detect_factorio_dir() / "mods"


def _get_scenario_path() -> Path:
    """Get local Factorio scenario directory."""
    return _detect_factorio_dir() / "scenarios"


def get_client_script_output_dir() -> Path:
    """
    Get script-output directory for Factorio client.
    
    Returns:
        Path to client script-output directory
    """
    return _detect_factorio_dir() / "script-output"


def clear_client_snapshot_dir() -> None:
    """
    Clear the snapshot directory for Factorio client.
    
    Removes all files in script-output/factoryverse/snapshots to ensure
    a clean state on client launch.
    """
    script_output_dir = get_client_script_output_dir()
    snapshot_dir = script_output_dir / "factoryverse" / "snapshots"
    
    if snapshot_dir.exists():
        print(f"🧹 Clearing client snapshot directory: {snapshot_dir}")
        shutil.rmtree(snapshot_dir)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        print("✓ Client snapshot directory cleared")
    else:
        # Ensure parent directories exist
        snapshot_dir.mkdir(parents=True, exist_ok=True)


def get_factorio_log_path() -> Path:
    """
    Get the path to factorio-current.log file.
    
    Based on Factorio wiki: https://wiki.factorio.com/Application_directory
    - Windows: %appdata%\\Factorio\\factorio-current.log
    - macOS: ~/Library/Application Support/factorio/factorio-current.log
    - Linux: ~/.factorio/factorio-current.log
    
    Returns:
        Path to factorio-current.log file
    """
    factorio_dir = _detect_factorio_dir()
    return factorio_dir / "factorio-current.log"


def read_factorio_log(follow: bool = False) -> None:
    """
    Read and display factorio-current.log file.
    
    Args:
        follow: If True, follow the log file (like tail -f)
    """
    log_path = get_factorio_log_path()
    
    if not log_path.exists():
        print(f"❌ Log file not found at: {log_path}", file=sys.stderr)
        sys.exit(1)
    
    try:
        if follow:
            # Follow mode - stream the log file
            import time
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Seek to end of file
                f.seek(0, 2)
                print(f"📋 Following log file: {log_path}")
                print("Press Ctrl+C to stop...")
                print("-" * 80)
                try:
                    while True:
                        line = f.readline()
                        if line:
                            print(line, end='')
                        else:
                            time.sleep(0.1)
                except KeyboardInterrupt:
                    print("\n✅ Stopped following log")
        else:
            # Read and print entire file
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                print(f.read(), end='')
    except PermissionError:
        print(f"❌ Permission denied: {log_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error reading log file: {e}", file=sys.stderr)
        sys.exit(1)


def _ensure_mod_list_exists(mod_path: Path) -> None:
    """Ensure mod-list.json exists."""
    mod_list_path = mod_path / "mod-list.json"
    if not mod_list_path.exists():
        mod_list = {
            "mods": [
                {"name": "base", "enabled": True},
            ]
        }
        mod_list_path.write_text(json.dumps(mod_list, indent=2))


def _load_mod_list(mod_path: Path) -> dict:
    """Load mod-list.json."""
    mod_list_path = mod_path / "mod-list.json"
    if mod_list_path.exists():
        return json.loads(mod_list_path.read_text())
    return {"mods": [{"name": "base", "enabled": True}]}


def _save_mod_list(mod_path: Path, mod_list: dict) -> None:
    """Save mod-list.json."""
    (mod_path / "mod-list.json").write_text(json.dumps(mod_list, indent=2))


def _update_mod_list(mod_path: Path, mod_name: str, enabled: bool) -> None:
    """Add or update a mod in mod-list.json."""
    mod_list = _load_mod_list(mod_path)
    
    # Find or create mod entry
    mod_entry = None
    for mod in mod_list.get("mods", []):
        if mod.get("name") == mod_name:
            mod_entry = mod
            break
    
    if mod_entry:
        mod_entry["enabled"] = enabled
    else:
        mod_list.setdefault("mods", []).append({"name": mod_name, "enabled": enabled})
    
    _save_mod_list(mod_path, mod_list)


def setup_client(verse_mod_dir: Path, scenario: str = "test_scenario", force: bool = False, project_scenarios_dir: Optional[Path] = None) -> None:
    """
    Setup client with factorio_verse mod and scenarios.
    
    Args:
        verse_mod_dir: Path to factorio_verse mod directory
        scenario: Scenario name to setup
        force: Force copy scenario even if it exists
        project_scenarios_dir: Path to project scenarios directory (for copying non-factorio_verse scenarios)
    """
    mod_path = _get_mod_path()
    scenario_path = _get_scenario_path()
    
    # Ensure directories exist
    mod_path.mkdir(parents=True, exist_ok=True)
    scenario_path.mkdir(parents=True, exist_ok=True)
    
    # Ensure mod-list.json exists
    _ensure_mod_list_exists(mod_path)
    
    print(f"📱 Setting up Factorio client (scenario: {scenario})")
    
    if scenario == "factorio_verse":
        # Always copy factorio_verse as a scenario
        print("📋 Copying factorio_verse as scenario...")
        client_scenario_dir = scenario_path / "factorio_verse"
        
        # Remove old scenario if exists (always overwrite for factorio_verse)
        if client_scenario_dir.exists():
            shutil.rmtree(client_scenario_dir)
        
        # Copy to scenario directory
        shutil.copytree(verse_mod_dir, client_scenario_dir)
        
        # Disable factorio_verse in mod-list (it's a scenario now, not a mod)
        _update_mod_list(mod_path, "factorio_verse", False)
        print("✓ factorio_verse copied as scenario")
        print("🚫 factorio_verse: disabled (used as scenario)")
    else:
        # Copy factorio_verse as a mod
        print("📦 Copying factorio_verse mod...")
        client_mod_dir = mod_path / "factorio_verse"
        
        # Remove old mod if exists
        if client_mod_dir.exists():
            shutil.rmtree(client_mod_dir)
        
        # Copy to mod directory
        shutil.copytree(verse_mod_dir, client_mod_dir)
        
        # Enable factorio_verse in mod-list
        _update_mod_list(mod_path, "factorio_verse", True)
        print("✓ factorio_verse mod copied")
        
        # Handle other scenarios if project_scenarios_dir is provided
        if project_scenarios_dir:
            client_scenario_dir = scenario_path / scenario
            project_scenario_dir = project_scenarios_dir / scenario
            
            # Check if scenario needs to be copied
            should_copy = force or not client_scenario_dir.exists()
            
            if should_copy:
                if project_scenario_dir.exists():
                    if client_scenario_dir.exists():
                        shutil.rmtree(client_scenario_dir)
                    print(f"📋 Copying scenario '{scenario}'...")
                    shutil.copytree(project_scenario_dir, client_scenario_dir)
                    print(f"✓ Scenario '{scenario}' copied")
                else:
                    print(f"⚠️  Scenario '{scenario}' not found in project")
            else:
                print(f"ℹ️  Scenario '{scenario}' already exists (use --force to overwrite)")
    
    # Ensure DLC mods are disabled
    dlc_mods = ["space-age", "quality", "elevated-rails"]
    for dlc_mod in dlc_mods:
        _update_mod_list(mod_path, dlc_mod, False)
        print(f"🚫 {dlc_mod}: disabled")
    
    print("✅ Client setup complete!")


def _find_factorio_executable() -> Path:
    """Find Factorio client executable based on OS."""
    os_name = platform.system()
    
    if os_name == "Darwin":
        # macOS
        default_path = Path.home() / "Library" / "Application Support" / "Steam" / "steamapps" / "common" / "Factorio" / "factorio.app" / "Contents" / "MacOS" / "factorio"
    elif os_name == "Windows":
        # Windows
        default_path = Path("C:/Program Files (x86)/Steam/steamapps/common/Factorio/bin/x64/factorio.exe")
    else:  # Linux
        # Linux
        default_path = Path.home() / ".steam" / "steam" / "steamapps" / "common" / "Factorio" / "bin" / "x64" / "factorio"
    
    if default_path.exists():
        return default_path
    
    raise FileNotFoundError(f"Factorio executable not found at {default_path}")


def launch_factorio_client() -> None:
    """Launch Factorio client with optional UDP support."""
    try:
        # Clear snapshot directory before launch
        clear_client_snapshot_dir()
        
        factorio_exe = _find_factorio_executable()
        
        print(f"🎮 Launching Factorio client: {factorio_exe}")
        
        command = [str(factorio_exe)]
        if ENABLE_FACTORIO_UDP:
            print("⚠️  WARNING: Launching Factorio client with UDP enabled (--enable-lua-udp)")
            command.extend(["--enable-lua-udp", "34200"])
        
        subprocess.Popen(command)
        print("✅ Factorio client launched!")
    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error launching Factorio: {e}", file=sys.stderr)
        sys.exit(1)


def sync_hotreload_to_client(verse_mod_dir: Path) -> None:
    """Sync Lua files to client scenario directory (and temp) and trigger reload via RCON.

    Rationale:
    - Factorio client reloads scripts from the active scenario path. If we only
      sync to the temp/currently-playing directory, a reload may repopulate that
      directory from the scenario, effectively reverting our changes. To ensure
      consistency, update the installed scenario directory first, then (optionally)
      mirror to temp for immediate reload, and finally call game.reload_script().
    """
    try:
        factorio_dir = _detect_factorio_dir()
        scenario_dir = factorio_dir / "scenarios" / "factorio_verse"
        temp_dir = factorio_dir / "temp" / "currently-playing"
        scenario_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"📋 Syncing factorio_verse files to client scenario dir...")
        print(f"   Source: {verse_mod_dir}")
        print(f"   Scenario: {scenario_dir}")
        
        # First, sync to the installed scenario directory
        result = subprocess.run(
            ["rsync", "-r", "--delete", f"{verse_mod_dir}/", str(scenario_dir) + "/"],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode == 0:
            files_copied = len(list(verse_mod_dir.rglob("*.lua")))
            print(f"✓ Files synced to client scenario directory ({files_copied} file(s))")
        else:
            print(f"⚠️  rsync returned code {result.returncode}")
            if result.stderr:
                print(f"   Error: {result.stderr}")
        
        # Then, mirror to temp/currently-playing to support immediate reload
        print(f"📋 Mirroring files to client temp dir...")
        print(f"   Temp: {temp_dir}")
        result_temp = subprocess.run(
            ["rsync", "-r", "--delete", f"{verse_mod_dir}/", str(temp_dir) + "/"],
            capture_output=True,
            text=True,
            check=False
        )
        if result_temp.returncode == 0:
            print("✓ Files mirrored to client temp directory")
        else:
            print(f"⚠️  rsync (temp) returned code {result_temp.returncode}")
            if result_temp.stderr:
                print(f"   Error: {result_temp.stderr}")

        # Wait for filesystem to flush
        import time
        time.sleep(1)
        
        # Trigger reload via client RCON
        print("🔌 Connecting to client RCON...")
        try:
            from factorio_rcon import RCONClient
            rcon = RCONClient(CLIENT_RCON_HOST, CLIENT_RCON_PORT, CLIENT_RCON_PASSWORD)
            rcon.connect()
            print("✓ RCON connected")
            
            # Reload scripts
            print("🔄 Triggering game.reload_script()...")
            response = rcon.send_command("/c game.reload_script();game.print('Scripts reloaded');rcon.print('Scripts reloaded')")
            print(f"✓ Reload triggered: {response}")
            rcon.close()
            
        except Exception as e:
            print(f"⚠️  Could not connect to client RCON at {CLIENT_RCON_HOST}:{CLIENT_RCON_PORT}")
            print(f"   Error: {e}")
            print(f"   Manual reload: Press F5 or run `/c game.reload_script()` in console")
        
    except Exception as e:
        print(f"❌ Hotreload sync failed: {e}")
