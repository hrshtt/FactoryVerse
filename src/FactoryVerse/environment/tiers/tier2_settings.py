"""Tier 2: Factorio Settings.

Orchestrates scenario loading, save file management, and map generation settings.

Key insight: Some settings (peaceful mode, resource generation) require
generating a save file first before launching - they cannot be set via CLI.
"""

import logging
import json
from pathlib import Path
from typing import Optional, Dict, Any, TYPE_CHECKING

from ..config import InfraMode, SettingsConfig
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

        # Validate scenario exists (if specified)
        scenario = self.config.scenario
        if scenario and not self.config.save_path:
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
        """Verify the map the server will create matches the requested settings.

        PEACEFUL-1. This used to write a two-key JSON file to the output
        directory and point ``_current_save`` at a zip it never created. The
        server never reads that path: it creates its map from
        ``server_config_dir/map-gen-settings.json``, which the container mounts
        and passes to ``--create``. So ``SettingsConfig.peaceful`` decided
        nothing, and a run could contradict the agent's own system prompt
        ("no enemies attack") with nothing anywhere reporting the mismatch.

        We do not write that file. It is checked in, it carries the full
        autoplace/cliff/terrain configuration, and silently rewriting tracked
        repo state during a run is worse than the bug. Instead the requested
        settings are checked against it and a mismatch fails the tier loudly,
        naming the file and the key. Silence is not evidence.
        """
        infra_config = self._env.config.infra_config
        requested = self._build_map_gen_settings()

        # Only a server-mode run creates its own map. An attached client is
        # already running whatever world it loaded; tier 2 cannot speak for it.
        if self._env.config.tier1.mode != InfraMode.SERVER:
            if self.config.peaceful:
                logger.warning(
                    "Tier 2: peaceful=True cannot be enforced on an attached "
                    "instance — the world comes from the save the client "
                    "already loaded. Verify it before trusting any claim "
                    "about enemies."
                )
            self._current_scenario = self.config.scenario
            self._current_save = None
            return

        settings_path = infra_config.server_config_dir / "map-gen-settings.json"
        if not settings_path.exists():
            raise TierInitializationError(
                self.tier_level,
                f"Map generation settings not found at {settings_path}. The "
                "server creates its map from this file; without it the "
                "requested settings cannot be honoured.",
            )

        mounted = json.loads(settings_path.read_text())
        mismatches = [
            f"{key}: requested {value!r}, file has {mounted.get(key)!r}"
            for key, value in requested.items()
            if not _settings_match(mounted.get(key), value)
        ]
        if mismatches:
            raise TierInitializationError(
                self.tier_level,
                "Requested map generation settings disagree with the file the "
                f"server builds its map from ({settings_path}): "
                + "; ".join(mismatches)
                + ". Edit that file, or change the request — do not launch a "
                "run whose world contradicts its own configuration.",
            )

        logger.info(
            f"Tier 2: Verified map generation settings against {settings_path} "
            f"({', '.join(f'{k}={v}' for k, v in requested.items()) or 'no constraints'})"
        )
        self._current_scenario = self.config.scenario
        self._current_save = None

    def _build_map_gen_settings(self) -> Dict[str, Any]:  # noqa: D401
        """Build the map generation settings this run requires.

        Keys must match Factorio's ``map-gen-settings.json`` schema exactly —
        this dict is compared against that file. ``peaceful_mode`` was
        previously written as ``peace_mode``, which the engine ignores.
        """
        settings: Dict[str, Any] = {}

        # "Peaceful" means a world with no enemy entities, not merely enemies
        # that do not attack. Measured (SCENARIO_BOOT_CONTRACT §4): only the
        # zeroed enemy-base autoplace empties the world; no_enemies_mode
        # closes later spawning; peaceful_mode is the backstop.
        if self.config.peaceful:
            settings["peaceful_mode"] = True
            settings["no_enemies_mode"] = True
            settings["autoplace_controls"] = {
                "enemy-base": {"frequency": 0, "size": 0, "richness": 0}
            }

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


def _settings_match(mounted: Any, requested: Any) -> bool:
    """A requested value matches when the file carries it; dicts match as subsets.

    ``autoplace_controls`` in the file lists every control; the request only
    constrains ``enemy-base``. Numbers compare by value so ``0`` and ``0.0``
    agree.
    """
    if isinstance(requested, dict):
        if not isinstance(mounted, dict):
            return False
        return all(_settings_match(mounted.get(k), v) for k, v in requested.items())
    if isinstance(requested, (int, float)) and isinstance(mounted, (int, float)) \
            and not isinstance(requested, bool) and not isinstance(mounted, bool):
        return float(mounted) == float(requested)
    return mounted == requested
