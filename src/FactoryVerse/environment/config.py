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

    CLIENT = "client"  # Manage client lifecycle
    SERVER = "server"  # Manage server lifecycle (Docker)
    CLIENT_AND_SERVER = "client_and_server"  # Manage both
    EXTERNAL = "external"  # Connect to pre-existing instance, don't manage lifecycle


class RuntimeVariant(str, Enum):
    """Runtime tier variant controlling loaded components."""

    MINIMAL = "minimal"  # No remote_view, no DuckDB
    FULL = "full"  # All agent modules including remote_view


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

    @classmethod
    def for_eval(
        cls,
        task_name: str,
        scenario: str = "test-ground",
        agent_id: str = "agent_1",
        initial_inventory: Optional[Dict[str, int]] = None,
    ) -> "EnvironmentConfig":
        """Create config for evaluation runs.

        Eval runs track trajectories and create notebooks for reproducibility,
        but skip LLM-specific artifacts (system_prompt, initial_state, chat).

        Session directory: .fv-output/evals/{task_name}/{run_id}/
        Artifacts created:
        - trajectory.jsonl (mechanistic source of truth)
        - notebook.ipynb (reproducibility)
        - config.json (task + environment config)
        - result.json (verification result, written by eval harness)

        Args:
            task_name: Task key for directory organization and verification
            scenario: Scenario to load (default: test-ground)
            agent_id: Agent identifier (default: agent_1)
            initial_inventory: Optional inventory override (task inventory used if None)

        Returns:
            EnvironmentConfig suitable for eval runs (initialize up to Tier 4 only)
        """
        return cls(
            tier2=SettingsConfig(scenario=scenario, peaceful=True),
            tier3=PythonConfig(agent_id=agent_id),
            tier4=RuntimeConfig(
                variant=RuntimeVariant.FULL,  # Need DuckDB for verification
                agent_id=agent_id,
                session_mode=SessionMode.EVAL,
                task_name=task_name,
                initial_inventory=initial_inventory,
                execution_mode=ExecutionMode.JUPYTER,  # Notebook for reproducibility
            ),
            # Tier 5 & 6 not configured - no LLM
        )
