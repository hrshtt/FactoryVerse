"""Centralized configuration for FactoryVerse runtime.

This module provides a multi-agent ready configuration system with:
- Global config (RCON connection, base paths) - shared across all agents
- Per-agent runtime config (UDP port, session dir, DB path) - unique per agent

Design supports multiple concurrent agents without modification.
"""
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


# Detect repo root once at module load
_REPO_ROOT = _find_repo_root()


class FactoryVerseConfig(BaseSettings):
    """Global configuration shared across all agents.
    
    Loaded from environment variables with .env file support.
    Only contains truly global settings (RCON connection, base paths).
    
    The .env file is automatically located at the repository root,
    regardless of current working directory.
    
    Example:
        >>> config = FactoryVerseConfig()
        >>> print(config.rcon_host)
        'localhost'
    """
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),  # Use absolute path
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # RCON connection (shared across all agents)
    rcon_host: str = Field(default="localhost", description="Factorio RCON host")
    rcon_port: int = Field(default=27100, description="Factorio RCON port")
    rcon_pwd: str = Field(default="factorio", description="RCON password")
    
    # Base paths (shared)
    factorio_script_output_dir: Optional[Path] = Field(
        default=None,
        description="Factorio script-output directory (auto-detected if None)"
    )
    
    factoryverse_dump_file: Optional[Path] = Field(
        default=None,
        description="Path to factorio-data-dump.json (defaults to repo root if None)"
    )
    
    # Port allocation
    agent_udp_port_start: int = Field(
        default=24389,
        description="Starting port for agent UDP port allocation"
    )
    
    def get_dump_file(self) -> Path:
        """Get factorio-data-dump.json path with auto-detection.
        
        Returns:
            Path to factorio-data-dump.json
            
        Raises:
            ValueError: If file not found and env var not set
        """
        if self.factoryverse_dump_file:
            dump_path = Path(self.factoryverse_dump_file)
            if dump_path.exists():
                return dump_path
            raise ValueError(f"Dump file not found: {dump_path}")
        
        # Auto-detect at repo root
        dump_path = _REPO_ROOT / "factorio-data-dump.json"
        if dump_path.exists():
            return dump_path
        
        raise ValueError(
            f"factorio-data-dump.json not found at {dump_path}\n"
            "Please set FACTORYVERSE_DUMP_FILE environment variable."
        )
    
    def get_script_output_dir(self) -> Path:
        """Get Factorio script-output directory with auto-detection.
        
        Returns:
            Path to Factorio's script-output directory
            
        Raises:
            ValueError: If auto-detection fails and env var not set
        """
        if self.factorio_script_output_dir:
            return Path(self.factorio_script_output_dir)
        
        # Auto-detect using existing infrastructure
        try:
            from FactoryVerse.infra.factorio_client_setup import get_client_script_output_dir
            return get_client_script_output_dir()
        except Exception as e:
            raise ValueError(
                f"Cannot auto-detect Factorio script-output directory: {e}\n"
                "Please set FACTORIO_SCRIPT_OUTPUT_DIR environment variable."
            )
    
    def get_snapshot_dir(self) -> Path:
        """Get snapshot directory (shared across all agents).
        
        Returns:
            Path to snapshot directory, creates if doesn't exist
        """
        script_output = self.get_script_output_dir()
        snapshot_dir = script_output / "factoryverse" / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        return snapshot_dir


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
        24389
        >>> print(config.db_path)
        /tmp/session1/map.duckdb
    """
    
    def __init__(
        self,
        session_dir: Path,
        agent_id: str = "agent_1",
        udp_port: Optional[int] = None,
        global_config: Optional[FactoryVerseConfig] = None
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
        # Future: Implement port registry for multi-agent
        self.udp_port = udp_port or self._allocate_udp_port()
        
        # Session-specific paths
        self.db_path = self.session_dir / "map.duckdb"
        self.snapshot_dir = self.global_config.get_snapshot_dir()
        
        # Ensure session directory exists
        self.session_dir.mkdir(parents=True, exist_ok=True)
    
    def _allocate_udp_port(self) -> int:
        """Allocate UDP port for this agent.
        
        Current: Use default starting port
        Future: Implement port registry to track used ports
                and auto-assign next available port
        
        Returns:
            Allocated UDP port number
        """
        return self.global_config.agent_udp_port_start
    
    @property
    def rcon_host(self) -> str:
        """RCON host (shared across all agents)."""
        return self.global_config.rcon_host
    
    @property
    def rcon_port(self) -> int:
        """RCON port (shared across all agents)."""
        return self.global_config.rcon_port
    
    @property
    def rcon_password(self) -> str:
        """RCON password (shared across all agents)."""
        return self.global_config.rcon_pwd


# Convenience function for single-agent scenarios
def get_runtime_config(
    session_dir: Path,
    agent_id: str = "agent_1",
    udp_port: Optional[int] = None
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
        session_dir=session_dir,
        agent_id=agent_id,
        udp_port=udp_port
    )
