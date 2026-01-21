#!/usr/bin/env python3
"""Factorio client lifecycle management (start/stop/restart)."""

import os
import signal
import subprocess
import json
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

from FactoryVerse.config import get_config
from .factorio_client_setup import (
    _find_factorio_executable,
    _find_steam_executable,
    clear_client_snapshot_dir,
    setup_client,
)


class FactorioClientManager:
    """Manages Factorio client lifecycle (start/stop/restart) with process tracking."""

    def __init__(self, work_dir: Path):
        self.work_dir = work_dir.resolve()
        self.output_dir = work_dir / ".fv-output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.pid_file = self.output_dir / "client.pid"
        self.state_file = self.output_dir / "client-state.json"
        self.saves_dir = self.output_dir / "saves"
        self.saves_dir.mkdir(parents=True, exist_ok=True)

    def start(
        self,
        scenario: Optional[str] = None,
        save_file: Optional[Path] = None,
        map_gen_settings: Optional[Path] = None,
        new_map: bool = False,
        map_name: Optional[str] = None,
        force_setup: bool = False,
        project_scenarios_dir: Optional[Path] = None,
    ) -> None:
        """Start Factorio client with optional scenario or save file.

        Args:
            scenario: Scenario name to load (e.g., 'base/freeplay' or 'test-ground')
            save_file: Absolute path to save file to load
            map_gen_settings: Absolute path to map generation settings JSON
            new_map: If True, create a new map (requires scenario or map_gen_settings)
            map_name: Name for new map save file (default: auto-generated)
            force_setup: Force re-setup of client mods/scenarios
            project_scenarios_dir: Path to project scenarios directory
        """
        # Check if already running
        if self.is_running():
            print("⚠️  Factorio client is already running")
            return

        config = get_config()
        factorio_exe = _find_factorio_executable()

        # Always setup client mods (base behavior)
        from .docker.factorio_server_manager import FactorioServerManager

        server_mgr = FactorioServerManager(self.work_dir, config)

        # Setup mods and optionally scenario (None = mods only)
        setup_client(
            self.work_dir,
            scenario=scenario,  # Pass through as-is (None = mods only, no scenario)
            force=force_setup,
            project_scenarios_dir=project_scenarios_dir or server_mgr.scenarios_dir,
        )

        clear_client_snapshot_dir()

        # On macOS, use Steam -applaunch to bypass the popup dialog
        # Factorio App ID: 427520
        use_steam_launch = sys.platform == "darwin"
        steam_exe = None
        if use_steam_launch:
            steam_exe = _find_steam_executable()
            if not steam_exe:
                print("⚠️  Steam executable not found, falling back to direct launch")
                use_steam_launch = False

        # Build command
        if use_steam_launch:
            # Use Steam -applaunch on macOS
            command = [str(steam_exe), "-applaunch", "427520"]
        else:
            # Direct executable launch (Windows, Linux, or macOS fallback)
            command = [str(factorio_exe)]
        
        command.extend(["--enable-lua-udp", str(config.enable_udp_port)])

        # Handle save file creation or loading
        final_save_path = None
        if new_map:
            # Create a new map
            if not scenario and not map_gen_settings:
                raise ValueError(
                    "Cannot create new map: must provide --scenario or --map-gen-settings"
                )

            # Generate save file name
            if map_name:
                save_filename = f"{map_name}.zip"
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                scenario_part = scenario.replace("/", "_") if scenario else "new_map"
                save_filename = f"{scenario_part}_{timestamp}.zip"

            final_save_path = self.saves_dir / save_filename

            # Create new map using --create flag (always use direct executable for this)
            create_command = [str(factorio_exe), "--create", str(final_save_path)]
            if map_gen_settings:
                create_command.extend(["--map-gen-settings", str(map_gen_settings)])

            print(f"🗺️  Creating new map: {final_save_path}")
            result = subprocess.run(
                create_command, check=True, capture_output=True, text=True
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to create map: {result.stderr}")
            print(f"✅ Map created successfully")

            # Now load the created save
            command.extend(["--load-game", str(final_save_path)])
        elif save_file:
            # Load existing save file
            save_path = Path(save_file)
            if not save_path.is_absolute():
                raise ValueError(f"Save file path must be absolute: {save_file}")
            if not save_path.exists():
                raise FileNotFoundError(f"Save file not found: {save_path}")
            command.extend(["--load-game", str(save_path)])
            final_save_path = save_path
        elif scenario:
            # Load scenario directly
            command.extend(["--load-scenario", scenario])
        else:
            # No scenario or save - just launch (will show main menu)
            print("⚠️  No scenario or save file specified, launching to main menu")

        # Launch process
        if use_steam_launch:
            print(f"🎮 Launching Factorio via Steam: {steam_exe}")
        else:
            print(f"🎮 Launching Factorio client: {factorio_exe}")
        if final_save_path:
            print(f"   Loading: {final_save_path}")
        elif scenario:
            print(f"   Scenario: {scenario}")

        process = subprocess.Popen(command)
        self._save_pid(process.pid)

        # Save state for restart
        self._save_state(
            scenario=scenario,
            save_file=str(final_save_path) if final_save_path else None,
            map_gen_settings=str(map_gen_settings) if map_gen_settings else None,
            new_map=new_map,
        )

        print(f"✅ Factorio client started (PID: {process.pid})")

    def stop(self, force: bool = False) -> None:
        """Stop Factorio client gracefully or forcefully.

        Args:
            force: If True, use SIGKILL instead of SIGTERM
        """
        pid = self._load_pid()

        # On macOS, if the PID from file is not running, we try to find it by name
        # because Steam might have restarted it with a different PID.
        if not pid or not self._is_process_running(pid):
            if sys.platform == "darwin":
                pid = self._find_factorio_pid_by_name()
                if pid:
                    print(
                        f"🔍 Found Factorio client via process name search (PID: {pid})"
                    )

        if not pid:
            print("⚠️  No client PID found (client may not be running)")
            return

        if not self._is_process_running(pid):
            print("⚠️  Client process not found (may have exited)")
            self._clear_pid()
            return

        try:
            if force:
                os.kill(pid, signal.SIGKILL)
                print(f"🛑 Forcefully killed Factorio client (PID: {pid})")
            else:
                os.kill(pid, signal.SIGTERM)
                print(f"🛑 Sent SIGTERM to Factorio client (PID: {pid})")
                # Wait a bit for graceful shutdown
                import time

                time.sleep(2)
                if self._is_process_running(pid):
                    print("⚠️  Client didn't exit gracefully, force killing...")
                    os.kill(pid, signal.SIGKILL)
                    print(f"🛑 Force killed Factorio client (PID: {pid})")

            self._clear_pid()
        except ProcessLookupError:
            print("⚠️  Process already exited")
            self._clear_pid()
        except PermissionError:
            print(f"❌ Permission denied killing process {pid}")
            sys.exit(1)

    def restart(
        self,
        scenario: Optional[str] = None,
        save_file: Optional[Path] = None,
        map_gen_settings: Optional[Path] = None,
        new_map: bool = False,
        map_name: Optional[str] = None,
        force_setup: bool = False,
        project_scenarios_dir: Optional[Path] = None,
    ) -> None:
        """Restart Factorio client.

        If no arguments provided, uses last known configuration.
        Otherwise, restarts with new configuration.

        Args:
            scenario: Scenario name to load (overrides saved state)
            save_file: Save file to load (overrides saved state)
            map_gen_settings: Map generation settings (overrides saved state)
            new_map: Create new map (overrides saved state)
            map_name: Name for new map
            force_setup: Force re-setup of client mods/scenarios
            project_scenarios_dir: Path to project scenarios directory
        """
        # Load saved state if no overrides provided
        state = self._load_state()

        if scenario is None:
            scenario = state.get("scenario")
        if save_file is None and not new_map:
            # If we have a saved save_file, use it (don't create new map)
            save_file_str = state.get("save_file")
            if save_file_str:
                save_file = Path(save_file_str)
        if map_gen_settings is None:
            map_gen_settings_str = state.get("map_gen_settings")
            if map_gen_settings_str:
                map_gen_settings = Path(map_gen_settings_str)
        # Only use saved new_map if explicitly not overridden
        if not new_map:
            new_map = state.get("new_map", False)

        # Stop if running
        if self.is_running():
            self.stop()
            import time

            time.sleep(1)  # Brief pause between stop/start

        # Start with configuration
        self.start(
            scenario=scenario,
            save_file=save_file,
            map_gen_settings=map_gen_settings,
            new_map=new_map,
            map_name=map_name,
            force_setup=force_setup,
            project_scenarios_dir=project_scenarios_dir,
        )

    def is_running(self) -> bool:
        """Check if client is currently running."""
        pid = self._load_pid()
        if pid and self._is_process_running(pid):
            return True

        # Fallback for macOS/Steam restart
        if sys.platform == "darwin":
            pid = self._find_factorio_pid_by_name()
            if pid:
                self._save_pid(pid)  # Update PID file
                return True
        return False

    def status(self) -> dict:
        """Get client status.

        Returns:
            Dictionary with 'running', 'pid', and 'state' keys
        """
        pid = self._load_pid()
        running = self.is_running() if pid else False
        state = self._load_state() if self.state_file.exists() else {}

        return {
            "running": running,
            "pid": pid if running else None,
            "state": state,
        }

    def _load_pid(self) -> Optional[int]:
        """Load PID from file."""
        if not self.pid_file.exists():
            return None
        try:
            return int(self.pid_file.read_text().strip())
        except (ValueError, IOError):
            return None

    def _save_pid(self, pid: int) -> None:
        """Save PID to file."""
        self.pid_file.write_text(str(pid))

    def _clear_pid(self) -> None:
        """Clear PID file."""
        if self.pid_file.exists():
            self.pid_file.unlink()

    def _find_factorio_pid_by_name(self) -> Optional[int]:
        """Try to find Factorio PID by process name (macOS only)."""
        try:
            # Look for process named 'factorio'
            result = subprocess.run(
                ["pgrep", "-x", "factorio"], capture_output=True, text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                # Take the first one if multiple
                return int(result.stdout.splitlines()[0].strip())
        except Exception:
            pass
        return None

    def _is_process_running(self, pid: int) -> bool:
        """Check if process with given PID is running."""
        try:
            os.kill(pid, 0)  # Signal 0 doesn't kill, just checks existence
            return True
        except (ProcessLookupError, OverflowError):
            return False
        except PermissionError:
            return True

    def _save_state(
        self,
        scenario: Optional[str] = None,
        save_file: Optional[str] = None,
        map_gen_settings: Optional[str] = None,
        new_map: bool = False,
    ) -> None:
        """Save client state for restart."""
        state = {
            "scenario": scenario,
            "save_file": save_file,
            "map_gen_settings": map_gen_settings,
            "new_map": new_map,
        }
        # Remove None values
        state = {k: v for k, v in state.items() if v is not None}
        self.state_file.write_text(json.dumps(state, indent=2))

    def _load_state(self) -> dict:
        """Load client state."""
        if not self.state_file.exists():
            return {}
        try:
            return json.loads(self.state_file.read_text())
        except (json.JSONDecodeError, IOError):
            return {}
