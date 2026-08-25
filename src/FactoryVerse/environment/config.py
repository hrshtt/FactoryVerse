"""Centralized configuration for FactoryVerse.

This module provides a unified configuration system with:
- FactoryVerseConfig: Base settings from .env (RCON, Docker, ports, paths)
- AgentRuntimeConfig: Per-agent session configuration
- Environment-specific configs for each tier

All settings use the FV_ prefix and are loaded from .env file.
"""

import platform
import logging
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


logger = logging.getLogger(__name__)


# =============================================================================
# Path Detection Utilities
# =============================================================================


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


def _detect_factorio_install_dir() -> Optional[Path]:
    """Detect Factorio installation directory (where inbuilt scenarios live).

    Returns:
        Path to Factorio installation, or None if not found.

    Platform-specific locations:
        - macOS Steam: ~/Library/Application Support/Steam/steamapps/common/Factorio/factorio.app/Contents
        - macOS standalone: /Applications/factorio.app/Contents
        - Linux Steam: ~/.steam/steam/steamapps/common/Factorio
        - Linux standalone: /opt/factorio
        - Windows Steam: C:/Program Files (x86)/Steam/steamapps/common/Factorio
    """
    os_name = platform.system()

    candidates = []
    if os_name == "Darwin":
        candidates = [
            # Steam installation
            Path.home() / "Library" / "Application Support" / "Steam" / "steamapps" / "common" / "Factorio" / "factorio.app" / "Contents",
            # Standalone installation
            Path("/Applications/factorio.app/Contents"),
        ]
    elif os_name == "Windows":
        candidates = [
            # Steam installation (common locations)
            Path("C:/Program Files (x86)/Steam/steamapps/common/Factorio"),
            Path("C:/Program Files/Steam/steamapps/common/Factorio"),
            # Standalone installation
            Path("C:/Program Files/Factorio"),
        ]
    else:  # Linux
        candidates = [
            # Steam installation
            Path.home() / ".steam" / "steam" / "steamapps" / "common" / "Factorio",
            Path.home() / ".local" / "share" / "Steam" / "steamapps" / "common" / "Factorio",
            # Standalone installation
            Path("/opt/factorio"),
            Path.home() / "factorio",
        ]

    for candidate in candidates:
        # Check for data/base directory which contains scenarios
        data_base = candidate / "data" / "base"
        if data_base.exists():
            return candidate

    return None


# Detect repo root once at module load
_REPO_ROOT = _find_repo_root()


# =============================================================================
# Base Configuration (from .env)
# =============================================================================


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
        default="factoriotools/factorio:2.0.76",
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
    def inbuilt_scenarios_dir(self) -> Optional[Path]:
        """Get Factorio's inbuilt scenarios directory.

        These are bundled with Factorio (freeplay, sandbox, etc.):
        - macOS: .../Factorio.app/Contents/data/base/scenarios
        - Linux/Windows: .../Factorio/data/base/scenarios

        Returns:
            Path to inbuilt scenarios, or None if Factorio not found.
        """
        install_dir = _detect_factorio_install_dir()
        if install_dir:
            return install_dir / "data" / "base" / "scenarios"
        return None

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

    @property
    def placement_hints_mod_dir(self) -> Path:
        """Get fv_placement_hints mod source directory."""
        return self.project_root / "src" / "fv_placement_hints"

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
        """List available scenarios from repo, inbuilt, and optionally local directories.

        Priority order (highest first):
        1. Repo scenarios (custom FactoryVerse scenarios)
        2. Inbuilt Factorio scenarios (freeplay, sandbox, etc.)
        3. Local user scenarios (if include_local=True)

        Args:
            include_local: If True, include local user Factorio scenarios

        Returns:
            List of scenario names (deduplicated, sorted)
        """
        # Start with repo scenarios (highest precedence)
        all_scenarios = set(self._list_scenarios_in_dir(self.scenarios_dir))

        # Add inbuilt Factorio scenarios
        if self.inbuilt_scenarios_dir:
            inbuilt = set(self._list_scenarios_in_dir(self.inbuilt_scenarios_dir))
            all_scenarios |= inbuilt

        # Add local user scenarios (lowest precedence)
        if include_local:
            local_scenarios = set(self._list_scenarios_in_dir(self.local_scenarios_dir))
            all_scenarios |= local_scenarios

        return sorted(list(all_scenarios))

    def validate_scenario(self, scenario: str) -> bool:
        """Check if a scenario exists (in repo, inbuilt, or local directories)."""
        # Check repo first (highest precedence)
        repo_path = self.scenarios_dir / scenario
        if repo_path.exists() and (repo_path / "control.lua").exists():
            return True
        # Check inbuilt Factorio scenarios
        if self.inbuilt_scenarios_dir:
            inbuilt_path = self.inbuilt_scenarios_dir / scenario
            if inbuilt_path.exists() and (inbuilt_path / "control.lua").exists():
                return True
        # Check local user scenarios
        local_path = self.local_scenarios_dir / scenario
        if local_path.exists() and (local_path / "control.lua").exists():
            return True
        return False

    def get_scenario_source(self, scenario: str) -> Optional[Path]:
        """Get the source path for a scenario.

        Priority order (highest first):
        1. Repo scenarios
        2. Inbuilt Factorio scenarios
        3. Local user scenarios

        Args:
            scenario: Scenario name

        Returns:
            Path to scenario directory, or None if not found
        """
        # Repo takes precedence
        repo_path = self.scenarios_dir / scenario
        if repo_path.exists() and (repo_path / "control.lua").exists():
            return repo_path
        # Check inbuilt Factorio scenarios
        if self.inbuilt_scenarios_dir:
            inbuilt_path = self.inbuilt_scenarios_dir / scenario
            if inbuilt_path.exists() and (inbuilt_path / "control.lua").exists():
                return inbuilt_path
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

    def is_inbuilt_scenario(self, scenario: str) -> bool:
        """Check if a scenario is an inbuilt Factorio scenario.

        Args:
            scenario: Scenario name

        Returns:
            True if scenario exists in Factorio's inbuilt scenarios directory
        """
        if not self.inbuilt_scenarios_dir:
            return False
        inbuilt_path = self.inbuilt_scenarios_dir / scenario
        return inbuilt_path.exists() and (inbuilt_path / "control.lua").exists()


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


def reset_config() -> None:
    """Reset configuration singleton (for testing)."""
    global _config
    _config = None


# =============================================================================
# Environment-Specific Enums and Configs
# =============================================================================


class InfraMode(str, Enum):
    """Factorio infrastructure mode."""

    CLIENT = "client"  # Manage client lifecycle
    SERVER = "server"  # Manage server lifecycle (Docker)
    CLIENT_AND_SERVER = "client_and_server"  # Manage both
    EXTERNAL = "external"  # Connect to pre-existing instance, don't manage lifecycle


class RuntimeVariant(str, Enum):
    """Runtime tier variant controlling loaded components."""

    MINIMAL = "minimal"  # No remote_view, no DuckDB
    FULL = "full"  # All agent modules including remote_view


class RuntimeAccessProfile(str, Enum):
    """Actor-visible capabilities exposed by Tier 4 code execution."""

    PRODUCTION = "production"  # Embodied interfaces and DuckDB; no raw RCON/admin
    DEBUG = "debug"  # Development profile with low-level control objects


class ExecutionMode(str, Enum):
    """Code execution mode for the runtime."""

    INPROCESS = "inprocess"  # Execute in same Python process (lightweight, no notebook)
    JUPYTER = "jupyter"  # Execute in Jupyter kernel (isolated, with notebook logging)


class InteractionMode(str, Enum):
    """Agent interaction mode."""

    AUTONOMOUS = "autonomous"  # Continuous agent loop
    ASSISTED = "assisted"  # Single-turn interaction
    MCP = "mcp"  # MCP server mode


class SessionMode(str, Enum):
    """Session directory and trajectory mode.

    Controls how session directories are structured and what artifacts are created.
    """

    LLM = "llm"  # Full LLM agent session: .fv-output/runs/{provider}/{model}/{run_id}/
    EVAL = "eval"  # Eval run session: .fv-output/evals/{task_key}/{run_id}/
    NONE = "none"  # No session directory (testing only, no trajectory)


class InfraConfig(BaseModel):
    """Tier 1: Factorio Infrastructure configuration."""

    mode: InfraMode = Field(
        default=InfraMode.CLIENT,
        description="Infrastructure mode: client, server, or both",
    )
    server_count: int = Field(
        default=1,
        ge=1,
        description="Number of server instances (only for SERVER/CLIENT_AND_SERVER modes)",
    )

    class Config:
        use_enum_values = True


class SettingsConfig(BaseModel):
    """Tier 2: Factorio game settings configuration.

    Handles scenarios, saves, and map generation settings.
    Key insight: Custom map settings (like peaceful mode) require
    generating a save first, then launching with that save.
    """

    scenario: Optional[str] = Field(
        default=None,
        description="Scenario to load (freeplay, test-ground, or task-specific). None launches to main menu.",
    )
    save_path: Optional[Path] = Field(
        default=None,
        description="Existing save file to load (overrides scenario if set)",
    )
    seed: Optional[int] = Field(
        default=None, description="World generation seed for reproducibility"
    )
    peaceful: bool = Field(
        default=True, description="Enable peaceful mode (requires save generation)"
    )
    map_gen_settings: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Custom map generation settings (requires save generation)",
    )

    @property
    def requires_save_generation(self) -> bool:
        """Check if settings require pre-generating a save file.

        Some settings can't be passed via CLI and require modifying
        map-settings.json and generating a save first.
        """
        # Peaceful mode and custom map settings require save generation
        return self.peaceful or self.map_gen_settings is not None


class PythonConfig(BaseModel):
    """Tier 3: Python infrastructure configuration."""

    instance: Optional[str] = Field(
        default=None, description="Instance name (client/server_N), auto-detect if None"
    )
    udp_enabled: bool = Field(
        default=True, description="Enable UDP listener for async notifications"
    )
    udp_port: Optional[int] = Field(
        default=None,
        description="UDP port for agent action notifications. If None, calculated from agent_id."
    )
    agent_id: str = Field(
        default="agent_1",
        description="Agent ID used to calculate UDP port when udp_port is None"
    )


class RuntimeConfig(BaseModel):
    """Tier 4: FactoryVerse runtime configuration."""

    variant: RuntimeVariant = Field(
        default=RuntimeVariant.FULL, description="Runtime variant (minimal or full)"
    )
    agent_id: str = Field(default="agent_1", description="Agent identifier")
    initial_inventory: Optional[Dict[str, int]] = Field(
        default=None,
        description="Initial inventory items to give agent on creation: {item_name: count, ...}",
    )
    access_profile: RuntimeAccessProfile = Field(
        default=RuntimeAccessProfile.DEBUG,
        description=(
            "Actor capability profile. Production omits raw RCON and admin "
            "objects from the execution namespace."
        ),
    )
    database_path: Optional[Path] = Field(
        default=None,
        description=(
            "Persistent DuckDB path used by RemoteView. None keeps the "
            "historical in-memory behavior."
        ),
    )
    session_dir: Optional[Path] = Field(
        default=None, description="Session directory (auto-created if None)"
    )
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.JUPYTER,
        description="Code execution mode (jupyter for notebook logging, inprocess for lightweight)",
    )
    kernel_name: str = Field(
        default="fv",
        description="Jupyter kernel name (only used when execution_mode=JUPYTER)",
    )
    # Session mode controls directory structure and artifacts
    session_mode: SessionMode = Field(
        default=SessionMode.LLM,
        description="Session mode: 'llm' for agent runs, 'eval' for evaluation, 'none' for testing",
    )
    task_name: Optional[str] = Field(
        default=None,
        description="Task name for eval sessions. Used in directory path: .fv-output/evals/{task_name}/{run_id}/",
    )
    # Session metadata for trajectory tracking (LLM mode only)
    provider: Optional[str] = Field(
        default=None,
        description="LLM provider for session organization (e.g., 'prime_intellect'). Used in session directory path.",
    )
    model: Optional[str] = Field(
        default=None,
        description="Model name for session organization (e.g., 'intellect-3'). Used in session directory path.",
    )
    mode: Optional[str] = Field(
        default=None,
        description="Agent mode ('assisted' or 'autonomous'). Stored in session metadata.",
    )

    class Config:
        use_enum_values = True


class SpecificationConfig(BaseModel):
    """Tier 5: Agent specification configuration."""

    include_api_reference: bool = Field(
        default=True, description="Include API reference in system prompt"
    )
    include_schema_reference: bool = Field(
        default=True, description="Include database schema in system prompt"
    )
    include_initial_state: bool = Field(
        default=True, description="Generate initial state summary showing agent's situation"
    )
    system_prompt_path: Optional[Path] = Field(
        default=None, description="Custom system prompt path (uses default if None)"
    )
    task_name: Optional[str] = Field(
        default=None, description="Task name for task-specific prompts"
    )


class InteractionConfig(BaseModel):
    """Tier 6: LLM interaction configuration."""

    mode: InteractionMode = Field(
        default=InteractionMode.AUTONOMOUS, description="Interaction mode"
    )
    llm_provider: str = Field(
        default="prime_intellect", description="LLM provider name"
    )
    model: str = Field(default="intellect-3", description="Model name/identifier")
    max_turns: Optional[int] = Field(
        default=None, description="Max turns (None for unlimited)"
    )
    max_context_tokens: int = Field(
        default=100000, description="Maximum context window tokens"
    )
    console_output_enabled: bool = Field(
        default=True,
        description="Enable console output streaming for agent thoughts/actions",
    )

    class Config:
        use_enum_values = True


class EnvironmentConfig(BaseModel):
    """Complete Environment configuration.

    Composes tier-specific configs with global FactoryVerseConfig.
    """

    tier1: InfraConfig = Field(default_factory=InfraConfig)
    tier2: SettingsConfig = Field(default_factory=SettingsConfig)
    tier3: PythonConfig = Field(default_factory=PythonConfig)
    tier4: RuntimeConfig = Field(default_factory=RuntimeConfig)
    tier5: SpecificationConfig = Field(default_factory=SpecificationConfig)
    tier6: InteractionConfig = Field(default_factory=InteractionConfig)

    # Global infrastructure config (ports, paths, etc.)
    _infra_config: Optional[FactoryVerseConfig] = None

    @property
    def infra_config(self) -> FactoryVerseConfig:
        """Get global infrastructure configuration."""
        if self._infra_config is None:
            self._infra_config = FactoryVerseConfig()
        return self._infra_config

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def for_run(
        cls,
        *,
        instance: str = "client",
        scenario: str = "freeplay",
        provider: str = "prime_intellect",
        model: Optional[str] = None,
        agent_id: str = "agent_1",
        max_turns: Optional[int] = None,
        task_name: Optional[str] = None,
        interactive: bool = False,
    ) -> "EnvironmentConfig":
        """The one place a full agent run (tiers 1–6) is assembled.

        ``task_name`` selects a verified eval (session under .fv-output/evals/);
        otherwise the run is freeplay (.fv-output/runs/). ``interactive`` puts
        tier 6 in assisted mode. A ``client`` instance is attached to, never
        owned; any other instance is treated as a Docker server.
        """
        if model is None:
            from FactoryVerse.infra.llm.client.factory import default_model_for_provider

            model = default_model_for_provider(provider) or "default"
        infra_mode = InfraMode.EXTERNAL if instance == "client" else InfraMode.SERVER
        mode = InteractionMode.ASSISTED if interactive else InteractionMode.AUTONOMOUS

        # FREEPLAY-INV-1: on a task run the starting kit is applied during cell
        # allocation, but a freeplay run allocates no cell (only the lab-grid
        # adapter is registered, and the inbuilt freeplay scenario does not
        # answer its interface), so `_allocate_cell` returns before it can
        # apply anything and the agent starts empty. Stock it at agent
        # creation instead. Freeplay only — setting it for a task run would
        # stock the agent twice.
        #
        # The kit is the vanilla freeplay starter, the same constant the
        # campaign supervisor uses, so an in-repo freeplay run and a campaign
        # freeplay run begin from the same state and their observations remain
        # comparable. It is deliberately NOT the lab throughput kit: handing a
        # freeplay agent hundreds of belts and poles would prejudge exactly the
        # transport-affordance behaviour these runs exist to observe.
        starting_inventory: Optional[Dict[str, int]] = None
        if task_name is None:
            from FactoryVerse.game.tasks.definitions.common import (
                FREEPLAY_STARTING_INVENTORY,
            )

            starting_inventory = dict(FREEPLAY_STARTING_INVENTORY)
        return cls(
            tier1=InfraConfig(mode=infra_mode),
            tier2=SettingsConfig(scenario=scenario),
            tier3=PythonConfig(instance=instance, agent_id=agent_id),
            tier4=RuntimeConfig(
                variant=RuntimeVariant.FULL,
                agent_id=agent_id,
                # An agent run is a production run: the actor gets embodied
                # interfaces and DuckDB, not raw RCON / runtime / scenario.
                # Stated explicitly so `fv run` and the freeplay campaign
                # supervisor draw the same affordance boundary; the field's
                # own default stays DEBUG for dev entry points.
                access_profile=RuntimeAccessProfile.PRODUCTION,
                initial_inventory=starting_inventory,
                provider=provider,
                model=model,
                mode=mode.value,
                session_mode=SessionMode.EVAL if task_name else SessionMode.LLM,
                task_name=task_name,
            ),
            tier5=SpecificationConfig(
                include_api_reference=True,
                include_schema_reference=True,
                include_initial_state=True,
                task_name=task_name,
            ),
            tier6=InteractionConfig(
                mode=mode,
                llm_provider=provider,
                model=model,
                max_turns=max_turns,
            ),
        )

    @classmethod
    def for_testing(
        cls,
        scenario: str = "test-ground",
        variant: RuntimeVariant = RuntimeVariant.MINIMAL,
        mode: InfraMode = InfraMode.SERVER,
    ) -> "EnvironmentConfig":
        """Create config for testing."""
        return cls(
            tier1=InfraConfig(mode=mode),
            tier2=SettingsConfig(scenario=scenario, peaceful=True),
            tier4=RuntimeConfig(variant=variant),
        )

