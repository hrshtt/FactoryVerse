"""Centralized configuration for FactoryVerse runtime.

This module provides a unified configuration system with:
- RCON connection settings (client and server ports)
- Docker container configuration
- Port allocation for agents and game servers
- Path management for script-output and data files

All settings use the FV_ prefix and are loaded from .env file.
"""

import platform
import logging
from pathlib import Path
from typing import Optional, List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


logger = logging.getLogger(__name__)


def _find_repo_root() -> Path:
    """Find repository root by looking for .env or fv_filters.yaml.

    Walks up from this file's location until it finds the repo root markers.

    Returns:
        Path to repository root

    Raises:
        RuntimeError: If repo root cannot be found
    """
    current = Path(__file__).resolve().parent

    # Walk up directory tree
    for _ in range(10):  # Limit search depth
        # Check for repo root markers
        if (current / ".env").exists() or (current / "fv_filters.yaml").exists():
            return current

        parent = current.parent
        if parent == current:  # Reached filesystem root
            break
        current = parent

    raise RuntimeError(
        "Could not find repository root. "
        "Looking for .env or fv_filters.yaml in parent directories."
    )


def _detect_factorio_dir() -> Path:
    """Detect local Factorio data directory based on platform."""
    import os

    os_name = platform.system()
    if os_name == "Darwin":
        return Path.home() / "Library" / "Application Support" / "factorio"
    elif os_name == "Windows":
        appdata = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
        return Path(appdata) / "Factorio"
    else:  # Linux
        return Path.home() / ".factorio"


# Detect repo root once at module load
_REPO_ROOT = _find_repo_root()


class FactoryVerseConfig(BaseSettings):
    """Unified configuration for FactoryVerse.

    Loaded from environment variables with .env file support.
    All settings use FV_ prefix.

    Example:
        >>> config = FactoryVerseConfig()
        >>> print(config.rcon_client_port)
        27100
        >>> print(config.get_rcon_port("server_0"))
        27000
    """

    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_prefix="FV_",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================================================================
    # RCON Configuration
    # =========================================================================

    rcon_host: str = Field(default="localhost", description="RCON host address")
    rcon_client_port: int = Field(
        default=27100, description="RCON port for Factorio client"
    )
    rcon_server_port_base: int = Field(
        default=27000,
        description="Base RCON port for servers (server N uses base + N)",
    )
    rcon_password: str = Field(default="factorio", description="RCON password")

    # =========================================================================
    # Docker Configuration
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

    game_port_base: int = Field(
        default=34197, description="Base game UDP port for servers"
    )
    agent_port_base: int = Field(
        default=34202, description="Base UDP port for agent action notifications"
    )
    snapshot_port_base: int = Field(
        default=34400, description="Base UDP port for snapshot/sync notifications (server N uses base + N)"
    )
    client_snapshot_port: int = Field(
        default=34500, description="UDP port for client snapshot/sync notifications"
    )
    enable_udp_port: int = Field(
        default=34200,
        description="Port for --enable-lua-udp (Factorio's incoming UDP listener)",
    )
    max_agents: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Max agents per server (determines UDP port range)",
    )

    # Expose the --enable-lua-udp listening port to host
    expose_incoming_udp: bool = Field(
        default=False,
        description="Whether to expose Factorio's incoming UDP port to host",
    )

    # =========================================================================
    # Internal Docker Ports (container-side)
    # =========================================================================

    internal_rcon_port: int = Field(
        default=27015, description="RCON port inside container"
    )
    internal_game_port: int = Field(
        default=34197, description="Game port inside container"
    )

    # =========================================================================
    # Map & Scenario Configuration
    # =========================================================================

    map_gen_seed: int = Field(
        default=44340, description="Map generation seed for reproducibility"
    )
    default_scenario: str = Field(
        default="test-ground", description="Default scenario to load"
    )

    # =========================================================================
    # Path Configuration
    # =========================================================================

    output_dir: Optional[Path] = Field(
        default=None,
        description="Override .fv-output directory (auto-detected if None)",
    )

    # =========================================================================
    # Computed Properties
    # =========================================================================

    @property
    def project_root(self) -> Path:
        """Get project root directory."""
        return _REPO_ROOT

    @property
    def fv_output_dir(self) -> Path:
        """Get .fv-output directory."""
        if self.output_dir:
            return self.output_dir
        return _REPO_ROOT / ".fv-output"

    @property
    def data_dump_path(self) -> Path:
        """Get path to factorio-data-dump.json (runtime dump)."""
        return self.fv_output_dir / "factorio-data-dump.json"

    @property
    def prototype_api_path(self) -> Path:
        """Get path to prototype-api.json (static API definitions).

        This file contains static type definitions from Factorio's API:
        - defines (enums like direction, entity_status)
        - type structures (MapPosition, BoundingBox, etc.)

        Downloaded from: https://lua-api.factorio.com/2.0.72/prototype-api.json
        Use `fv data refresh-api` or call download_prototype_api() to fetch.
        """
        return self.fv_output_dir / "prototype-api.json"

    @property
    def prototype_api_url(self) -> str:
        """URL to download prototype-api.json from Factorio developers."""
        return "https://lua-api.factorio.com/2.0.72/prototype-api.json"

    def download_prototype_api(self, force: bool = False) -> Path:
        """Download prototype-api.json from Factorio API.

        Args:
            force: If True, re-download even if file exists.

        Returns:
            Path to the downloaded file.

        Raises:
            RuntimeError: If download fails.
        """
        import urllib.request

        dest = self.prototype_api_path

        if dest.exists() and not force:
            return dest

        # Ensure output dir exists
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            print(f"Downloading prototype-api.json from {self.prototype_api_url}...")
            urllib.request.urlretrieve(self.prototype_api_url, dest)
            print(f"Downloaded to {dest}")
            return dest
        except Exception as e:
            raise RuntimeError(
                f"Failed to download prototype-api.json: {e}\n"
                f"You can manually download from: {self.prototype_api_url}"
            ) from e

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

    @property
    def scenarios_dir(self) -> Path:
        """Get repo scenarios directory (project source).

        This is the authoritative source. Local scenarios are merged in
        when needed.
        """
        return self.project_root / "src" / "factorio" / "scenarios"

    @property
    def local_scenarios_dir(self) -> Path:
        """Get local Factorio scenarios directory.

        This is where user's custom scenarios live:
        - macOS: ~/Library/Application Support/factorio/scenarios
        - Linux: ~/.factorio/scenarios
        - Windows: %APPDATA%/Factorio/scenarios
        """
        return _detect_factorio_dir() / "scenarios"

    @property
    def server_config_dir(self) -> Path:
        """Get server config directory."""
        return self.project_root / "src" / "factorio" / "config"

    @property
    def mods_dir(self) -> Path:
        """Get local Factorio mods directory."""
        return _detect_factorio_dir() / "mods"

    @property
    def embodied_agent_mod_dir(self) -> Path:
        """Get fv_embodied_agent mod source directory."""
        return self.project_root / "src" / "fv_embodied_agent"

    @property
    def snapshot_mod_dir(self) -> Path:
        """Get fv_snapshot mod source directory."""
        return self.project_root / "src" / "fv_snapshot"

    # =========================================================================
    # Methods
    # =========================================================================

    def get_rcon_port(self, instance: str) -> int:
        """Get RCON port for an instance.

        Args:
            instance: 'client' or 'server_N' (e.g., 'server_0', 'server_1')

        Returns:
            RCON port number
        """
        if instance == "client":
            return self.rcon_client_port
        if instance.startswith("server_"):
            server_id = int(instance.split("_")[1])
            return self.rcon_server_port_base + server_id
        raise ValueError(
            f"Invalid instance: {instance}. Expected 'client' or 'server_N'"
        )

    def get_game_port(self, server_index: int) -> int:
        """Get game UDP port for a server instance."""
        return self.game_port_base + server_index

    def get_snapshot_port(self, instance: str) -> int:
        """Get snapshot UDP port for an instance.
        
        Args:
            instance: 'client' or 'server_N' (e.g., 'server_0', 'server_1')
            
        Returns:
            Snapshot UDP port number
        """
        if instance == "client":
            return self.client_snapshot_port
        if instance.startswith("server_"):
            server_id = int(instance.split("_")[1])
            return self.snapshot_port_base + server_id
        raise ValueError(
            f"Invalid instance: {instance}. Expected 'client' or 'server_N'"
        )

    def get_agent_port(self, agent_index: int, server_index: Optional[int] = None) -> int:
        """Get UDP port for a specific agent.
        
        Args:
            agent_index: Agent index (0-based)
            server_index: Server index for per-server isolation. None means client.
            
        Returns:
            Agent UDP port number
        """
        if agent_index >= self.max_agents:
            raise ValueError(
                f"Agent index {agent_index} exceeds max_agents {self.max_agents}"
            )
        
        if server_index is not None:
            # Each server gets its own range of max_agents ports
            base_port = self.agent_port_base + (server_index * self.max_agents)
            return base_port + agent_index
        else:
            # Client mode: simple increment from base
            return self.agent_port_base + agent_index

    def get_agent_port_range(self, server_index: Optional[int] = None) -> List[int]:
        """Get list of agent ports for a server or client.
        
        Args:
            server_index: Server index for per-server isolation. None means client.
            
        Returns:
            List of agent UDP ports
        """
        if server_index is not None:
            base_port = self.agent_port_base + (server_index * self.max_agents)
            return [base_port + i for i in range(self.max_agents)]
        else:
            return [self.agent_port_base + i for i in range(self.max_agents)]

    def get_script_output_dir(self, instance: str) -> Path:
        """Get script-output directory for an instance.

        Args:
            instance: 'client' or 'server_N' (e.g., 'server_0', 'server_1')

        Returns:
            Path to script-output directory
        """
        if instance == "client":
            return _detect_factorio_dir() / "script-output"
        if instance.startswith("server_"):
            server_id = int(instance.split("_")[1])
            return self.get_server_output_dir(server_id)
        raise ValueError(
            f"Invalid instance: {instance}. Expected 'client' or 'server_N'"
        )

    def get_server_output_dir(self, server_index: int) -> Path:
        """Get output directory for a specific server instance."""
        output_dir = self.fv_output_dir / f"server_{server_index}"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def get_snapshot_dir(self, instance: str) -> Path:
        """Get snapshot directory for an instance.

        Returns:
            Path to snapshot directory, creates if doesn't exist
        """
        script_output = self.get_script_output_dir(instance)
        snapshot_dir = script_output / "factoryverse" / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        return snapshot_dir

    def get_dump_file(self) -> Path:
        """Get factorio-data-dump.json path.

        Returns:
            Path to factorio-data-dump.json

        Raises:
            ValueError: If file not found
        """
        dump_path = self.data_dump_path
        if dump_path.exists():
            return dump_path

        raise ValueError(
            f"factorio-data-dump.json not found at {dump_path}\n"
            "Run 'fv data refresh' to generate it."
        )

    def _list_scenarios_in_dir(self, directory: Path) -> List[str]:
        """List valid scenarios in a directory."""
        if not directory.exists():
            return []
        return [
            d.name
            for d in directory.iterdir()
            if d.is_dir() and (d / "control.lua").exists()
        ]

    def list_scenarios(self, include_local: bool = True) -> List[str]:
        """List available scenarios from both repo and local directories.

        Args:
            include_local: If True, include local Factorio scenarios

        Returns:
            List of scenario names (repo scenarios take precedence)
        """
        # Start with repo scenarios (these take precedence)
        repo_scenarios = set(self._list_scenarios_in_dir(self.scenarios_dir))

        if include_local:
            # Add local scenarios that don't conflict with repo
            local_scenarios = set(self._list_scenarios_in_dir(self.local_scenarios_dir))
            # Only add local scenarios that aren't already in repo
            all_scenarios = repo_scenarios | local_scenarios
        else:
            all_scenarios = repo_scenarios

        return sorted(list(all_scenarios))

    def validate_scenario(self, scenario: str) -> bool:
        """Check if a scenario exists (in repo or local directories)."""
        # Check repo first
        repo_path = self.scenarios_dir / scenario
        if repo_path.exists() and (repo_path / "control.lua").exists():
            return True
        # Check local
        local_path = self.local_scenarios_dir / scenario
        if local_path.exists() and (local_path / "control.lua").exists():
            return True
        return False

    def get_scenario_source(self, scenario: str) -> Optional[Path]:
        """Get the source path for a scenario (repo takes precedence).

        Args:
            scenario: Scenario name

        Returns:
            Path to scenario directory, or None if not found
        """
        # Repo takes precedence
        repo_path = self.scenarios_dir / scenario
        if repo_path.exists() and (repo_path / "control.lua").exists():
            return repo_path
        # Fallback to local
        local_path = self.local_scenarios_dir / scenario
        if local_path.exists() and (local_path / "control.lua").exists():
            return local_path
        return None

    def is_repo_scenario(self, scenario: str) -> bool:
        """Check if a scenario is from the repo (hot-reloadable).

        Args:
            scenario: Scenario name

        Returns:
            True if scenario exists in repo's scenarios directory
        """
        repo_path = self.scenarios_dir / scenario
        return repo_path.exists() and (repo_path / "control.lua").exists()


class AgentRuntimeConfig:
    """Per-agent runtime configuration.

    Each agent runtime session gets its own:
    - UDP port (unique)
    - Session directory (unique)
    - Database (unique, in session dir)
    - Agent ID (unique)

    This design supports multiple concurrent agents.

    Example:
        >>> config = AgentRuntimeConfig(
        ...     session_dir=Path("/tmp/session1"),
        ...     agent_id="agent_1"
        ... )
        >>> print(config.udp_port)
        34202
        >>> print(config.db_path)
        /tmp/session1/map.duckdb
    """

    def __init__(
        self,
        session_dir: Path,
        agent_id: str = "agent_1",
        udp_port: Optional[int] = None,
        global_config: Optional[FactoryVerseConfig] = None,
    ):
        """Initialize per-agent runtime config.

        Args:
            session_dir: Session directory (e.g., sessions/intellect-3/run_001)
            agent_id: Agent identifier (e.g., "agent_1", "agent_2")
            udp_port: UDP port for this agent (auto-allocated if None)
            global_config: Global config (loads from env if None)
        """
        self.session_dir = Path(session_dir)
        self.agent_id = agent_id
        self.global_config = global_config or FactoryVerseConfig()

        # Auto-assign UDP port if not provided
        self.udp_port = udp_port or self._allocate_udp_port()

        # Session-specific paths
        self.db_path = self.session_dir / "map.duckdb"

        # Ensure session directory exists
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def _allocate_udp_port(self) -> int:
        """Allocate UDP port for this agent.
        
        Uses dynamic port discovery to find an available UDP port.
        This is safer than pre-allocating as it checks availability at runtime.

        Returns:
            Allocated UDP port number
        """
        from FactoryVerse.utils.port_utils import find_free_udp_port
        
        try:
            # Try to find a free port starting from the agent_port_base
            return find_free_udp_port(
                start_port=self.global_config.agent_port_base,
                max_attempts=200,  # Search up to 200 ports
                host=self.global_config.rcon_host
            )
        except RuntimeError as e:
            # Fallback to base port if dynamic allocation fails
            logger.warning(f"Dynamic port allocation failed: {e}. Using base port.")
            return self.global_config.agent_port_base

    @property
    def rcon_host(self) -> str:
        """RCON host (shared across all agents)."""
        return self.global_config.rcon_host

    @property
    def rcon_port(self) -> int:
        """RCON port - uses client port by default."""
        return self.global_config.rcon_client_port

    @property
    def rcon_password(self) -> str:
        """RCON password (shared across all agents)."""
        return self.global_config.rcon_password


# Convenience function for single-agent scenarios
def get_runtime_config(
    session_dir: Path, agent_id: str = "agent_1", udp_port: Optional[int] = None
) -> AgentRuntimeConfig:
    """Get runtime config for an agent session.

    Convenience function for creating agent runtime config.

    Args:
        session_dir: Session directory path
        agent_id: Agent identifier (default: "agent_1")
        udp_port: Explicit UDP port (auto-allocated if None)

    Returns:
        AgentRuntimeConfig instance

    Example:
        >>> config = get_runtime_config(Path("/tmp/session1"))
        >>> print(config.agent_id)
        'agent_1'
    """
    return AgentRuntimeConfig(
        session_dir=session_dir, agent_id=agent_id, udp_port=udp_port
    )


# Singleton instance for easy access
_config: Optional[FactoryVerseConfig] = None


def get_config() -> FactoryVerseConfig:
    """Get configuration singleton."""
    global _config
    if _config is None:
        _config = FactoryVerseConfig()
    return _config
