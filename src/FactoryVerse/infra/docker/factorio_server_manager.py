#!/usr/bin/env python3
"""Factorio server management for FactoryVerse.

Handles Docker container lifecycle, mod preparation, and server configuration.
Uses the unified FactoryVerseConfig from config.py.
"""

import json
import shutil
import subprocess
import hashlib
from pathlib import Path
from typing import Dict, List, Optional
from factorio_rcon import RCONClient

from FactoryVerse.config import FactoryVerseConfig, get_config


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
    """Manages Factorio server configuration and lifecycle.

    Uses the unified FactoryVerseConfig for all configuration values.
    """

    def __init__(
        self,
        work_dir: Optional[Path] = None,
        config: Optional[FactoryVerseConfig] = None,
    ):
        """Initialize server manager.

        Args:
            work_dir: Project root directory (optional, auto-detected from config)
            config: Configuration (auto-loaded if not provided)
        """
        self.config = config or get_config()

        # Work directory
        self.work_dir = work_dir or self.config.project_root

        # Mod directories
        self.verse_mod_dir = self.work_dir / "src" / "factorio_verse"
        self.embodied_agent_mod_dir = self.config.embodied_agent_mod_dir
        self.snapshot_mod_dir = self.config.snapshot_mod_dir
        self.placement_hints_mod_dir = self.config.placement_hints_mod_dir
        self.scenarios_dir = self.config.scenarios_dir
        self.config_dir = self.config.server_config_dir
        self.mod_path = self.config.mods_dir

        # Instance state
        self.num_instances = 1
        self.scenario = self.config.default_scenario

    # Scenario Management
    # =========================================================================

    def list_scenarios(self) -> List[str]:
        """List available scenarios from both repo and local directories.

        Returns:
            List of scenario names that can be loaded (includes local scenarios)
        """
        return self.config.list_scenarios(include_local=True)

    def validate_scenario(self, scenario: str) -> bool:
        """Check if a scenario exists and is valid.

        Args:
            scenario: Scenario name to validate

        Returns:
            True if scenario exists and has control.lua
        """
        return self.config.validate_scenario(scenario)

    def consolidate_scenarios(self) -> int:
        """Consolidate local scenarios to repo scenarios directory.

        Copies scenarios from local Factorio directory to repo's scenarios
        directory for server access. Repo scenarios take precedence (won't
        be overwritten by local copies).

        Returns:
            Number of scenarios copied
        """
        local_dir = self.config.local_scenarios_dir
        repo_dir = self.config.scenarios_dir

        if not local_dir.exists():
            return 0

        copied = 0
        for scenario_dir in local_dir.iterdir():
            if not scenario_dir.is_dir():
                continue
            if not (scenario_dir / "control.lua").exists():
                continue

            target_dir = repo_dir / scenario_dir.name

            # Skip if already exists in repo (repo takes precedence)
            if target_dir.exists():
                continue

            # Copy scenario
            print(f"📦 Copying local scenario '{scenario_dir.name}' to repo...")
            shutil.copytree(scenario_dir, target_dir)
            copied += 1

        if copied > 0:
            print(f"✓ Copied {copied} local scenario(s) to repo")

        return copied

    # =========================================================================
    # Directory Management
    # =========================================================================

    def get_server_script_output_dir(self, instance_id: int = 0) -> Path:
        """Get script-output directory for a server instance."""
        return self.config.get_server_output_dir(instance_id)

    def clear_server_snapshot_dir(self, instance_id: int = 0) -> None:
        """Clear the snapshot directory for a server instance."""
        script_output_dir = self.get_server_script_output_dir(instance_id)
        snapshot_dir = script_output_dir / "factoryverse" / "snapshots"

        if snapshot_dir.exists():
            print(
                f"🧹 Clearing server {instance_id} snapshot directory: {snapshot_dir}"
            )
            shutil.rmtree(snapshot_dir)
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            print(f"✓ Server {instance_id} snapshot directory cleared")
        else:
            snapshot_dir.mkdir(parents=True, exist_ok=True)

    def clear_all_server_snapshot_dirs(self, num_instances: int) -> None:
        """Clear snapshot directories for all server instances."""
        for i in range(num_instances):
            self.clear_server_snapshot_dir(i)

    # =========================================================================
    # Mod Preparation
    # =========================================================================

    def prepare_mods(self, scenario: str) -> None:
        """Prepare FactoryVerse mods for server.

        FactoryVerse mods (fv_embodied_agent + fv_snapshot) are ALWAYS loaded.
        This is the only supported mode.

        Args:
            scenario: Scenario name to use
        """
        # Check mod directories exist
        if not self.embodied_agent_mod_dir.exists():
            raise RuntimeError(
                f"FV Embodied Agent mod not found at {self.embodied_agent_mod_dir}"
            )
        if not self.snapshot_mod_dir.exists():
            raise RuntimeError(f"FV Snapshot mod not found at {self.snapshot_mod_dir}")

        print("📦 Preparing FactoryVerse mods for server...")

        # Remove existing FactoryVerse mod copies
        print("   Removing existing mod copies...")
        for old_mod_pattern in [
            "fv_embodied_agent*",
            "fv_snapshot*",
            "fv_placement_hints*",
            "factorio_verse*",
        ]:
            for old_mod in self.mod_path.glob(old_mod_pattern):
                if old_mod.is_dir():
                    print(f"   Removing {old_mod.name}...")
                    shutil.rmtree(old_mod)

        # Prepare fv_embodied_agent mod
        self._copy_mod(self.embodied_agent_mod_dir, "fv_embodied_agent", force=False)

        # Prepare fv_snapshot mod
        self._copy_mod(self.snapshot_mod_dir, "fv_snapshot", force=False)

        # Prepare fv_placement_hints mod (if it exists)
        if self.placement_hints_mod_dir.exists():
            self._copy_mod(self.placement_hints_mod_dir, "fv_placement_hints", force=False)
        else:
            print("⚠️  fv_placement_hints mod not found, skipping...")

        # Ensure DLC mods are disabled
        for dlc_mod in ["space-age", "quality", "elevated-rails"]:
            _update_mod_list(self.mod_path, dlc_mod, False)
        print("✓ DLC mods disabled in mod-list")

    def _calculate_directory_hash(self, directory: Path) -> str:
        """Calculate SHA256 hash of all files in a directory."""
        hasher = hashlib.sha256()
        all_files = sorted(directory.rglob("*"))
        
        for file_path in all_files:
            if file_path.is_file():
                rel_path = file_path.relative_to(directory)
                hasher.update(str(rel_path).encode())
                try:
                    with open(file_path, "rb") as f:
                        hasher.update(f.read())
                except (IOError, OSError):
                    pass
        
        return hasher.hexdigest()

    def _get_mod_hash_file(self, mod_name: str) -> Path:
        """Get path to hash file for a mod."""
        return self.mod_path / f".{mod_name}.hash"

    def _get_mod_hash(self, mod_name: str) -> Optional[str]:
        """Get stored hash for a mod."""
        hash_file = self._get_mod_hash_file(mod_name)
        if hash_file.exists():
            return hash_file.read_text().strip()
        return None

    def _save_mod_hash(self, mod_name: str, hash_value: str) -> None:
        """Save hash for a mod."""
        hash_file = self._get_mod_hash_file(mod_name)
        hash_file.write_text(hash_value)

    def _mod_needs_update(self, source_dir: Path, mod_name: str) -> bool:
        """Check if mod needs to be updated based on hash comparison."""
        if not source_dir.exists():
            return True
        
        current_hash = self._calculate_directory_hash(source_dir)
        stored_hash = self._get_mod_hash(mod_name)
        
        if stored_hash != current_hash:
            self._save_mod_hash(mod_name, current_hash)
            return True
        
        return False

    def _copy_mod(self, source_dir: Path, default_name: str, force: bool = False) -> None:
        """Copy a mod to the Factorio mods directory."""
        info_json_path = source_dir / "info.json"
        if info_json_path.exists():
            info = json.loads(info_json_path.read_text())
            mod_name = info.get("name", default_name)
            mod_version = info.get("version", "1.0.0")
        else:
            mod_name = default_name
            mod_version = "1.0.0"

        print(f"📦 Checking {mod_name} mod...")
        target_dir = self.mod_path / f"{mod_name}_{mod_version}"

        # Check if mod needs update based on hash
        if force or self._mod_needs_update(source_dir, mod_name):
            if target_dir.exists():
                shutil.rmtree(target_dir)
            print(f"   Updating {mod_name} mod (hash changed or --force)...")
            shutil.copytree(source_dir, target_dir)
            print(f"✓ {mod_name} mod updated as {target_dir.name}")
        else:
            # Ensure mod directory exists even if hash matches
            if not target_dir.exists():
                print(f"   Mod directory missing, copying {mod_name}...")
                shutil.copytree(source_dir, target_dir)
                print(f"✓ {mod_name} mod copied as {target_dir.name}")
            else:
                print(f"✓ {mod_name} mod up to date (hash unchanged)")

        _update_mod_list(self.mod_path, mod_name, True)
        print(f"✓ {mod_name} mod copied as {target_dir.name}")
        print(f"✓ {mod_name}: enabled in mod-list")

    # =========================================================================
    # Docker Compose Service Generation
    # =========================================================================

    def get_services(
        self,
        num_instances: int,
        scenario: str,
        max_agents: Optional[int] = None,
    ) -> Dict[str, dict]:
        """Generate Factorio server services for Docker Compose.

        Args:
            num_instances: Number of server instances
            scenario: Scenario to load
            max_agents: Maximum agents per server (determines UDP port range)

        Returns:
            Dict of service definitions for docker-compose
        """
        self.num_instances = num_instances
        self.scenario = scenario

        # Store effective max_agents (CLI override or config default)
        self.effective_max_agents = (
            max_agents if max_agents is not None else self.config.max_agents
        )

        services = {}

        for i in range(num_instances):
            # Add Factorio server
            services[f"factorio_{i}"] = self._build_service_config(i, scenario)
            # Add UDP forwarder sidecar (Alpine + socat)
            services[f"udp_forwarder_{i}"] = self._build_udp_forwarder_config(i)

        return services

    def _build_service_config(self, instance_id: int, scenario: str) -> dict:
        """Build Docker Compose service config for a single server instance."""
        cfg = self.config

        # Calculate ports for this instance
        game_port = cfg.get_game_port(instance_id)
        rcon_port = cfg.get_rcon_port(f"server_{instance_id}")
        output_dir = self.get_server_script_output_dir(instance_id)

        # Build Factorio command
        emulator = cfg.factorio_emulator
        factorio_bin = f"{emulator} /opt/factorio/bin/x64/factorio".strip()

        command_parts = [
            factorio_bin,
            f"--start-server-load-scenario {scenario}",
            f"--port {cfg.internal_game_port}",
            f"--rcon-port {cfg.internal_rcon_port}",
            f'--rcon-password "{cfg.rcon_password}"',
            "--server-settings /factorio/config/server-settings.json",
            "--map-gen-settings /factorio/config/map-gen-settings.json",
            "--map-settings /factorio/config/map-settings.json",
            "--server-whitelist /factorio/config/server-whitelist.json",
            "--use-server-whitelist",
            "--server-adminlist /factorio/config/server-adminlist.json",
            "--mod-directory /opt/factorio/mods",
            f"--map-gen-seed {cfg.map_gen_seed}",
            # Enable UDP for Lua - required for agent/snapshot notifications
            f"--enable-lua-udp {cfg.enable_udp_port}",
        ]

        command = " ".join(command_parts)

        # Build port mappings - only game and RCON
        # Agent/snapshot UDP ports are handled by the sidecar forwarder
        ports = [
            f"{game_port}:{cfg.internal_game_port}/udp",  # Game UDP
            f"{rcon_port}:{cfg.internal_rcon_port}/tcp",  # RCON TCP
        ]

        # Optionally expose Factorio's incoming UDP listener (for external control)
        if cfg.expose_incoming_udp:
            ports.append(f"{cfg.enable_udp_port}:{cfg.enable_udp_port}/udp")

        return {
            "image": cfg.docker_image,
            "platform": cfg.docker_platform,
            "entrypoint": [],
            "command": command,
            "environment": ["DLC_SPACE_AGE=false"],
            "deploy": {"resources": {"limits": {"cpus": "1", "memory": "1024m"}}},
            "ports": ports,
            "volumes": [
                f"{self.scenarios_dir.resolve()}:/opt/factorio/scenarios",
                f"{self.mod_path.resolve()}:/opt/factorio/mods",
                f"{self.config_dir.resolve()}:/factorio/config",
                f"{output_dir.resolve()}:/opt/factorio/script-output",
            ],
            # extra_hosts needed here since sidecar shares network namespace
            "extra_hosts": ["host.docker.internal:host-gateway"],
            "restart": "unless-stopped",
        }

    def _build_udp_forwarder_config(self, instance_id: int) -> dict:
        """Build UDP forwarder sidecar service config.

        This Alpine-based container runs socat to forward UDP from Factorio's
        localhost (inside the Factorio container's network namespace) to
        host.docker.internal where Python on the host listens.

        Factorio's helpers.send_udp() sends to localhost:port, which this
        sidecar intercepts and forwards to the host.
        """
        cfg = self.config
        snapshot_port = cfg.get_snapshot_port(f"server_{instance_id}")

        # Build socat commands for all agent ports + snapshot port
        socat_commands = []
        for agent_idx in range(self.effective_max_agents):
            agent_port = cfg.get_agent_port(agent_idx, server_index=instance_id)
            # socat listens on localhost:port and forwards to host.docker.internal:port
            socat_commands.append(
                f"socat UDP-LISTEN:{agent_port},fork,reuseaddr UDP:host.docker.internal:{agent_port}"
            )
        # Also forward snapshot port
        socat_commands.append(
            f"socat UDP-LISTEN:{snapshot_port},fork,reuseaddr UDP:host.docker.internal:{snapshot_port}"
        )

        # Run all socat instances in parallel, keep container alive
        # Using & to background all but the last one (which keeps container running)
        if len(socat_commands) > 1:
            command = " & ".join(socat_commands[:-1]) + " & " + socat_commands[-1]
        else:
            command = socat_commands[0]

        return {
            "image": "alpine/socat",
            "platform": cfg.docker_platform,
            # Share network namespace with Factorio container
            # (inherits extra_hosts from factorio service)
            "network_mode": f"service:factorio_{instance_id}",
            # Override entrypoint since alpine/socat has "socat" as entrypoint
            # Use list format to ensure command is passed as single argument to -c
            "entrypoint": ["/bin/sh", "-c"],
            "command": [command],
            "depends_on": [f"factorio_{instance_id}"],
            "restart": "unless-stopped",
        }

    # =========================================================================
    # Hot Reload
    # =========================================================================

    def sync_hotreload_to_server(self, compose_mgr, server_id: int = 0) -> None:
        """Sync Lua files to server temp directory and trigger reload via RCON."""
        try:
            container_name = f"factoryverse-factorio_{server_id}-1"
            print(f"📋 Syncing files to container temp dir (factorio_{server_id})...")

            # Ensure temp directory exists in container
            subprocess.run(
                [
                    "docker",
                    "exec",
                    container_name,
                    "mkdir",
                    "-p",
                    "/opt/factorio/temp/currently-playing",
                ],
                capture_output=True,
                check=False,
            )

            local_mod = self.verse_mod_dir

            # Use rsync to sync files
            result = subprocess.run(
                [
                    "rsync",
                    "-r",
                    "--delete",
                    "-e",
                    f"docker exec {container_name}",
                    f"{local_mod}/",
                    ":/opt/factorio/temp/currently-playing/",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode == 0:
                files_copied = len(list(local_mod.rglob("*.lua")))
                print(f"✓ Files synced to temp directory ({files_copied} file(s))")
            else:
                # Fallback: use docker cp
                print("⚠️  rsync failed, falling back to docker cp...")
                for lua_file in local_mod.rglob("*.lua"):
                    rel_path = lua_file.relative_to(local_mod)
                    container_path = f"/opt/factorio/temp/currently-playing/{rel_path}"

                    container_dir = str(container_path).rsplit("/", 1)[0]
                    subprocess.run(
                        [
                            "docker",
                            "exec",
                            container_name,
                            "mkdir",
                            "-p",
                            container_dir,
                        ],
                        capture_output=True,
                        check=False,
                    )

                    subprocess.run(
                        [
                            "docker",
                            "cp",
                            str(lua_file),
                            f"{container_name}:{container_path}",
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                    )

            # Trigger reload via RCON
            print("🔌 Connecting via RCON...")
            rcon_port = self.config.get_rcon_port(f"server_{server_id}")
            rcon = RCONClient("localhost", rcon_port, self.config.rcon_password)

            try:
                rcon.connect()
                print("✓ RCON connected")

                print("🔄 Triggering game.reload_script()...")
                response = rcon.send_command(
                    "/c game.reload_script();game.print('Scripts reloaded');rcon.print('Scripts reloaded')"
                )
                print(f"✓ Reload triggered: {response}")
            finally:
                rcon.close()

        except Exception as e:
            print(f"❌ Hotreload failed: {e}")
