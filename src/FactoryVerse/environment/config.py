"""Environment configuration dataclasses.

Composes with existing FactoryVerseConfig for infrastructure settings.
"""

from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field

from FactoryVerse.config import FactoryVerseConfig


class InfraMode(str, Enum):
    """Factorio infrastructure mode."""

    CLIENT = "client"
    SERVER = "server"
    CLIENT_AND_SERVER = "client_and_server"


class RuntimeVariant(str, Enum):
    """Runtime tier variant controlling loaded components."""

    MINIMAL = "minimal"  # No remote_view, no DuckDB
    FULL = "full"  # All agent modules including remote_view


class InteractionMode(str, Enum):
    """Agent interaction mode."""

    AUTONOMOUS = "autonomous"  # Continuous agent loop
    ASSISTED = "assisted"  # Single-turn interaction
    MCP = "mcp"  # MCP server mode


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

    scenario: str = Field(
        default="test-ground",
        description="Scenario to load (freeplay, test-ground, or task-specific)",
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
        default=None, description="UDP port (auto-allocated if None)"
    )


class RuntimeConfig(BaseModel):
    """Tier 4: FactoryVerse runtime configuration."""

    variant: RuntimeVariant = Field(
        default=RuntimeVariant.FULL, description="Runtime variant (minimal or full)"
    )
    agent_id: str = Field(default="agent_1", description="Agent identifier")
    session_dir: Optional[Path] = Field(
        default=None, description="Session directory (auto-created if None)"
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
    def for_agent(
        cls,
        mode: InteractionMode = InteractionMode.AUTONOMOUS,
        llm_provider: str = "prime_intellect",
        model: str = "intellect-3",
        scenario: str = "freeplay",
    ) -> "EnvironmentConfig":
        """Create config for agent runs."""
        return cls(
            tier2=SettingsConfig(scenario=scenario),
            tier4=RuntimeConfig(variant=RuntimeVariant.FULL),
            tier6=InteractionConfig(
                mode=mode,
                llm_provider=llm_provider,
                model=model,
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

    @classmethod
    def for_mcp(cls, instance: Optional[str] = None) -> "EnvironmentConfig":
        """Create config for MCP server."""
        return cls(
            tier3=PythonConfig(instance=instance),
            tier4=RuntimeConfig(variant=RuntimeVariant.FULL),
            tier6=InteractionConfig(mode=InteractionMode.MCP),
        )
