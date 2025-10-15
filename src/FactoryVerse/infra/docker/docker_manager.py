#!/usr/bin/env python3

import os
import platform
import subprocess
import sys
import socket
from pathlib import Path
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

    Env override: FLE_STATE_DIR
    Default: platformdirs.user_state_dir("fle")
    """
    override = os.environ.get("FLE_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path(user_state_dir("fle"))


def resolve_work_dir() -> Path:
    """Resolve user-visible working directory root with env override.

    Env override: FLE_WORKDIR
    Default: current working directory
    """
    override = os.environ.get("FLE_WORKDIR")
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
        env_override = os.environ.get("FLE_MODS_PATH")
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

    def _factorio_screenshots_volume(self):
        screenshots_dir = self.work_dir / ".fle" / "data" / "_screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        return {
            "source": str(screenshots_dir.resolve()),
            "target": "/opt/factorio/script-output",
            "type": "bind",
        }

    def _factorio_scenarios_volume(self):
        # Resolve from package resources if provided
        scenarios_dir = self.pkg_scenarios_dir
        if scenarios_dir is None:
            pkg_root = ir.files("fle.cluster")
            scenarios_dir = Path(pkg_root / "scenarios")
        if not scenarios_dir.exists():
            raise ValueError(f"Scenarios directory '{scenarios_dir}' does not exist.")
        return {
            "source": str(scenarios_dir.resolve()),
            "target": "/opt/factorio/scenarios",
            "type": "bind",
        }

    def _factorio_config_volume(self):
        # Resolve from package resources if provided
        config_dir = self.pkg_config_dir
        if config_dir is None:
            pkg_root = ir.files("fle.cluster")
            config_dir = Path(pkg_root / "config")
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
                self._factorio_screenshots_volume(),
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
    
    def postgres_services_dict(self):
        """Generate PostgreSQL service configuration."""
        return {
            "postgres": {
                "image": "postgis/postgis:15-3.3",
                "platform": self._docker_platform(),
                "environment": {
                    "POSTGRES_USER": POSTGRES_USER,
                    "POSTGRES_PASSWORD": POSTGRES_PASSWORD,
                    "POSTGRES_DB": POSTGRES_DB,
                },
                "ports": [f"{POSTGRES_PORT}:5432/tcp"],
                "volumes": [
                    {
                        "type": "volume",
                        "source": "factoryverse_pg_data",
                        "target": "/var/lib/postgresql/data",
                    },
                    # Auto-initialize experiment schema
                    {
                        "type": "bind",
                        "source": str((Path(__file__).parent.parent / "db" / "experiment_schema.sql").resolve()),
                        "target": "/docker-entrypoint-initdb.d/01-experiment_schema.sql",
                        "read_only": True,
                    }
                ],
                "restart": "unless-stopped",
                "healthcheck": {
                    "test": ["CMD-SHELL", "pg_isready -U factoryverse -d factoryverse"],
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
                "image": "jupyter/scipy-notebook:python-3.12",
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
                    'aiodocker pyyaml && start-notebook.sh --NotebookApp.token=\'\' --NotebookApp.password=\'\'"'
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
        services.update(self.postgres_services_dict())
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
    """Simple class wrapper to manage platform detection, compose, and lifecycle."""

    def __init__(self):
        self.compose_cmd = setup_compose_cmd()
        self.internal_rcon_port = ComposeGenerator.internal_rcon_port
        self.internal_game_port = ComposeGenerator.internal_game_port
        # Resolve key paths
        self.state_dir = resolve_state_dir()
        self.work_dir = resolve_work_dir()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.compose_path = (self.state_dir / "docker-compose.yml").resolve()

        # Ensure necessary directories exist
        (self.work_dir / "notebooks").mkdir(parents=True, exist_ok=True)
        (self.work_dir / ".fv-output").mkdir(parents=True, exist_ok=True)

        # Package resources (read-only)
        pkg_root = ir.files("fle.cluster")
        self.pkg_scenarios_dir = Path(pkg_root / "scenarios")
        self.pkg_config_dir = Path(pkg_root / "config")

    def _run_compose(self, args):
        cmd = self.compose_cmd.split() + args
        subprocess.run(cmd, check=True)

    def generate(self, num_instances, scenario, attach_mod=False, save_file=None):
        generator = ComposeGenerator(
            attach_mod=attach_mod,
            save_file=save_file,
            scenario=scenario,
            state_dir=self.state_dir,
            work_dir=self.work_dir,
            pkg_scenarios_dir=self.pkg_scenarios_dir,
            pkg_config_dir=self.pkg_config_dir,
        )
        generator.write(str(self.compose_path), num_instances)
        print(
            f"Generated compose at {self.compose_path} for {num_instances} instance(s) using scenario {scenario}"
        )

    def _is_tcp_listening(self, port):
        try:
            c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            c.settimeout(0.2)
            c.connect(("127.0.0.1", port))
            c.close()
            return True
        except OSError:
            return False

    def _find_port_conflicts(self, num_instances):
        listening = []
        for i in range(num_instances):
            tcp_port = START_RCON_PORT + i
            if self._is_tcp_listening(tcp_port):
                listening.append(f"tcp/{tcp_port}")
        return listening

    def start(self, num_instances, scenario, attach_mod=False, save_file=None):
        listening = self._find_port_conflicts(num_instances)
        if listening:
            print("Error: Required ports are in use:")
            print("  " + ", ".join(listening))
            print(
                "It looks like a Factorio cluster (or another service) is running. "
                "Stop it with 'fle cluster stop' (or 'docker compose -f docker-compose.yml down' in fle/cluster) and retry."
            )
            sys.exit(1)

        self.generate(num_instances, scenario, attach_mod, save_file)

        # Path summary
        print("Paths:")
        print(f"  state_dir:   {self.state_dir}")
        print(f"  work_dir:    {self.work_dir}")
        print(f"  compose:     {self.compose_path}")
        print(f"  scenarios:   {self.pkg_scenarios_dir}")
        print(f"  config:      {self.pkg_config_dir}")

        print(
            f"Starting FactoryVerse platform (PostgreSQL + Jupyter + {num_instances} Factorio instance(s))..."
        )
        self._run_compose(["-f", str(self.compose_path), "up", "-d"])
        print(
            f"\n✅ FactoryVerse cluster started!"
        )
        print(f"\nServices:")
        print(f"  📊 PostgreSQL:  localhost:{POSTGRES_PORT}")
        print(f"  📓 Jupyter:     http://localhost:8888")
        if num_instances > 0:
            print(f"  🎮 Factorio:    {num_instances} server(s)")
            for i in range(num_instances):
                print(f"     - factorio_{i}: RCON port {START_RCON_PORT + i}, Game port {START_GAME_PORT + i}")

        # Show PostgreSQL connection info
        generator = ComposeGenerator(
            attach_mod=attach_mod,
            save_file=save_file,
            scenario=scenario,
            state_dir=self.state_dir,
            work_dir=self.work_dir,
            pkg_scenarios_dir=self.pkg_scenarios_dir,
            pkg_config_dir=self.pkg_config_dir,
        )
        postgres_dsn = generator.get_postgres_dsn()
        print(f"\n🔗 PostgreSQL DSN: {postgres_dsn}")
        print(f"📁 Notebooks: {self.work_dir / 'notebooks'}")
        print(f"\n💡 Next: Create an experiment with 'factoryverse experiment create <agent-id>'")

    def stop(self):
        if not self.compose_path.exists():
            print(
                "Error: docker-compose.yml not found in state dir. No cluster to stop."
            )
            sys.exit(1)
        print("Stopping Factorio cluster...")
        self._run_compose(["-f", str(self.compose_path), "down"])
        print("Cluster stopped.")

    def restart(self):
        if not self.compose_path.exists():
            print(
                "Error: docker-compose.yml not found in state dir. No cluster to restart."
            )
            sys.exit(1)
        print(
            "Restarting existing Factorio services without regenerating docker-compose..."
        )
        self._run_compose(["-f", str(self.compose_path), "restart"])
        print("Factorio services restarted.")

    def logs(self, service: str = "factorio_0"):
        if not self.compose_path.exists():
            print(
                "Error: docker-compose.yml not found in state dir. Nothing to show logs for."
            )
            sys.exit(1)
        self._run_compose(["-f", str(self.compose_path), "logs", service])

    def show(self):
        # Show both Factorio and PostgreSQL containers
        ps_cmd = [
            "docker",
            "ps",
            "--filter",
            "name=factorio_",
            "--filter",
            "name=postgres",
            "--format",
            "table {{.Names}}\t{{.Ports}}\t{{.Status}}",
        ]
        ps = subprocess.run(ps_cmd, capture_output=True, text=True)
        out = ps.stdout.strip()
        if not out:
            print("No FactoryVerse containers found.")
            return
        print("FactoryVerse Services:")
        print(out)


def start_cluster(num_instances, scenario, attach_mod=False, save_file=None):
    manager = ClusterManager()
    manager.start(
        num_instances=num_instances,
        scenario=scenario,
        attach_mod=attach_mod,
        save_file=save_file,
    )


def stop_cluster():
    manager = ClusterManager()
    manager.stop()


def restart_cluster():
    manager = ClusterManager()
    manager.restart()
