#!/usr/bin/env python3
"""Factorio client setup for FactoryVerse."""

import os
import platform
import shutil
import json
import subprocess
import sys
import hashlib
from pathlib import Path
from typing import Optional

from FactoryVerse.environment.config import get_config


def _get_client_rcon_config():
    """Get client RCON configuration from unified config."""
    config = get_config()
    return config.rcon_host, config.rcon_client_port, config.rcon_password


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

            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                # Seek to end of file
                f.seek(0, 2)
                print(f"📋 Following log file: {log_path}")
                print("Press Ctrl+C to stop...")
                print("-" * 80)
                try:
                    while True:
                        line = f.readline()
                        if line:
                            print(line, end="")
                        else:
                            time.sleep(0.1)
                except KeyboardInterrupt:
                    print("\n✅ Stopped following log")
        else:
            # Read and print entire file
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                print(f.read(), end="")
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


def _calculate_directory_hash(directory: Path) -> str:
    """Calculate SHA256 hash of all files in a directory.
    
    Args:
        directory: Path to directory to hash
        
    Returns:
        Hexadecimal hash string
    """
    hasher = hashlib.sha256()
    
    # Get all files sorted by path for deterministic hashing
    all_files = sorted(directory.rglob("*"))
    
    for file_path in all_files:
        if file_path.is_file():
            # Include relative path in hash
            rel_path = file_path.relative_to(directory)
            hasher.update(str(rel_path).encode())
            
            # Include file contents
            try:
                with open(file_path, "rb") as f:
                    hasher.update(f.read())
            except (IOError, OSError):
                # Skip files we can't read
                pass
    
    return hasher.hexdigest()


def _get_mod_hash_file(mod_path: Path, mod_name: str) -> Path:
    """Get path to hash file for a mod.
    
    Args:
        mod_path: Factorio mods directory
        mod_name: Mod name (e.g., 'fv_embodied_agent')
        
    Returns:
        Path to hash file
    """
    return mod_path / f".{mod_name}.hash"


def _get_mod_hash(mod_path: Path, mod_name: str) -> Optional[str]:
    """Get stored hash for a mod.
    
    Args:
        mod_path: Factorio mods directory
        mod_name: Mod name
        
    Returns:
        Hash string if exists, None otherwise
    """
    hash_file = _get_mod_hash_file(mod_path, mod_name)
    if hash_file.exists():
        return hash_file.read_text().strip()
    return None


def _save_mod_hash(mod_path: Path, mod_name: str, hash_value: str) -> None:
    """Save hash for a mod.
    
    Args:
        mod_path: Factorio mods directory
        mod_name: Mod name
        hash_value: Hash to save
    """
    hash_file = _get_mod_hash_file(mod_path, mod_name)
    hash_file.write_text(hash_value)


def _mod_needs_update(source_dir: Path, mod_path: Path, mod_name: str) -> bool:
    """Check if mod needs to be updated based on hash comparison.

    Args:
        source_dir: Source mod directory
        mod_path: Factorio mods directory
        mod_name: Mod name

    Returns:
        True if mod needs update, False if hash matches
    """
    if not source_dir.exists():
        return True

    current_hash = _calculate_directory_hash(source_dir)
    stored_hash = _get_mod_hash(mod_path, mod_name)

    if stored_hash != current_hash:
        # Update stored hash
        _save_mod_hash(mod_path, mod_name, current_hash)
        return True

    return False


# =============================================================================
# Scenario Hash Functions (same pattern as mods)
# =============================================================================


def _get_scenario_hash_file(scenario_path: Path, scenario_name: str) -> Path:
    """Get path to hash file for a scenario.

    Args:
        scenario_path: Factorio scenarios directory
        scenario_name: Scenario name

    Returns:
        Path to hash file
    """
    return scenario_path / f".{scenario_name}.hash"


def _get_scenario_hash(scenario_path: Path, scenario_name: str) -> Optional[str]:
    """Get stored hash for a scenario.

    Args:
        scenario_path: Factorio scenarios directory
        scenario_name: Scenario name

    Returns:
        Hash string if exists, None otherwise
    """
    hash_file = _get_scenario_hash_file(scenario_path, scenario_name)
    if hash_file.exists():
        return hash_file.read_text().strip()
    return None


def _save_scenario_hash(scenario_path: Path, scenario_name: str, hash_value: str) -> None:
    """Save hash for a scenario.

    Args:
        scenario_path: Factorio scenarios directory
        scenario_name: Scenario name
        hash_value: Hash to save
    """
    hash_file = _get_scenario_hash_file(scenario_path, scenario_name)
    hash_file.write_text(hash_value)


def _scenario_needs_update(source_dir: Path, scenario_path: Path, scenario_name: str) -> bool:
    """Check if scenario needs to be updated based on hash comparison.

    Args:
        source_dir: Source scenario directory
        scenario_path: Factorio scenarios directory
        scenario_name: Scenario name

    Returns:
        True if scenario needs update, False if hash matches
    """
    if not source_dir.exists():
        return True

    current_hash = _calculate_directory_hash(source_dir)
    stored_hash = _get_scenario_hash(scenario_path, scenario_name)

    if stored_hash != current_hash:
        # Update stored hash
        _save_scenario_hash(scenario_path, scenario_name, current_hash)
        return True

    return False


def _update_mod_list(mod_path: Path, mod_name: str, enabled: bool) -> None:
    """Add or update a mod in mod-list.json.

    This function preserves all existing mod entries and only modifies the specified mod's
    enabled status. The mod-list.json structure is:
    {
      "mods": [
        {"name": "base", "enabled": true},
        {"name": "some-mod", "enabled": false},
        ...
      ]
    }
    """
    mod_list = _load_mod_list(mod_path)

    # Ensure "mods" array exists
    if "mods" not in mod_list:
        mod_list["mods"] = []

    # Find existing mod entry
    mod_entry = None
    for mod in mod_list["mods"]:
        if mod.get("name") == mod_name:
            mod_entry = mod
            break

    if mod_entry:
        # Update existing entry - only change the "enabled" field
        mod_entry["enabled"] = enabled
    else:
        # Add new entry if mod doesn't exist in the list
        mod_list["mods"].append({"name": mod_name, "enabled": enabled})

    # Save the entire mod list (preserving all other mods)
    _save_mod_list(mod_path, mod_list)


def setup_client(
    work_dir_or_mod_dir: Path,
    scenario: Optional[str] = None,
    force: bool = False,
    project_scenarios_dir: Optional[Path] = None,
) -> None:
    """
    Setup client with FactoryVerse mods and scenarios.

    FactoryVerse mods (fv_embodied_agent + fv_snapshot) are ALWAYS loaded.
    This is the only supported mode.

    NOTE: After running setup, you must restart Factorio for mod/scenario changes to take effect.
    Factorio only loads mods and scenarios at startup, not during runtime.

    Args:
        work_dir_or_mod_dir: Path to work directory (preferred) or mod directory (for backward compatibility)
        scenario: Scenario name to setup (None = mods only, no scenario)
        force: Force copy scenario even if it exists
        project_scenarios_dir: Path to project scenarios directory (for copying scenarios)
    """
    mod_path = _get_mod_path()
    scenario_path = _get_scenario_path()

    # Derive work_dir from the input path
    if work_dir_or_mod_dir.name in [
        "factorio_verse",
        "fv_embodied_agent",
        "fv_snapshot",
    ]:
        work_dir = work_dir_or_mod_dir.parent.parent
    else:
        work_dir = work_dir_or_mod_dir

    embodied_agent_mod_dir = work_dir / "src" / "fv_embodied_agent"
    snapshot_mod_dir = work_dir / "src" / "fv_snapshot"
    placement_hints_mod_dir = work_dir / "src" / "fv_placement_hints"

    # Ensure directories exist
    mod_path.mkdir(parents=True, exist_ok=True)
    scenario_path.mkdir(parents=True, exist_ok=True)

    # Ensure mod-list.json exists
    _ensure_mod_list_exists(mod_path)

    scenario_info = f"scenario: {scenario}" if scenario else "mods only"
    print(f"📱 Setting up Factorio client ({scenario_info})")

    # Check that both mod directories exist
    if not embodied_agent_mod_dir.exists():
        raise RuntimeError(
            f"FV Embodied Agent mod not found at {embodied_agent_mod_dir}"
        )
    if not snapshot_mod_dir.exists():
        raise RuntimeError(f"FV Snapshot mod not found at {snapshot_mod_dir}")

    # Remove all existing FactoryVerse mod copies
    print("📦 Removing existing FactoryVerse mod copies...")
    for old_mod_pattern in [
        "fv_embodied_agent*",
        "fv_snapshot*",
        "fv_placement_hints*",
        "factorio_verse*",
    ]:
        for old_mod in mod_path.glob(old_mod_pattern):
            if old_mod.is_dir():
                print(f"   Removing {old_mod.name}...")
                shutil.rmtree(old_mod)

    # Also remove any deprecated scenario copies if they exist
    for deprecated_scenario in ["factorio_verse", "fv_embodied_agent", "fv_snapshot"]:
        client_scenario_dir = scenario_path / deprecated_scenario
        if client_scenario_dir.exists():
            print(f"   Removing deprecated scenario at {client_scenario_dir}...")
            shutil.rmtree(client_scenario_dir)

    # Prepare fv_embodied_agent mod
    print("📦 Checking fv_embodied_agent mod...")
    info_json_path = embodied_agent_mod_dir / "info.json"
    if info_json_path.exists():
        info = json.loads(info_json_path.read_text())
        mod_name = info.get("name", "fv_embodied_agent")
        mod_version = info.get("version", "1.0.0")
    else:
        mod_name = "fv_embodied_agent"
        mod_version = "1.0.0"

    client_mod_dir = mod_path / f"{mod_name}_{mod_version}"
    
    # Check if mod needs update based on hash
    if force or _mod_needs_update(embodied_agent_mod_dir, mod_path, mod_name):
        if client_mod_dir.exists():
            shutil.rmtree(client_mod_dir)
        print(f"   Updating {mod_name} mod (hash changed or --force)...")
        shutil.copytree(embodied_agent_mod_dir, client_mod_dir)
        _update_mod_list(mod_path, mod_name, True)
        print(f"✓ {mod_name} mod updated as {client_mod_dir.name}")
    else:
        # Ensure mod directory exists even if hash matches
        if not client_mod_dir.exists():
            print(f"   Mod directory missing, copying {mod_name}...")
            shutil.copytree(embodied_agent_mod_dir, client_mod_dir)
            _update_mod_list(mod_path, mod_name, True)
            print(f"✓ {mod_name} mod copied as {client_mod_dir.name}")
        else:
            _update_mod_list(mod_path, mod_name, True)
            print(f"✓ {mod_name} mod up to date (hash unchanged)")

    # Prepare fv_snapshot mod
    print("📦 Checking fv_snapshot mod...")
    info_json_path = snapshot_mod_dir / "info.json"
    if info_json_path.exists():
        info = json.loads(info_json_path.read_text())
        mod_name = info.get("name", "fv_snapshot")
        mod_version = info.get("version", "1.0.0")
    else:
        mod_name = "fv_snapshot"
        mod_version = "1.0.0"

    client_mod_dir = mod_path / f"{mod_name}_{mod_version}"
    
    # Check if mod needs update based on hash
    if force or _mod_needs_update(snapshot_mod_dir, mod_path, mod_name):
        if client_mod_dir.exists():
            shutil.rmtree(client_mod_dir)
        print(f"   Updating {mod_name} mod (hash changed or --force)...")
        shutil.copytree(snapshot_mod_dir, client_mod_dir)
        _update_mod_list(mod_path, mod_name, True)
        print(f"✓ {mod_name} mod updated as {client_mod_dir.name}")
    else:
        # Ensure mod directory exists even if hash matches
        if not client_mod_dir.exists():
            print(f"   Mod directory missing, copying {mod_name}...")
            shutil.copytree(snapshot_mod_dir, client_mod_dir)
            _update_mod_list(mod_path, mod_name, True)
            print(f"✓ {mod_name} mod copied as {client_mod_dir.name}")
        else:
            _update_mod_list(mod_path, mod_name, True)
            print(f"✓ {mod_name} mod up to date (hash unchanged)")

    # Prepare fv_placement_hints mod
    print("📦 Checking fv_placement_hints mod...")
    if placement_hints_mod_dir.exists():
        info_json_path = placement_hints_mod_dir / "info.json"
        if info_json_path.exists():
            info = json.loads(info_json_path.read_text())
            mod_name = info.get("name", "fv_placement_hints")
            mod_version = info.get("version", "1.0.0")
        else:
            mod_name = "fv_placement_hints"
            mod_version = "1.0.0"

        client_mod_dir = mod_path / f"{mod_name}_{mod_version}"

        # Check if mod needs update based on hash
        if force or _mod_needs_update(placement_hints_mod_dir, mod_path, mod_name):
            if client_mod_dir.exists():
                shutil.rmtree(client_mod_dir)
            print(f"   Updating {mod_name} mod (hash changed or --force)...")
            shutil.copytree(placement_hints_mod_dir, client_mod_dir)
            _update_mod_list(mod_path, mod_name, True)
            print(f"✓ {mod_name} mod updated as {client_mod_dir.name}")
        else:
            # Ensure mod directory exists even if hash matches
            if not client_mod_dir.exists():
                print(f"   Mod directory missing, copying {mod_name}...")
                shutil.copytree(placement_hints_mod_dir, client_mod_dir)
                _update_mod_list(mod_path, mod_name, True)
                print(f"✓ {mod_name} mod copied as {client_mod_dir.name}")
            else:
                _update_mod_list(mod_path, mod_name, True)
                print(f"✓ {mod_name} mod up to date (hash unchanged)")
    else:
        print("⚠️  fv_placement_hints mod not found, skipping...")

    # Handle scenario if project_scenarios_dir is provided and scenario is specified
    if project_scenarios_dir and scenario:
        print(f"📋 Checking scenario '{scenario}'...")
        client_scenario_dir = scenario_path / scenario
        project_scenario_dir = project_scenarios_dir / scenario

        if not project_scenario_dir.exists():
            print(f"⚠️  Scenario '{scenario}' not found in project at {project_scenario_dir}")
        else:
            # Use hash-based detection (same pattern as mods)
            if force or _scenario_needs_update(project_scenario_dir, scenario_path, scenario):
                if client_scenario_dir.exists():
                    shutil.rmtree(client_scenario_dir)
                print(f"   Updating scenario '{scenario}' (hash changed or --force)...")
                shutil.copytree(project_scenario_dir, client_scenario_dir)
                print(f"✓ Scenario '{scenario}' updated")
            else:
                # Ensure scenario directory exists even if hash matches
                if not client_scenario_dir.exists():
                    print(f"   Scenario directory missing, copying '{scenario}'...")
                    shutil.copytree(project_scenario_dir, client_scenario_dir)
                    print(f"✓ Scenario '{scenario}' copied")
                else:
                    print(f"✓ Scenario '{scenario}' up to date (hash unchanged)")
    elif not scenario:
        print("ℹ️  No scenario specified, skipping scenario setup")

    # Ensure DLC mods are disabled
    dlc_mods = ["space-age", "quality", "elevated-rails"]
    for dlc_mod in dlc_mods:
        _update_mod_list(mod_path, dlc_mod, False)
        print(f"🚫 {dlc_mod}: disabled")

    print("✅ Client setup complete!")
    print(
        "ℹ️  Note: Restart Factorio if it's already running for changes to take effect."
    )


def _find_steam_executable() -> Optional[Path]:
    """Find Steam executable on macOS for launching games via -applaunch."""
    if platform.system() != "Darwin":
        return None
    
    # Check standard location
    steam_path = Path("/Applications/Steam.app/Contents/MacOS/steam_osx")
    if steam_path.exists():
        return steam_path
    
    # Check alternative location
    alt_path = (
        Path.home()
        / "Library"
        / "Application Support"
        / "Steam"
        / "Steam.AppBundle"
        / "Steam"
        / "Contents"
        / "MacOS"
        / "steam_osx"
    )
    if alt_path.exists():
        return alt_path
    
    return None


def _find_factorio_executable() -> Path:
    """Find Factorio client executable based on OS."""
    os_name = platform.system()

    if os_name == "Darwin":
        # macOS
        default_path = (
            Path.home()
            / "Library"
            / "Application Support"
            / "Steam"
            / "steamapps"
            / "common"
            / "Factorio"
            / "factorio.app"
            / "Contents"
            / "MacOS"
            / "factorio"
        )
    elif os_name == "Windows":
        # Windows
        default_path = Path(
            "C:/Program Files (x86)/Steam/steamapps/common/Factorio/bin/x64/factorio.exe"
        )
    else:  # Linux
        # Linux
        default_path = (
            Path.home()
            / ".steam"
            / "steam"
            / "steamapps"
            / "common"
            / "Factorio"
            / "bin"
            / "x64"
            / "factorio"
        )

    if default_path.exists():
        return default_path

    raise FileNotFoundError(f"Factorio executable not found at {default_path}")


def launch_factorio_client() -> None:
    """Launch Factorio client with UDP support for agent communication."""
    try:
        # Clear snapshot directory before launch
        clear_client_snapshot_dir()

        config = get_config()
        
        # On macOS, use Steam -applaunch to bypass the popup dialog
        # Factorio App ID: 427520
        use_steam_launch = platform.system() == "Darwin"
        steam_exe = None
        if use_steam_launch:
            steam_exe = _find_steam_executable()
            if not steam_exe:
                print("⚠️  Steam executable not found, falling back to direct launch")
                use_steam_launch = False

        if use_steam_launch:
            # Use Steam -applaunch on macOS
            command = [str(steam_exe), "-applaunch", "427520"]
            print(f"🎮 Launching Factorio via Steam: {steam_exe}")
        else:
            # Direct executable launch (Windows, Linux, or macOS fallback)
            factorio_exe = _find_factorio_executable()
            command = [str(factorio_exe)]
            print(f"🎮 Launching Factorio client: {factorio_exe}")

        # Always enable UDP for agent and snapshot communication
        print("📡 Launching Factorio client with UDP enabled (--enable-lua-udp)")
        command.extend(["--enable-lua-udp", str(config.enable_udp_port)])

        subprocess.Popen(command)
        print("✅ Factorio client launched!")
    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error launching Factorio: {e}", file=sys.stderr)
        sys.exit(1)


def dump_data_raw(
    work_dir: Path,
    scenario: str = "test-ground",
    force: bool = False,
    project_scenarios_dir: Optional[Path] = None,
) -> Path:
    """Dump Factorio's data.raw to JSON using --dump-data flag."""
    setup_client(
        work_dir,
        scenario=scenario,
        force=force,
        project_scenarios_dir=project_scenarios_dir,
    )

    factorio_exe = _find_factorio_executable()
    script_output_dir = get_client_script_output_dir()
    script_output_dir.mkdir(parents=True, exist_ok=True)

    print(f"📦 Dumping data.raw to JSON...")
    subprocess.run([str(factorio_exe), "--dump-data"], check=True, timeout=300)

    dump_file = script_output_dir / "data-raw-dump.json"
    if not dump_file.exists():
        raise RuntimeError(f"Dump file not found: {dump_file}")

    print(f"✅ Data dump complete: {dump_file}")
    return dump_file


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
            check=False,
        )

        if result.returncode == 0:
            files_copied = len(list(verse_mod_dir.rglob("*.lua")))
            print(
                f"✓ Files synced to client scenario directory ({files_copied} file(s))"
            )
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
            check=False,
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
        rcon_host, rcon_port, rcon_password = _get_client_rcon_config()
        try:
            from factorio_rcon import RCONClient

            rcon = RCONClient(rcon_host, rcon_port, rcon_password)
            rcon.connect()
            print("✓ RCON connected")

            # Reload scripts
            print("🔄 Triggering game.reload_script()...")
            response = rcon.send_command(
                "/c game.reload_script();game.print('Scripts reloaded');rcon.print('Scripts reloaded')"
            )
            print(f"✓ Reload triggered: {response}")
            rcon.close()

        except Exception as e:
            print(f"⚠️  Could not connect to client RCON at {rcon_host}:{rcon_port}")
            print(f"   Error: {e}")
            print(
                "   Manual reload: Press F5 or run `/c game.reload_script()` in console"
            )

    except Exception as e:
        print(f"❌ Hotreload sync failed: {e}")
