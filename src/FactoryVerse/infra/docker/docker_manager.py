#!/usr/bin/env python3

import os
import platform
import subprocess
import sys
import socket
from pathlib import Path
from typing import List, Optional
import shutil
import yaml
import zipfile
import importlib.resources as ir
from platformdirs import user_state_dir

START_RCON_PORT = 27000
START_GAME_PORT = 34197
RCON_PASSWORD = "factorio"
POSTGRES_PORT = 5432
POSTGRES_USER = "factoryverse"
POSTGRES_PASSWORD = "factoryverse"
POSTGRES_DB = "factoryverse"


def resolve_state_dir() -> Path:
    """Resolve platform-specific state directory with env override.

    Env override: FACTORYVERSE_STATE_DIR
    Default: platformdirs.user_state_dir("factoryverse")
    """
    override = os.environ.get("FACTORYVERSE_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path(user_state_dir("factoryverse"))


def resolve_work_dir() -> Path:
    """Resolve user-visible working directory root with env override.

    Env override: FACTORYVERSE_WORKDIR
    Default: current working directory
    """
    override = os.environ.get("FACTORYVERSE_WORKDIR")
    base = Path(override).expanduser().resolve() if override else Path.cwd()
    return base


def setup_compose_cmd():
    candidates = [
        ["docker", "compose", "version"],
        ["docker-compose", "--version"],
    ]
    for cmd in candidates:
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return " ".join(cmd[:2]) if cmd[0] == "docker" else "docker-compose"
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    print("Error: Docker Compose not found. Install Docker Desktop or docker-compose.")
    sys.exit(1)


class ComposeGenerator:
    """Compose YAML generator with centralized path handling."""

    rcon_password = RCON_PASSWORD
    factorio_image = "factoriotools/factorio:2.0.60"
    map_gen_seed = 44340
    internal_rcon_port = 27015
    internal_game_port = 34197

    def __init__(
        self,
        attach_mod=False,
        save_file=None,
        scenario="factorio_verse",
        state_dir: Path | None = None,
        work_dir: Path | None = None,
        pkg_scenarios_dir: Path | None = None,
        pkg_config_dir: Path | None = None,
    ):
        self.arch = platform.machine()
        self.os_name = platform.system()
        self.attach_mod = attach_mod
        self.save_file = save_file
        self.scenario = scenario
        self.state_dir = (state_dir or resolve_state_dir()).resolve()
        self.work_dir = (work_dir or resolve_work_dir()).resolve()
        # Package resource directories (read-only)
        self.pkg_scenarios_dir = pkg_scenarios_dir
        self.pkg_config_dir = pkg_config_dir

    def _docker_platform(self):
        if self.arch in ["arm64", "aarch64"]:
            return "linux/arm64"
        else:
            return "linux/amd64"

    def _factorio_emulator(self):
        if self.arch in ["arm64", "aarch64"]:
            return "/bin/box64"
        else:
            return ""

    def _factorio_command(self):
        launch_command = f"--start-server-load-scenario {self.scenario}"
        if self.save_file:
            # Use only the basename inside the command
            launch_command = f"--start-server {Path(self.save_file).name}"
        args = [
            f"--port {self.internal_game_port}",
            f"--rcon-port {self.internal_rcon_port}",
            f"--rcon-password {self.rcon_password}",
            "--server-settings /opt/factorio/config/server-settings.json",
            "--map-gen-settings /opt/factorio/config/map-gen-settings.json",
            "--map-settings /opt/factorio/config/map-settings.json",
            "--server-adminlist /opt/factorio/config/server-adminlist.json",
            "--server-banlist /opt/factorio/config/server-banlist.json",
            "--server-whitelist /opt/factorio/config/server-whitelist.json",
            "--use-server-whitelist",
        ]
        if self.scenario == "open_world":
            args.append(f"--map-gen-seed {self.map_gen_seed}")
        if self.attach_mod:
            args.append("--mod-directory /opt/factorio/mods")
        factorio_bin = f"{self._factorio_emulator()} /opt/factorio/bin/x64/factorio".strip()
        return " ".join([factorio_bin, launch_command] + args)

    def _factorio_mod_path(self):
        env_override = os.environ.get("FACTORYVERSE_MODS_PATH")
        if env_override:
            return Path(env_override).expanduser()
        if self.os_name == "Windows":
            appdata = os.environ.get("APPDATA")
            if not appdata:
                # Fallback to the typical path if APPDATA is missing
                appdata = Path.home() / "AppData" / "Roaming"
            return Path(appdata) / "Factorio" / "mods"
        elif self.os_name == "Darwin":
            return Path.home() / "Library" / "Application Support" / "factorio" / "mods"
        else:  # Linux
            return Path.home() / ".factorio" / "mods"

    def _factorio_save_path(self):
        return self.state_dir / "saves"

    def _factorio_copy_save(self, save_file: str):
        save_dir = self._factorio_save_path().resolve()
        save_file_name = Path(save_file).name

        # Ensure the file is a zip file
        if not save_file_name.lower().endswith(".zip"):
            raise ValueError(f"Save file '{save_file}' is not a zip file.")

        # Check that the zip contains a level.dat file
        with zipfile.ZipFile(save_file, "r") as zf:
            if "level.dat" not in zf.namelist():
                raise ValueError(
                    f"Save file '{save_file}' does not contain a 'level.dat' file."
                )

        shutil.copy2(save_file, save_dir / save_file_name)
        print(f"Copied save file to {save_dir / save_file_name}")

    def _factorio_mods_volume(self):
        return {
            "source": str(self._factorio_mod_path().resolve()),
            "target": "/opt/factorio/mods",
            "type": "bind",
        }

    def _factorio_save_volume(self):
        return {
            "source": str(self._factorio_save_path().resolve()),
            "target": "/opt/factorio/saves",
            "type": "bind",
        }

    def _factorio_snapshots_volume(self, instance_id):
        snapshots_dir = self.work_dir / ".fv" / "snapshots" / f"factorio_{instance_id}"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        return {
            "source": str(snapshots_dir.resolve()),
            "target": "/opt/factorio/script-output",
            "type": "bind",
        }

    def _factorio_scenarios_volume(self):
        # Mount the factorio_verse scenario specifically, like in run-envs.sh
        pkg_root = ir.files("FactoryVerse")
        factorio_verse_dir = Path(pkg_root / ".." / "factorio" / "factorio_verse")
        if not factorio_verse_dir.exists():
            raise ValueError(f"Factorio verse directory '{factorio_verse_dir}' does not exist.")
        return {
            "source": str(factorio_verse_dir.resolve()),
            "target": "/opt/factorio/scenarios/factorio_verse",
            "type": "bind",
        }

    def _factorio_config_volume(self):
        # Resolve from package resources if provided
        config_dir = self.pkg_config_dir
        if config_dir is None:
            pkg_root = ir.files("FactoryVerse")
            config_dir = Path(pkg_root / ".." / "factorio" / "config")
        if not config_dir.exists():
            raise ValueError(f"Config directory '{config_dir}' does not exist.")
        return {
            "source": str(config_dir.resolve()),
            "target": "/opt/factorio/config",
            "type": "bind",
        }

    def factorio_services_dict(self, num_instances):
        services = {}
        for i in range(num_instances):
            host_rcon = START_RCON_PORT + i
            host_game = START_GAME_PORT + i
            volumes = [
                self._factorio_scenarios_volume(),
                self._factorio_config_volume(),
                self._factorio_snapshots_volume(i),
            ]
            if self.save_file:
                volumes.append(self._factorio_save_volume())
            if self.attach_mod:
                volumes.append(self._factorio_mods_volume())
            services[f"factorio_{i}"] = {
                "image": self.factorio_image,
                "platform": self._docker_platform(),
                "command": self._factorio_command(),
                "deploy": {"resources": {"limits": {"cpus": "1", "memory": "1024m"}}},
                "entrypoint": [],
                "ports": [
                    f"{host_game}:{self.internal_game_port}/udp",
                    f"{host_rcon}:{self.internal_rcon_port}/tcp",
                ],
                "pull_policy": "missing",
                "restart": "unless-stopped",
                "user": "factorio",
                "volumes": volumes,
            }
        return services
    
    def postgres_services_dict(self, num_factorio_instances=1):
        """Generate PostgreSQL service configuration."""
        # Mount entire snapshots directory for all instances
        snapshots_root = self.work_dir / ".fv" / "snapshots"
        snapshots_root.mkdir(parents=True, exist_ok=True)
        
        return {
            "postgres": {
                "image": "kartoza/postgis:latest",
                "platform": self._docker_platform(),
                "environment": {
                    "POSTGRES_USER": POSTGRES_USER,
                    "POSTGRES_PASSWORD": POSTGRES_PASSWORD,
                    "POSTGRES_DB": "postgres",  # Default, will create instance DBs
                    "FACTORIO_INSTANCE_COUNT": str(num_factorio_instances),
                },
                "ports": [f"{POSTGRES_PORT}:5432/tcp"],
                "volumes": [
                    {
                        "type": "volume",
                        "source": "factoryverse_pg_data",
                        "target": "/var/lib/postgresql/data",
                    },
                    # Mount all Factorio snapshot directories
                    {
                        "type": "bind",
                        "source": str(snapshots_root.resolve()),
                        "target": "/var/lib/factoryverse/snapshots",
                        "read_only": True,
                    },
                    # Schema initialization scripts
                    {
                        "type": "bind",
                        "source": str((Path(__file__).parent.parent / "db" / "schema").resolve()),
                        "target": "/docker-entrypoint-initdb.d",
                    }
                ],
                # "restart": "unless-stopped",
                "healthcheck": {
                    "test": ["CMD-SHELL", f"pg_isready -U {POSTGRES_USER} -d postgres -h localhost"],
                    "interval": "10s",
                    "timeout": "5s",
                    "retries": 5,
                },
                "networks": ["factoryverse"]
            }
        }

    def jupyter_services_dict(self):
        """Generate Jupyter service configuration."""
        return {
            "jupyter": {
                "image": "jupyter/minimal-notebook:latest",
                "platform": self._docker_platform(),
                "environment": {
                    "PG_HOST": "postgres",
                    "PG_PORT": "5432",
                    "PG_USER": POSTGRES_USER,
                    "PG_PASSWORD": POSTGRES_PASSWORD,
                    "PG_DB": POSTGRES_DB,
                    "PG_DSN": f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@postgres:5432/{POSTGRES_DB}",
                    "JUPYTER_ENABLE_LAB": "yes",
                    "GRANT_SUDO": "yes",
                    "JUPYTER_TOKEN": "",  # Disable token for local dev
                },
                "ports": ["8888:8888/tcp"],
                "volumes": [
                    {
                        "type": "bind",
                        "source": str((self.work_dir / "notebooks").resolve()),
                        "target": "/home/jovyan/work",
                    },
                    {
                        "type": "bind",
                        "source": str((Path(__file__).parent.parent.parent.parent).resolve()),
                        "target": "/home/jovyan/src",
                        "read_only": True,
                    },
                    {
                        "type": "bind",
                        "source": str((self.work_dir / ".fv-output").resolve()),
                        "target": "/home/jovyan/factorio-snapshots",
                        "read_only": True,
                    },
                ],
                "restart": "unless-stopped",
                "user": "root",
                "command": (
                    'bash -c "pip install --no-cache-dir psycopg2-binary factorio-rcon-py dill nbformat '
                    'aiodocker pyyaml pandas numpy matplotlib && start-notebook.sh --NotebookApp.token=\'\' --NotebookApp.password=\'\'"'
                ),
                "depends_on": {
                    "postgres": {
                        "condition": "service_healthy"
                    }
                },
                "networks": ["factoryverse"]
            }
        }

    def compose_dict(self, num_instances):
        """Generate complete docker-compose configuration with all services."""
        services = {}

        # Always include PostgreSQL and Jupyter
        services.update(self.postgres_services_dict(num_instances))
        services.update(self.jupyter_services_dict())

        # Add Factorio servers if requested
        if num_instances > 0:
            factorio_services = self.factorio_services_dict(num_instances)
            # Add network to factorio services
            for svc_name, svc_config in factorio_services.items():
                svc_config["networks"] = ["factoryverse"]
            services.update(factorio_services)

        return {
            "version": "3.8",
            "services": services,
            "volumes": {
                "factoryverse_pg_data": {
                    "driver": "local"
                }
            },
            "networks": {
                "factoryverse": {
                    "driver": "bridge"
                }
            }
        }

    def get_postgres_dsn(self):
        """Get PostgreSQL connection DSN for the service."""
        return f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@localhost:{POSTGRES_PORT}/{POSTGRES_DB}"

    def write(self, path: str, num_instances: int):
        # Handle save file copy if provided
        if self.save_file:
            save_dir = self._factorio_save_path()
            save_dir.mkdir(parents=True, exist_ok=True)
            self._factorio_copy_save(self.save_file)
        data = self.compose_dict(num_instances)
        with open(path, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)


class ClusterManager:
    """
    Pure Docker operations wrapper for FactoryVerse services.
    
    This class handles only low-level Docker Compose operations.
    All business logic and orchestration is handled by ExperimentManager.
    """

    def __init__(self, state_dir: Optional[Path] = None, work_dir: Optional[Path] = None):
        """
        Initialize ClusterManager.
        
        Args:
            state_dir: Directory for Docker state files (default: platform-specific)
            work_dir: Working directory for notebooks and data (default: current directory)
        """
        self.compose_cmd = setup_compose_cmd()
        self.state_dir = (state_dir or resolve_state_dir()).resolve()
        self.work_dir = (work_dir or resolve_work_dir()).resolve()
        self.compose_path = (self.state_dir / "docker-compose.yml").resolve()
        
        # Ensure directories exist
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.work_dir / "notebooks").mkdir(parents=True, exist_ok=True)
        (self.work_dir / ".fv-output").mkdir(parents=True, exist_ok=True)

    def _run_compose(self, args):
        """Run docker-compose command."""
        cmd = self.compose_cmd.split() + args
        subprocess.run(cmd, check=True)

    def generate_compose(self, num_instances: int, scenario: str, attach_mod: bool = False, save_file: Optional[str] = None):
        """
        Generate docker-compose.yml file.
        
        Args:
            num_instances: Number of Factorio instances (0 for platform only)
            scenario: Factorio scenario name
            attach_mod: Whether to attach mod directory
            save_file: Optional save file to load
        """
        # Package resources (read-only)
        pkg_root = ir.files("FactoryVerse")
        pkg_scenarios_dir = Path(pkg_root / ".." / "factorio" / "factorio_verse")
        pkg_config_dir = Path(pkg_root / ".." / "factorio" / "config")
        
        generator = ComposeGenerator(
            attach_mod=attach_mod,
            save_file=save_file,
            scenario=scenario,
            state_dir=self.state_dir,
            work_dir=self.work_dir,
            pkg_scenarios_dir=pkg_scenarios_dir,
            pkg_config_dir=pkg_config_dir,
        )
        generator.write(str(self.compose_path), num_instances)

    def start_services(self):
        """Start all services defined in docker-compose.yml."""
        if not self.compose_path.exists():
            raise RuntimeError("docker-compose.yml not found. Run generate_compose() first.")
        self._run_compose(["-f", str(self.compose_path), "up", "-d"])

    def stop_services(self):
        """Stop all services."""
        if not self.compose_path.exists():
            raise RuntimeError("docker-compose.yml not found.")
        self._run_compose(["-f", str(self.compose_path), "down"])

    def restart_services(self):
        """Restart all services."""
        if not self.compose_path.exists():
            raise RuntimeError("docker-compose.yml not found.")
        self._run_compose(["-f", str(self.compose_path), "restart"])

    def get_service_logs(self, service: str):
        """Get logs for a specific service."""
        if not self.compose_path.exists():
            raise RuntimeError("docker-compose.yml not found.")
        self._run_compose(["-f", str(self.compose_path), "logs", service])

    def is_service_running(self, service: str) -> bool:
        """Check if a specific service is running."""
        try:
            result = subprocess.run([
                "docker", "ps", "--filter", f"name={service}", "--format", "{{.Names}}"
            ], capture_output=True, text=True, check=True)
            return service in result.stdout
        except subprocess.CalledProcessError:
            return False

    def list_running_services(self) -> List[str]:
        """List all running FactoryVerse services."""
        try:
            result = subprocess.run([
                "docker", "ps", "--filter", "name=factoryverse_", "--format", "{{.Names}}"
            ], capture_output=True, text=True, check=True)
            return [name.strip() for name in result.stdout.split('\n') if name.strip()]
        except subprocess.CalledProcessError:
            return []

    def get_postgres_dsn(self) -> str:
        """Get PostgreSQL connection DSN."""
        return f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@localhost:{POSTGRES_PORT}/postgres"


# Legacy functions for backward compatibility
def start_cluster(num_instances, scenario, attach_mod=False, save_file=None):
    """Legacy function - use ExperimentManager instead."""
    manager = ClusterManager()
    manager.generate_compose(num_instances, scenario, attach_mod, save_file)
    manager.start_services()


def stop_cluster():
    """Legacy function - use ExperimentManager instead."""
    manager = ClusterManager()
    manager.stop_services()


def restart_cluster():
    """Legacy function - use ExperimentManager instead."""
    manager = ClusterManager()
    manager.restart_services()
