"""Tier 2: Factorio Settings.

Orchestrates scenario loading, save file management, and map generation settings.

Key insight: Some settings (peaceful mode, resource generation) require
generating a save file first before launching - they cannot be set via CLI.
"""

import logging
import json
from pathlib import Path
from typing import Optional, Dict, Any, TYPE_CHECKING

from ..config import SettingsConfig
from ..status import Tier2Status, TierState, PrerequisiteResult
from .base import TierBase, Tier, TierInitializationError

if TYPE_CHECKING:
    from ..environment import Environment

logger = logging.getLogger(__name__)


class Tier2Settings(TierBase):
    """Tier 2: Factorio Settings.

    Manages scenario selection, save file loading, and map generation settings.

    Scenario-Task Coupling:
    - freeplay: Base building, general gameplay
    - test-ground: Testing and development
    - lab: Task-specific controlled environment (future)
    - Custom scenarios: Coupled to specific tasks

    Map Settings Workflow:
    When custom map settings (peaceful mode, resource settings) are needed:
    1. Write settings to map-gen-settings.json
    2. Generate a save from scenario with those settings
    3. Launch with the generated save
    """

    tier_level = Tier.SETTINGS

    def __init__(self, environment: "Environment"):
        super().__init__(environment)
        self._current_scenario: Optional[str] = None
        self._current_save: Optional[Path] = None
        self._game_loaded: bool = False
        self._game_tick: int = 0

    @property
    def config(self) -> SettingsConfig:
        """Get tier 2 configuration."""
        return self._env.config.tier2

    @property
    def current_scenario(self) -> Optional[str]:
        """Currently loaded scenario name."""
        return self._current_scenario

    @property
    def current_save(self) -> Optional[Path]:
        """Currently loaded save file path."""
        return self._current_save

    async def verify_prerequisites(self) -> PrerequisiteResult:
        """Verify Tier 1 (Factorio Infra) is ready."""
        tier1 = self._env.tier1

        if tier1 is None or not tier1.is_ready:
            return PrerequisiteResult.failed(
                missing=["tier1_factorio_infra"],
                message="Factorio infrastructure must be initialized first",
            )

        # Validate scenario exists
        scenario = self.config.scenario
        if not self.config.save_path:
            # Only validate scenario if not using a save file
            if not self._validate_scenario(scenario):
                return PrerequisiteResult.failed(
                    missing=[f"scenario_{scenario}"],
                    message=f"Scenario '{scenario}' not found",
                )

        return PrerequisiteResult.ok()

    async def initialize(self) -> None:
        """Initialize settings and optionally generate save with custom settings.

        If custom map settings are required (peaceful mode, etc.):
        1. Generate map-gen-settings.json
        2. Create a save file with those settings
        3. Store the save path for tier 1 to use when starting
        """
        self._set_state(TierState.INITIALIZING)

        try:
            if self.config.save_path:
                # Use existing save file
                self._current_save = self.config.save_path
                self._current_scenario = None
                logger.info(f"Tier 2: Using save file {self._current_save}")

            elif self.config.requires_save_generation:
                # Generate save with custom settings
                await self._generate_save_with_settings()
                logger.info("Tier 2: Generated save with custom settings")

                self._current_scenario = self.config.scenario
                self._current_save = None
                logger.info(f"Tier 2: Using scenario {self._current_scenario}")

            # Start Factorio instance via Tier 1
            await self._start_factorio_instance()

            self._set_state(TierState.READY)

        except Exception as e:
            self._set_state(TierState.ERROR, str(e))
            raise TierInitializationError(self.tier_level, str(e)) from e

    async def verify_ready(self) -> Tier2Status:
        """Verify settings are loaded and game is in playable state."""
        if self._state != TierState.READY:
            return Tier2Status(
                state=self._state,
                error=self._error,
            )

        return Tier2Status(
            state=self._state,
            game_loaded=self._game_loaded,
            scenario_name=self._current_scenario,
            tick=self._game_tick,
        )

    async def reset(self) -> None:
        """Reset by reloading scenario/save."""
        self._set_state(TierState.INITIALIZING)
        self._game_loaded = False
        self._game_tick = 0
        await self.initialize()

    async def shutdown(self) -> None:
        """Cleanup settings state."""
        self._current_scenario = None
        self._current_save = None
        self._game_loaded = False
        self._game_tick = 0
        self._set_state(TierState.SHUTDOWN)

    # =========================================================================
    # Game State Methods (called by higher tiers)
    # =========================================================================

    def mark_game_loaded(self, tick: int = 0) -> None:
        """Mark game as loaded (called after successful RCON connection).

        Args:
            tick: Current game tick
        """
        self._game_loaded = True
        self._game_tick = tick

    def update_tick(self, tick: int) -> None:
        """Update current game tick."""
        self._game_tick = tick

    # =========================================================================
    # Scenario/Save Methods
    # =========================================================================

    def list_scenarios(self, include_local: bool = True) -> list[str]:
        """List available scenarios."""
        return self._env.config.infra_config.list_scenarios(include_local)

    def get_scenario_source(self, scenario: str) -> Optional[Path]:
        """Get source path for a scenario."""
        return self._env.config.infra_config.get_scenario_source(scenario)

    def is_repo_scenario(self, scenario: str) -> bool:
        """Check if scenario is from repo (hot-reloadable)."""
        return self._env.config.infra_config.is_repo_scenario(scenario)

    # =========================================================================
    # Map Generation Settings
    # =========================================================================

    async def _generate_save_with_settings(self) -> None:
        """Generate a save file with custom map settings.

        This handles settings that cannot be passed via CLI:
        - Peaceful mode
        - Resource generation settings
        - Enemy evolution settings
        """
        infra_config = self._env.config.infra_config

        # Prepare map generation settings
        map_gen = self._build_map_gen_settings()

        # Write to temporary map-gen-settings.json
        output_dir = infra_config.fv_output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        settings_path = output_dir / "map-gen-settings.json"
        with open(settings_path, "w") as f:
            json.dump(map_gen, f, indent=2)

        # Generate save filename
        scenario = self.config.scenario
        seed = self.config.seed or infra_config.map_gen_seed
        save_name = f"{scenario}_seed{seed}"
        if self.config.peaceful:
            save_name += "_peaceful"

        save_path = output_dir / "saves" / f"{save_name}.zip"
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # NOTE: Actual save generation would require running Factorio
        # with --create <save> --map-gen-settings <path>
        # For now, we just set up the paths - the client/server will
        # need to generate the save on first run if it doesn't exist

        self._current_save = save_path
        self._current_scenario = scenario  # Keep track of source scenario

        logger.info(f"Tier 2: Prepared settings for save {save_path}")

    def _build_map_gen_settings(self) -> Dict[str, Any]:
        """Build map generation settings dictionary."""
        settings: Dict[str, Any] = {}

        # Peaceful mode
        if self.config.peaceful:
            settings["peace_mode"] = True

        # Seed
        if self.config.seed is not None:
            settings["seed"] = self.config.seed
        elif self._env.config.infra_config.map_gen_seed:
            settings["seed"] = self._env.config.infra_config.map_gen_seed

        # Additional custom settings
        if self.config.map_gen_settings:
            settings.update(self.config.map_gen_settings)

        return settings

    def _validate_scenario(self, scenario: str) -> bool:
        """Check if scenario exists."""
        return self._env.config.infra_config.validate_scenario(scenario)

    # =========================================================================
    # Launch Configuration
    # =========================================================================

    def get_launch_args(self) -> Dict[str, Any]:
        """Get arguments for launching Factorio with current settings.

        Returns dict suitable for passing to tier1.start_client/start_server.
        """
        args: Dict[str, Any] = {}

        if self._current_save and self._current_save.exists():
            args["save_path"] = self._current_save
        elif self._current_scenario:
            args["scenario"] = self._current_scenario

        return args

    async def _start_factorio_instance(self) -> None:
        """Start Factorio instance using Tier 1."""
        tier1 = self._env.tier1
        if not tier1:
            raise RuntimeError("Tier 1 not initialized")

        from ..config import InfraMode

        infra_mode = tier1.config.mode

        launch_args = self.get_launch_args()

        if infra_mode in (InfraMode.SERVER, InfraMode.CLIENT_AND_SERVER):
            # Start server(s)
            scenario = self._current_scenario or "test-ground"  # Fallback
            await tier1.start_server(
                scenario=scenario, num_instances=tier1.config.server_count
            )
            logger.info("Tier 2: Started Factorio server(s)")

        elif infra_mode == InfraMode.CLIENT:
            # Start client
            await tier1.start_client(**launch_args)
            logger.info("Tier 2: Started Factorio client")
