#!/usr/bin/env python3
"""Factorio server management for FactoryVerse."""

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional
from factorio_rcon import RCONClient

# ============================================================================
# CONFIGURATION
# ============================================================================

START_RCON_PORT = 27000
START_GAME_PORT = 34197
RCON_PASSWORD = "factorio"
FACTORIO_IMAGE = "factoriotools/factorio:2.0.69"
MAP_GEN_SEED = 44340
INTERNAL_RCON_PORT = 27015
INTERNAL_GAME_PORT = 34197


def _detect_mod_path() -> Path:
    """Detect local Factorio mod directory."""
    os_name = platform.system()
    if os_name == "Darwin":
        return Path.home() / "Library" / "Application Support" / "factorio" / "mods"
    elif os_name == "Windows":
        appdata = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
        return Path(appdata) / "Factorio" / "mods"
    else:  # Linux
        return Path.home() / ".factorio" / "mods"


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


class FactorioServerManager:
    """Manages Factorio server configuration and lifecycle."""
    
    def __init__(self, work_dir: Path):
        self.work_dir = work_dir.resolve()
        self.verse_mod_dir = self.work_dir / "src" / "factorio_verse"
        self.scenarios_dir = self.work_dir / "src" / "factorio" / "scenarios"
        self.config_dir = self.work_dir / "src" / "factorio" / "config"
        self.mod_path = _detect_mod_path()
        self.arch = platform.machine()
        self.num_instances = 1
        self.scenario = "test_scenario"
    
    def _docker_platform(self) -> str:
        """Get Docker platform based on architecture."""
        return "linux/arm64" if self.arch in ["arm64", "aarch64"] else "linux/amd64"
    
    def _factorio_emulator(self) -> str:
        """Get emulator prefix if needed."""
        return "/bin/box64" if self.arch in ["arm64", "aarch64"] else ""
    
    def get_server_script_output_dir(self, instance_id: int = 0) -> Path:
        """
        Get script-output directory for a server instance.
        
        Args:
            instance_id: Server instance ID (default: 0)
        
        Returns:
            Path to server script-output directory
        """
        return self.work_dir / ".fv-output" / f"output_{instance_id}"
    
    def prepare_mods(self, scenario: str) -> None:
        """Prepare factorio_verse mod for server."""
        if not self.verse_mod_dir.exists():
            raise RuntimeError(f"FactoryVerse mod not found at {self.verse_mod_dir}")
        
        print(f"📦 Preparing FactoryVerse for server...")
        
        if scenario == "factorio_verse":
            # Copy factorio_verse mod directory to server mods
            server_mod_dir = self.mod_path / "factorio_verse"
            
            # Remove old mod if exists
            if server_mod_dir.exists():
                shutil.rmtree(server_mod_dir)
            
            # Copy to mod directory
            shutil.copytree(self.verse_mod_dir, server_mod_dir)
            
            # Disable factorio_verse in mod-list (it will be used as scenario)
            _update_mod_list(self.mod_path, "factorio_verse", False)
            print("✓ factorio_verse copied (disabled as mod)")
        else:
            # Copy factorio_verse mod directory to server mods
            server_mod_dir = self.mod_path / "factorio_verse"
            
            # Remove old mod if exists
            if server_mod_dir.exists():
                shutil.rmtree(server_mod_dir)
            
            # Copy to mod directory
            shutil.copytree(self.verse_mod_dir, server_mod_dir)
            
            # Enable factorio_verse in mod-list
            _update_mod_list(self.mod_path, "factorio_verse", True)
            print("✓ factorio_verse mod copied and enabled")
        
        # Ensure DLC mods are disabled
        dlc_mods = ["space-age", "quality", "elevated-rails"]
        for dlc_mod in dlc_mods:
            _update_mod_list(self.mod_path, dlc_mod, False)
        
        print("✓ DLC mods disabled in mod-list")
    
    def get_services(self, num_instances: int, scenario: str) -> Dict[str, dict]:
        """Generate Factorio server services."""
        self.num_instances = num_instances
        self.scenario = scenario
        services = {}
        
        # Add Factorio servers
        for i in range(num_instances):
            udp_port = START_GAME_PORT + i
            rcon_port = START_RCON_PORT + i
            output_dir = self.work_dir / ".fv-output" / f"output_{i}"
            output_dir.mkdir(parents=True, exist_ok=True)
            
            emulator = self._factorio_emulator()
            factorio_bin = f"{emulator} /opt/factorio/bin/x64/factorio".strip()
            
            services[f"factorio_{i}"] = {
                "image": FACTORIO_IMAGE,
                "platform": self._docker_platform(),
                "entrypoint": [],
                "command": f"{factorio_bin} --start-server-load-scenario {scenario} "
                          f"--port {INTERNAL_GAME_PORT} --rcon-port {INTERNAL_RCON_PORT} "
                          f'--rcon-password "{RCON_PASSWORD}" '
                          f"--server-settings /factorio/config/server-settings.json "
                          f"--map-gen-settings /factorio/config/map-gen-settings.json "
                          f"--map-settings /factorio/config/map-settings.json "
                          f"--server-whitelist /factorio/config/server-whitelist.json "
                          f"--use-server-whitelist "
                          f"--server-adminlist /factorio/config/server-adminlist.json "
                          f"--mod-directory /opt/factorio/mods "
                          f"--map-gen-seed {MAP_GEN_SEED}",
                "environment": ["DLC_SPACE_AGE=false"],
                "deploy": {"resources": {"limits": {"cpus": "1", "memory": "1024m"}}},
                "ports": [
                    f"{udp_port}:{INTERNAL_GAME_PORT}/udp",
                    f"{rcon_port}:{INTERNAL_RCON_PORT}/tcp",
                ],
                "volumes": [
                    {"source": str(self.scenarios_dir.resolve()), "target": "/opt/factorio/scenarios"},
                    {"source": str(self.mod_path.resolve()), "target": "/opt/factorio/mods"},
                    {"source": str(self.config_dir.resolve()), "target": "/factorio/config"},
                    {"source": str(output_dir.resolve()), "target": "/opt/factorio/script-output"},
                ],
                "restart": "unless-stopped",
            }
        
        return services
    
    def sync_hotreload_to_server(self, compose_mgr, server_id: int = 0) -> None:
        """Sync Lua files to server temp directory and trigger reload via RCON."""
        try:
            container_name = f"factoryverse-factorio_{server_id}-1"
            
            print(f"📋 Syncing factorio_verse files to container temp dir (factorio_{server_id})...")
            
            # Ensure temp directory exists in container
            subprocess.run(
                ["docker", "exec", container_name, "mkdir", "-p", "/opt/factorio/temp/currently-playing"],
                capture_output=True,
                check=False
            )
            
            local_mod = self.verse_mod_dir
            
            # Use rsync via docker to sync files efficiently to container temp directory
            result = subprocess.run(
                ["rsync", "-r", "--delete", "-e", f"docker exec {container_name}",
                 f"{local_mod}/", ":/opt/factorio/temp/currently-playing/"],
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                files_copied = len(list(local_mod.rglob("*.lua")))
                print(f"✓ Files synced to temp directory ({files_copied} file(s))")
            else:
                # Fallback: use docker cp for each file
                print("⚠️  rsync failed, falling back to docker cp...")
                for lua_file in local_mod.rglob("*.lua"):
                    rel_path = lua_file.relative_to(local_mod)
                    container_path = f"/opt/factorio/temp/currently-playing/{rel_path}"
                    
                    # Create subdirectories in container if needed
                    container_dir = str(container_path).rsplit('/', 1)[0]
                    subprocess.run(
                        ["docker", "exec", container_name, "mkdir", "-p", container_dir],
                        capture_output=True,
                        check=False
                    )
                    
                    subprocess.run(
                        ["docker", "cp", str(lua_file), f"{container_name}:{container_path}"],
                        capture_output=True,
                        text=True,
                        check=False
                    )
            
            # Connect via RCON and trigger reload
            print("🔌 Connecting via RCON...")
            rcon_port = START_RCON_PORT + server_id
            rcon = RCONClient("localhost", rcon_port, RCON_PASSWORD)
            
            try:
                rcon.connect()
                print("✓ RCON connected")
                
                # Reload scripts (game.reload_script reads from temp/currently-playing)
                print("🔄 Triggering game.reload_script()...")
                response = rcon.send_command("/c game.reload_script();game.print('Scripts reloaded');rcon.print('Scripts reloaded')")
                print(f"✓ Reload triggered: {response}")
                
            finally:
                rcon.close()
        
        except Exception as e:
            print(f"❌ Hotreload failed: {e}")
