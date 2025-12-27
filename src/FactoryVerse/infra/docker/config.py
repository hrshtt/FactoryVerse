"""
FactoryVerse Docker Server Configuration.

Uses pydantic-settings to load configuration from environment variables and .env files.
"""

import logging
import os
import platform
from pathlib import Path
from typing import Optional, List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _get_project_root() -> Path:
    """Get the project root directory."""
    # Navigate up from src/FactoryVerse/infra/docker/config.py to project root
    return Path(__file__).resolve().parent.parent.parent.parent.parent


def _detect_local_mods_path() -> Path:
    """Detect local Factorio mod directory based on platform."""
    os_name = platform.system()
    if os_name == "Darwin":
        return Path.home() / "Library" / "Application Support" / "factorio" / "mods"
    elif os_name == "Windows":
        appdata = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
        return Path(appdata) / "Factorio" / "mods"
    else:  # Linux
        return Path.home() / ".factorio" / "mods"


class ServerConfig(BaseSettings):
    """Configuration for Factorio headless servers managed by FactoryVerse.

    Loaded from environment variables and .env file.
    All FV_ prefixed variables are auto-loaded.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FV_",
        extra="ignore",
    )

    # =========================================================================
    # Docker Image & Platform
    # =========================================================================

    docker_image: str = Field(
        default="factoriotools/factorio:2.0.72",
        description="Docker image for Factorio server",
    )
    force_amd64: bool = Field(
        default=False, description="Force amd64 platform even on ARM"
    )

    # =========================================================================
    # Port Configuration
    # =========================================================================

    # Base ports - each server instance gets port + instance_id
    rcon_port_base: int = Field(
        default=27000,
        description="Base RCON port (server 0 uses this, server 1 uses +1, etc.)",
    )
    game_port_base: int = Field(default=34197, description="Base game UDP port")

    # UDP ports for agent/snapshot communication
    agent_port_base: int = Field(
        default=34202, description="Base UDP port for agent action notifications"
    )
    snapshot_port: int = Field(
        default=34400,
        alias="FV_SNAPSHOT_PORT",
        description="UDP port for snapshot/sync notifications",
    )
    enable_udp_port: int = Field(
        default=34200,
        description="Port passed to --enable-lua-udp (Factorio's incoming UDP listener)",
    )

    # Agent configuration
    max_agents: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of agents (determines UDP port range)",
    )

    # =========================================================================
    # Server Behavior
    # =========================================================================

    rcon_password: str = Field(default="factorio", description="RCON password")
    map_gen_seed: int = Field(
        default=44340, description="Map generation seed for reproducibility"
    )
    default_scenario: str = Field(
        default="test-ground", description="Default scenario to load"
    )

    # Expose the --enable-lua-udp listening port to host
    expose_incoming_udp: bool = Field(
        default=False,
        description="Whether to expose Factorio's incoming UDP port to host",
    )

    # =========================================================================
    # Internal Docker ports (container-side)
    # =========================================================================

    internal_rcon_port: int = Field(default=27015)
    internal_game_port: int = Field(default=34197)

    # =========================================================================
    # Computed properties
    # =========================================================================

    @property
    def arch(self) -> str:
        """Get current architecture."""
        return platform.machine()

    @property
    def docker_platform(self) -> str:
        """Get Docker platform string."""
        if self.force_amd64:
            return "linux/amd64"
        return "linux/arm64" if self.arch in ["arm64", "aarch64"] else "linux/amd64"

    @property
    def factorio_emulator(self) -> str:
        """Get emulator prefix for ARM platforms."""
        if self.force_amd64:
            return ""
        return "/bin/box64" if self.arch in ["arm64", "aarch64"] else ""

    def get_agent_port(self, agent_index: int) -> int:
        """Get UDP port for a specific agent index."""
        if agent_index >= self.max_agents:
            raise ValueError(
                f"Agent index {agent_index} exceeds max_agents {self.max_agents}"
            )
        return self.agent_port_base + agent_index

    def get_agent_port_range(self) -> List[int]:
        """Get list of all agent ports."""
        return [self.agent_port_base + i for i in range(self.max_agents)]

    def get_rcon_port(self, server_index: int) -> int:
        """Get RCON port for a specific server instance."""
        return self.rcon_port_base + server_index

    def get_game_port(self, server_index: int) -> int:
        """Get game UDP port for a specific server instance."""
        return self.game_port_base + server_index


class PathConfig(BaseSettings):
    """Path configuration for FactoryVerse.

    Handles project directories and Factorio paths.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Override paths (if not set, auto-detected)
    factorio_script_output_dir: Optional[Path] = Field(
        default=None,
        alias="FACTORIO_SCRIPT_OUTPUT_DIR",
        description="Override Factorio script-output directory",
    )

    @property
    def project_root(self) -> Path:
        """Get project root directory."""
        return _get_project_root()

    @property
    def scenarios_dir(self) -> Path:
        """Get scenarios directory."""
        return self.project_root / "src" / "factorio" / "scenarios"

    @property
    def server_config_dir(self) -> Path:
        """Get server config directory."""
        return self.project_root / "src" / "factorio" / "config"

    @property
    def mods_dir(self) -> Path:
        """Get local Factorio mods directory."""
        return _detect_local_mods_path()

    @property
    def embodied_agent_mod_dir(self) -> Path:
        """Get fv_embodied_agent mod source directory."""
        return self.project_root / "src" / "fv_embodied_agent"

    @property
    def snapshot_mod_dir(self) -> Path:
        """Get fv_snapshot mod source directory."""
        return self.project_root / "src" / "fv_snapshot"

    @property
    def output_dir(self) -> Path:
        """Get .fv-output directory for server outputs."""
        return self.project_root / ".fv-output"

    def get_server_output_dir(self, server_index: int) -> Path:
        """Get output directory for a specific server instance."""
        output_dir = self.output_dir / f"output_{server_index}"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def list_scenarios(self) -> List[str]:
        """List available scenarios."""
        if not self.scenarios_dir.exists():
            return []
        return [
            d.name
            for d in self.scenarios_dir.iterdir()
            if d.is_dir() and (d / "control.lua").exists()
        ]

    def validate_scenario(self, scenario: str) -> bool:
        """Check if a scenario exists."""
        scenario_dir = self.scenarios_dir / scenario
        return scenario_dir.exists() and (scenario_dir / "control.lua").exists()


# Create singleton instances for easy import
_server_config: Optional[ServerConfig] = None
_path_config: Optional[PathConfig] = None


def get_server_config() -> ServerConfig:
    """Get server configuration singleton."""
    global _server_config
    if _server_config is None:
        _server_config = ServerConfig()
    return _server_config


def get_path_config() -> PathConfig:
    """Get path configuration singleton."""
    global _path_config
    if _path_config is None:
        _path_config = PathConfig()
    return _path_config
