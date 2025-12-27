#!/usr/bin/env python3
"""Factorio server management for FactoryVerse.

Handles Docker container lifecycle, mod preparation, and server configuration.
Uses pydantic-settings based configuration from config.py.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
from factorio_rcon import RCONClient

from .config import get_server_config, get_path_config, ServerConfig, PathConfig


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

    Uses ServerConfig and PathConfig for all configuration values.
    """

    def __init__(
        self,
        work_dir: Optional[Path] = None,
        server_config: Optional[ServerConfig] = None,
        path_config: Optional[PathConfig] = None,
    ):
        """Initialize server manager.

        Args:
            work_dir: Project root directory (deprecated, use path_config)
            server_config: Server configuration (auto-loaded if not provided)
            path_config: Path configuration (auto-loaded if not provided)
        """
        self.config = server_config or get_server_config()
        self.paths = path_config or get_path_config()

        # For backward compatibility
        self.work_dir = work_dir or self.paths.project_root

        # Legacy attributes (kept for backward compatibility)
        self.verse_mod_dir = self.work_dir / "src" / "factorio_verse"
        self.embodied_agent_mod_dir = self.paths.embodied_agent_mod_dir
        self.snapshot_mod_dir = self.paths.snapshot_mod_dir
        self.scenarios_dir = self.paths.scenarios_dir
        self.config_dir = self.paths.server_config_dir
        self.mod_path = self.paths.mods_dir

        # Instance state
        self.num_instances = 1
        self.scenario = self.config.default_scenario

    # =========================================================================
    # Scenario Management
    # =========================================================================

    def list_scenarios(self) -> List[str]:
        """List available scenarios.

        Returns:
            List of scenario names that can be loaded
        """
        return self.paths.list_scenarios()

    def validate_scenario(self, scenario: str) -> bool:
        """Check if a scenario exists and is valid.

        Args:
            scenario: Scenario name to validate

        Returns:
            True if scenario exists and has control.lua
        """
        return self.paths.validate_scenario(scenario)

    # =========================================================================
    # Directory Management
    # =========================================================================

    def get_server_script_output_dir(self, instance_id: int = 0) -> Path:
        """Get script-output directory for a server instance."""
        return self.paths.get_server_output_dir(instance_id)

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

    def prepare_mods(self, scenario: str, as_mod: bool = False) -> None:
        """Prepare FactoryVerse mods for server.

        Args:
            scenario: Scenario name to use
            as_mod: If True, load FactoryVerse mods (fv_embodied_agent and fv_snapshot)
        """
        if as_mod:
            if scenario == "factorio_verse":
                raise RuntimeError(
                    "❌ Error: Cannot use scenario route for FactoryVerse. "
                    "FactoryVerse has been split into two mods (fv_embodied_agent and fv_snapshot). "
                    "Please use --as-mod flag with a different scenario."
                )

            # Check mod directories exist
            if not self.embodied_agent_mod_dir.exists():
                raise RuntimeError(
                    f"FV Embodied Agent mod not found at {self.embodied_agent_mod_dir}"
                )
            if not self.snapshot_mod_dir.exists():
                raise RuntimeError(
                    f"FV Snapshot mod not found at {self.snapshot_mod_dir}"
                )

            print("📦 Preparing FactoryVerse mods for server...")

            # Remove existing FactoryVerse mod copies
            print("📦 Removing existing FactoryVerse mod copies...")
            for old_mod_pattern in [
                "fv_embodied_agent*",
                "fv_snapshot*",
                "factorio_verse*",
            ]:
                for old_mod in self.mod_path.glob(old_mod_pattern):
                    if old_mod.is_dir():
                        print(f"   Removing {old_mod.name}...")
                        shutil.rmtree(old_mod)

            # Prepare fv_embodied_agent mod
            self._copy_mod(self.embodied_agent_mod_dir, "fv_embodied_agent")

            # Prepare fv_snapshot mod
            self._copy_mod(self.snapshot_mod_dir, "fv_snapshot")

        elif scenario == "factorio_verse":
            raise RuntimeError(
                "❌ Error: Scenario route for FactoryVerse is not supported. "
                "Please use --as-mod flag with a different scenario."
            )
        else:
            print(f"ℹ️  Using scenario mode (no mods needed for scenario: {scenario})")

        # Ensure DLC mods are disabled
        for dlc_mod in ["space-age", "quality", "elevated-rails"]:
            _update_mod_list(self.mod_path, dlc_mod, False)
        print("✓ DLC mods disabled in mod-list")

    def _copy_mod(self, source_dir: Path, default_name: str) -> None:
        """Copy a mod to the Factorio mods directory."""
        info_json_path = source_dir / "info.json"
        if info_json_path.exists():
            info = json.loads(info_json_path.read_text())
            mod_name = info.get("name", default_name)
            mod_version = info.get("version", "1.0.0")
        else:
            mod_name = default_name
            mod_version = "1.0.0"

        print(f"📦 Preparing {mod_name} mod...")
        target_dir = self.mod_path / f"{mod_name}_{mod_version}"

        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(source_dir, target_dir)

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
            services[f"factorio_{i}"] = self._build_service_config(i, scenario)

        return services

    def _build_service_config(self, instance_id: int, scenario: str) -> dict:
        """Build Docker Compose service config for a single server instance."""
        cfg = self.config

        # Calculate ports for this instance
        game_port = cfg.get_game_port(instance_id)
        rcon_port = cfg.get_rcon_port(instance_id)
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

        # Build port mappings
        ports = [
            f"{game_port}:{cfg.internal_game_port}/udp",  # Game UDP
            f"{rcon_port}:{cfg.internal_rcon_port}/tcp",  # RCON TCP
        ]

        # Add agent ports (Factorio sends OUT to these, Python listens)
        # These are exposed so Python on host can receive UDP from container
        for agent_idx in range(self.effective_max_agents):
            agent_port = cfg.get_agent_port(agent_idx)
            # Note: We expose on host, but Factorio sends to localhost:port inside container
            # This works because UDP from container can reach host's bound ports
            ports.append(f"{agent_port}:{agent_port}/udp")

        # Add snapshot port
        ports.append(f"{cfg.snapshot_port}:{cfg.snapshot_port}/udp")

        # Optionally expose Factorio's incoming UDP listener
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
            "restart": "unless-stopped",
            # Network mode for UDP to work properly
            # Container sends to localhost:port, needs host network or port forwarding
        }

    # =========================================================================
    # Hot Reload (Legacy)
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
            rcon_port = self.config.get_rcon_port(server_id)
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
