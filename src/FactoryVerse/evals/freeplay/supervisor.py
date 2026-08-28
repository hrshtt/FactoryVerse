"""Trusted freeplay campaign provisioning, preflight, and finalization."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from FactoryVerse.environment import Environment, Tier
from FactoryVerse.game.tasks.definitions.common import FREEPLAY_STARTING_INVENTORY
from FactoryVerse.environment.boot_probe import boot_errors, probe_boot
from FactoryVerse.environment.config import (
    EnvironmentConfig,
    ExecutionMode,
    FactoryVerseConfig,
    InfraConfig,
    InfraMode,
    PythonConfig,
    RuntimeAccessProfile,
    RuntimeConfig,
    RuntimeVariant,
    SessionMode,
    SettingsConfig,
)
from FactoryVerse.infra.docker.docker_compose_manager import DockerComposeManager
from FactoryVerse.infra.docker.factorio_server_manager import (
    factoryverse_server_mod_list,
)
from FactoryVerse.infra.instance_manager import FactorioInstanceManager

from .campaign import CampaignLease, CampaignStateError, FreeplayCampaignStore
from .checkpoint import FreeplayCheckpointService
from .models import CampaignStatus, RuntimeSessionRecord, utc_now
from .provenance import (
    canonical_json_sha256,
    repository_provenance,
    sha256_file,
    sha256_tree,
)


class FreeplayLaunchError(RuntimeError):
    pass



# Freeplay evaluations intentionally run faster than wall-clock simulation.
# Pin this in every campaign manifest and verify the live engine value during
# preflight so evaluation timing cannot silently vary between runs.
FREEPLAY_GAME_SPEED = 8

# Every added item is an unprocessed world resource. Quantities cover 50
# plates of each metal plus one lab's intermediates with recovery margin.
NOTIFICATION_DEBUG_RAW_INVENTORY: Dict[str, int] = {
    "iron-ore": 120,
    "copper-ore": 80,
    "coal": 80,
    "stone": 50,
}

# Focused affordance validation should not depend on unrelated research or
# production milestones. Supply only the finite items needed to exercise the
# public water-search, pump-placement, and fluid-connection path.
OFFSHORE_PUMP_DEBUG_INVENTORY: Dict[str, int] = {
    "offshore-pump": 1,
    "pipe": 4,
}


def _mod_identity(source: Path) -> tuple[str, str]:
    info = json.loads((source / "info.json").read_text(encoding="utf-8"))
    return str(info["name"]), str(info["version"])


def _expected_active_mods(infra_config: FactoryVerseConfig) -> Dict[str, str]:
    """Return the exact mod/version set allowed in a freeplay campaign."""
    image_tag = infra_config.docker_image.rsplit(":", 1)[-1]
    expected = {"base": image_tag}
    for source in (
        infra_config.embodied_agent_mod_dir,
        infra_config.snapshot_mod_dir,
        infra_config.placement_hints_mod_dir,
    ):
        name, version = _mod_identity(source)
        expected[name] = version
    return expected


def _freeplay_map_settings(source: Path, seed: int) -> Dict[str, Any]:
    settings = json.loads(source.read_text(encoding="utf-8"))
    settings["seed"] = seed
    settings["peaceful_mode"] = True
    controls = settings.setdefault("autoplace_controls", {})
    controls["enemy-base"] = {"frequency": 0, "size": 0, "richness": 0}
    return settings


def _freeplay_runtime_config(
    *, manifest: Dict[str, Any], session_dir: Path
) -> RuntimeConfig:
    """Build the production runtime for one dedicated freeplay agent.

    Script-created agent characters do not receive base/freeplay's
    ``on_player_created`` starter items because they are not LuaPlayer
    instances. Mirror the human freeplay starter kit explicitly when Tier 4
    creates the agent. Tier 4 only consumes this inventory on CREATE/RECREATE;
    binding to an agent restored from a checkpoint does not replenish it.
    """
    return RuntimeConfig(
        variant=RuntimeVariant.FULL,
        agent_id=manifest["agent_id"],
        initial_inventory=dict(
            manifest.get("initial_inventory", FREEPLAY_STARTING_INVENTORY)
        ),
        access_profile=RuntimeAccessProfile.PRODUCTION,
        database_path=session_dir / "runtime.duckdb",
        session_dir=session_dir,
        execution_mode=ExecutionMode.JUPYTER,
        session_mode=SessionMode.EVAL,
        task_name=f"freeplay:{manifest['campaign_id']}",
    )


def build_campaign_manifest(
    *,
    repo_root: Path,
    infra_config: FactoryVerseConfig,
    seed: int,
    agent_id: str,
    harness: str,
    model: str,
    harness_configuration: Optional[Dict[str, Any]] = None,
    initial_inventory: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    map_settings_path = infra_config.server_config_dir / "map-gen-settings.json"
    map_settings = _freeplay_map_settings(map_settings_path, seed)
    api_reference = repo_root / "docs" / "for-llms" / "api_reference.md"
    schema_reference = repo_root / "docs" / "for-llms" / "schema_reference.md"
    if not infra_config.data_dump_path.exists():
        raise FreeplayLaunchError(
            f"Missing Factorio prototype dump: {infra_config.data_dump_path}. "
            "Run 'fv data refresh' before creating a campaign."
        )
    if not infra_config.prototype_api_path.exists():
        raise FreeplayLaunchError(
            f"Missing Factorio prototype API: {infra_config.prototype_api_path}. "
            "Run 'fv data refresh-api' before creating a campaign."
        )
    return {
        "evaluation_unit": "freeplay_campaign",
        "scenario": "freeplay",
        "seed": seed,
        "agent_id": agent_id,
        "harness": harness,
        "model": model,
        "harness_configuration": harness_configuration or {},
        "initial_inventory": dict(
            initial_inventory or FREEPLAY_STARTING_INVENTORY
        ),
        "clock_policy": "continuous_simulation",
        "game_speed": FREEPLAY_GAME_SPEED,
        "enemies_enabled": False,
        "instance": "server_0",
        "capability_profile": RuntimeAccessProfile.PRODUCTION.value,
        "factorio_image": infra_config.docker_image,
        "expected_active_mods": _expected_active_mods(infra_config),
        "repository": repository_provenance(repo_root),
        "hashes": {
            "map_gen_settings": canonical_json_sha256(map_settings),
            # The scenario script is part of the world; a boot proves it
            # loaded this one through its contract interface (boot_probe).
            "scenario": sha256_tree(infra_config.scenarios_dir / "freeplay"),
            "embodied_mod": sha256_tree(infra_config.embodied_agent_mod_dir),
            "snapshot_mod": sha256_tree(infra_config.snapshot_mod_dir),
            "placement_hints_mod": sha256_tree(
                infra_config.placement_hints_mod_dir
            ),
            "server_mod_list": canonical_json_sha256(
                factoryverse_server_mod_list()
            ),
            "api_reference": sha256_file(api_reference),
            "schema_reference": sha256_file(schema_reference),
            "tier4_runtime": sha256_file(
                repo_root / "src" / "FactoryVerse" / "environment" / "tiers" / "tier4_runtime.py"
            ),
            "factorio_data_dump": sha256_file(infra_config.data_dump_path),
            "factorio_prototype_api": sha256_file(infra_config.prototype_api_path),
        },
        "documentation": {
            "api_reference": str(api_reference.resolve()),
            "schema_reference": str(schema_reference.resolve()),
        },
        "isolation_class": "dedicated_factorio_cooperative_python",
        "limitations": [
            "Production namespace omits raw RCON, but Python is not yet an adversarial sandbox.",
            "The runtime protocol records code and outputs; full model reasoning remains harness-owned.",
        ],
    }


class FreeplaySupervisor:
    """Owns exactly one dedicated Factorio server and one runtime lease."""

    def __init__(
        self,
        store: FreeplayCampaignStore,
        *,
        repo_root: Path,
        harness: str,
        model: str,
    ):
        self.store = store
        self.repo_root = Path(repo_root)
        self.harness = harness
        self.model = model
        self.environment: Optional[Environment] = None
        self.checkpoints: Optional[FreeplayCheckpointService] = None
        self.session_id: Optional[str] = None
        self._lease: Optional[CampaignLease] = None
        self._finished = False

    @classmethod
    def create_campaign(
        cls,
        store: FreeplayCampaignStore,
        *,
        repo_root: Path,
        infra_config: FactoryVerseConfig,
        seed: int,
        agent_id: str,
        harness: str,
        model: str,
        harness_configuration: Optional[Dict[str, Any]] = None,
        initial_inventory: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        manifest = build_campaign_manifest(
            repo_root=repo_root,
            infra_config=infra_config,
            seed=seed,
            agent_id=agent_id,
            harness=harness,
            model=model,
            harness_configuration=harness_configuration,
            initial_inventory=initial_inventory,
        )
        document = store.create(manifest)
        cls._prepare_server_config(store, infra_config, seed)
        cls._prepare_static_data(store, infra_config)
        return document

    @staticmethod
    def _prepare_server_config(
        store: FreeplayCampaignStore,
        infra_config: FactoryVerseConfig,
        seed: int,
    ) -> None:
        source = infra_config.server_config_dir
        destination = store.paths.server_config
        destination.mkdir(parents=True, exist_ok=True)
        for path in source.iterdir():
            if path.is_file():
                shutil.copy2(path, destination / path.name)
        settings = _freeplay_map_settings(source / "map-gen-settings.json", seed)
        (destination / "map-gen-settings.json").write_text(
            json.dumps(settings, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _prepare_static_data(
        store: FreeplayCampaignStore,
        infra_config: FactoryVerseConfig,
    ) -> None:
        """Copy immutable prototype inputs into the isolated campaign root."""
        store.paths.server_output.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            infra_config.data_dump_path,
            store.paths.server_output / "factorio-data-dump.json",
        )
        shutil.copy2(
            infra_config.prototype_api_path,
            store.paths.server_output / "prototype-api.json",
        )

    async def start(self, resume: Optional[str] = None) -> Dict[str, Any]:
        manifest = self.store.manifest()
        if self.harness != manifest["harness"] or self.model != manifest["model"]:
            raise FreeplayLaunchError(
                "Harness/model identity differs from the immutable campaign manifest "
                f"(expected {manifest['harness']!r}/{manifest['model']!r}, got "
                f"{self.harness!r}/{self.model!r})"
            )
        current_repository = repository_provenance(self.repo_root)
        if current_repository != manifest.get("repository"):
            raise FreeplayLaunchError(
                "Repository provenance differs from the immutable campaign manifest; "
                "create a new campaign for this source tree"
            )
        records = self.store.checkpoint_records()
        if resume is None and records:
            resume = "latest"
        if resume is not None and not records:
            raise CampaignStateError("Cannot resume a campaign with no checkpoints")

        checkpoint = self.store.resolve_checkpoint(resume) if resume else None
        self.session_id = f"session-{utc_now().replace(':', '').replace('+00:00', 'Z')}-{uuid.uuid4().hex[:8]}"
        self._lease = self.store.lease(self.session_id).acquire()

        allowed = {CampaignStatus.DEFINED, CampaignStatus.PAUSED}
        try:
            self.store.transition(
                CampaignStatus.PROVISIONING,
                expected=allowed,
                active_session_id=self.session_id,
                invalid_reason=None,
            )
        except Exception:
            self._release_lease()
            raise

        session_dir = self.store.paths.sessions / self.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        record = RuntimeSessionRecord(
            session_id=self.session_id,
            actor_id=manifest["agent_id"],
            started_at=utc_now(),
            access_profile=RuntimeAccessProfile.PRODUCTION.value,
            harness=self.harness,
            model=self.model,
            resume_checkpoint_id=(checkpoint["checkpoint_id"] if checkpoint else None),
        )
        self.store.start_session(record)

        infra = FactoryVerseConfig(
            output_dir=self.store.paths.server_output,
            map_gen_seed=int(manifest["seed"]),
        )
        if FactorioInstanceManager.get_server(0, infra).test_connection():
            await self.invalidate(
                "RCON port for server_0 is already active; dedicated ownership cannot be proven"
            )
            self._release_lease()
            raise FreeplayLaunchError(
                "server_0 is already active. Stop it before launching a dedicated freeplay campaign."
            )

        actual_map_settings = json.loads(
            (self.store.paths.server_config / "map-gen-settings.json").read_text(
                encoding="utf-8"
            )
        )
        if canonical_json_sha256(actual_map_settings) != manifest["hashes"][
            "map_gen_settings"
        ]:
            await self.invalidate("Campaign map-gen-settings hash does not match manifest")
            self._release_lease()
            raise FreeplayLaunchError(
                "Campaign map-gen-settings changed after manifest creation"
            )

        save_name: Optional[str] = None
        if checkpoint:
            source_save = Path(checkpoint["save_path"])
            if not source_save.exists():
                await self.invalidate(f"Checkpoint save is missing: {source_save}")
                self._release_lease()
                raise FreeplayLaunchError(f"Checkpoint save is missing: {source_save}")
            if sha256_file(source_save) != checkpoint["save_sha256"]:
                await self.invalidate(f"Checkpoint save hash mismatch: {source_save}")
                self._release_lease()
                raise FreeplayLaunchError("Checkpoint save hash mismatch")
            save_name = checkpoint["save_name"]
            saves_dir = infra.get_server_output_dir(0) / "saves"
            saves_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_save, saves_dir / f"{save_name}.zip")

        env_config = EnvironmentConfig(
            tier1=InfraConfig(mode=InfraMode.SERVER, server_count=1),
            tier2=SettingsConfig(
                scenario="freeplay",
                seed=int(manifest["seed"]),
                peaceful=False,
            ),
            tier3=PythonConfig(instance="server_0", agent_id=manifest["agent_id"]),
            tier4=_freeplay_runtime_config(
                manifest=manifest,
                session_dir=session_dir,
            ),
        )
        env_config._infra_config = infra
        self.environment = Environment(config=env_config)

        try:
            await self.environment.initialize(up_to=Tier.FACTORIO_INFRA)
            tier1 = self.environment.tier1
            if tier1 is None or tier1.server_manager is None:
                raise FreeplayLaunchError("Tier 1 server manager did not initialize")

            tier1.server_manager.config_dir = self.store.paths.server_config
            tier1.server_manager.mod_path = self.store.paths.server_mods
            tier1.server_manager.isolated_mods = True
            tier1.server_manager.prepare_mods("freeplay")
            self._verify_server_mod_bundle(manifest)
            tier1._docker_compose_manager = DockerComposeManager(
                work_dir=self.repo_root,
                compose_path=self.store.paths.compose,
            )
            await tier1.start_server(
                scenario="freeplay",
                num_instances=1,
                save=save_name,
                prepare_mods=False,
            )
            self.store.transition(
                CampaignStatus.PREFLIGHT,
                expected={CampaignStatus.PROVISIONING},
            )
            # Checkpoint saves are deliberately captured with ticks paused so
            # the native save and DuckDB evidence describe one boundary. A
            # resumed server therefore needs to be unpaused before Tier 4 waits
            # for snapshot bootstrap/live sync.
            await self.environment.initialize(up_to=Tier.PYTHON_INFRA)
            if self.environment.tier3 is None:
                raise FreeplayLaunchError("Tier 3 did not initialize")
            game_speed = manifest.get("game_speed", FREEPLAY_GAME_SPEED)
            if game_speed != FREEPLAY_GAME_SPEED:
                raise FreeplayLaunchError(
                    "Freeplay campaign game speed differs from the required "
                    f"value {FREEPLAY_GAME_SPEED}: {game_speed!r}"
                )
            self.environment.tier3.run_lua(
                f"game.tick_paused = false; game.speed = {FREEPLAY_GAME_SPEED}; "
                "return true",
                safe=True,
                silent=True,
            )
            active_mods = self._read_active_mods()
            active_mod_errors = self._active_mod_errors(active_mods)
            if active_mod_errors:
                raise FreeplayLaunchError(
                    "Freeplay active-mod preflight failed: "
                    + "; ".join(active_mod_errors)
                )
            await self.environment.initialize(up_to=Tier.RUNTIME)
            preflight = await self._preflight(checkpoint, active_mods=active_mods)
            (session_dir / "preflight.json").write_text(
                json.dumps(preflight, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if not preflight["valid"]:
                raise FreeplayLaunchError(
                    "Freeplay preflight failed: " + "; ".join(preflight["errors"])
                )

            self.store.transition(
                CampaignStatus.READY,
                expected={CampaignStatus.PREFLIGHT},
            )
            self.store.transition(
                CampaignStatus.LEASED,
                expected={CampaignStatus.READY},
            )
            self.store.transition(
                CampaignStatus.RUNNING,
                expected={CampaignStatus.LEASED},
            )
            self.store.update_session(
                self.session_id,
                status="running",
                actor_id=self.environment.tier4.agent_id,
                last_game_tick=preflight["game_tick"],
                metadata={"preflight": preflight},
            )
            self.checkpoints = FreeplayCheckpointService(self.store, self.environment)
            return preflight
        except Exception as exc:
            self._capture_server_diagnostics(exc)
            await self.invalidate(str(exc))
            await self._shutdown_environment()
            self._release_lease()
            raise

    def _capture_server_diagnostics(self, error: Exception) -> None:
        """Persist Compose/Factorio diagnostics before owned teardown."""
        if self.environment is None or self.environment.tier1 is None:
            return
        manager = self.environment.tier1._docker_compose_manager
        if manager is None:
            return
        diagnostics_dir = self.store.paths.root / "diagnostics"
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        try:
            (diagnostics_dir / "compose-ps.json").write_text(
                json.dumps(manager.ps(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (diagnostics_dir / "server-logs.txt").write_text(
                manager.capture_logs(), encoding="utf-8"
            )
            (diagnostics_dir / "failure.json").write_text(
                json.dumps(
                    {
                        "captured_at": utc_now(),
                        "error_type": type(error).__name__,
                        "error": str(error),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        except Exception:
            pass

    def _verify_server_mod_bundle(self, manifest: Dict[str, Any]) -> None:
        """Verify copied server inputs before Docker can consume them."""
        hashes = manifest["hashes"]
        mod_list_path = self.store.paths.server_mods / "mod-list.json"
        trusted_copy = self.store.paths.server_config / "server-mod-list.json"
        expected_mod_list_hash = hashes["server_mod_list"]
        for path in (mod_list_path, trusted_copy):
            if not path.exists():
                raise FreeplayLaunchError(f"Campaign server mod list is missing: {path}")
            actual = canonical_json_sha256(
                json.loads(path.read_text(encoding="utf-8"))
            )
            if actual != expected_mod_list_hash:
                raise FreeplayLaunchError(
                    f"Campaign server mod list differs from manifest: {path}"
                )

        expected_mod_hashes = {
            "fv_embodied_agent": hashes["embodied_mod"],
            "fv_snapshot": hashes["snapshot_mod"],
            "fv_placement_hints": hashes["placement_hints_mod"],
        }
        expected_versions = manifest["expected_active_mods"]
        for name, expected_hash in expected_mod_hashes.items():
            path = self.store.paths.server_mods / f"{name}_{expected_versions[name]}"
            if not path.is_dir():
                raise FreeplayLaunchError(f"Campaign server mod is missing: {path}")
            if sha256_tree(path) != expected_hash:
                raise FreeplayLaunchError(
                    f"Campaign server mod bytes differ from manifest: {name}"
                )

    def _read_active_mods(self) -> Dict[str, str]:
        if self.environment is None or self.environment.tier3 is None:
            raise FreeplayLaunchError("Tier 3 unavailable during mod preflight")
        result = self.environment.tier3.run_lua(
            """
            local mods = {}
            for name, version in pairs(script.active_mods) do
                mods[name] = version
            end
            return mods
            """
        )
        if not isinstance(result, dict):
            raise FreeplayLaunchError("Factorio did not return an active mod map")
        return {str(name): str(version) for name, version in result.items()}

    def _active_mod_errors(self, active_mods: Dict[str, str]) -> list[str]:
        expected = self.store.manifest().get("expected_active_mods")
        if not isinstance(expected, dict):
            return ["campaign manifest has no expected active-mod set"]
        expected = {str(name): str(version) for name, version in expected.items()}
        if active_mods == expected:
            return []
        unexpected = sorted(set(active_mods) - set(expected))
        missing = sorted(set(expected) - set(active_mods))
        wrong_versions = sorted(
            name
            for name in set(active_mods) & set(expected)
            if active_mods[name] != expected[name]
        )
        details = []
        if unexpected:
            details.append(f"unexpected active mods: {', '.join(unexpected)}")
        if missing:
            details.append(f"missing active mods: {', '.join(missing)}")
        if wrong_versions:
            details.append(
                "active mod version mismatch: "
                + ", ".join(
                    f"{name}={active_mods[name]} (expected {expected[name]})"
                    for name in wrong_versions
                )
            )
        return details or ["active mod set differs from campaign manifest"]

    async def _preflight(
        self,
        checkpoint: Optional[Dict[str, Any]],
        *,
        active_mods: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if self.environment is None or self.environment.tier3 is None:
            raise FreeplayLaunchError("Tier 3 unavailable during preflight")
        tier3 = self.environment.tier3
        tier4 = self.environment.tier4
        if tier4 is None or tier4.remote_view is None:
            raise FreeplayLaunchError("Tier 4 RemoteView unavailable during preflight")

        agent_interface = json.dumps(str(self.store.manifest()["agent_id"]))
        engine = tier3.run_lua(
            """
            local surface = game.surfaces[1]
            local control = surface.map_gen_settings.autoplace_controls["enemy-base"]
            local agent_interface = __AGENT_INTERFACE__
            local actor_position = remote.call(agent_interface, "get_position")
            local actor_inventory = remote.call(agent_interface, "get_inventory_items")
            local researched_technology_count = 0
            for _, technology in pairs(game.forces.player.technologies) do
                if technology.researched then
                    researched_technology_count = researched_technology_count + 1
                end
            end
            local enemy_force_entity_count = 0
            local hostile_combat_entity_count = 0
            for _, candidate_surface in pairs(game.surfaces) do
                enemy_force_entity_count = enemy_force_entity_count
                    + candidate_surface.count_entities_filtered{force="enemy"}
                hostile_combat_entity_count = hostile_combat_entity_count
                    + candidate_surface.count_entities_filtered{
                        force="enemy",
                        type={"unit", "unit-spawner", "turret"}
                    }
            end
            return {
                tick = game.tick,
                tick_paused = game.tick_paused,
                game_speed = game.speed,
                enemy_base_frequency = control and control.frequency or nil,
                enemy_base_size = control and control.size or nil,
                no_enemies_mode = surface.map_gen_settings.no_enemies_mode,
                peaceful_mode = surface.map_gen_settings.peaceful_mode,
                enemy_force_entity_count = enemy_force_entity_count,
                hostile_combat_entity_count = hostile_combat_entity_count,
                enemy_entity_present = hostile_combat_entity_count > 0,
                actor_position = actor_position,
                actor_inventory = actor_inventory,
                researched_technology_count = researched_technology_count
            }
            """.replace("__AGENT_INTERFACE__", agent_interface)
        )
        boot = probe_boot(tier3)
        fingerprint = tier4.remote_view.state_fingerprint()
        sync = tier4.remote_view.sync_state
        perception_row = tier4.remote_view.execute_raw(
            """
            SELECT
                (SELECT count(*) FROM chunk_snapshot_meta),
                (SELECT count(*) FROM resource_entity),
                (SELECT count(*) FROM resource_tile),
                (SELECT count(*) FROM water_tile)
            """
        )[0]
        perception = {
            "snapshotted_chunks": int(perception_row[0]),
            "resource_entities": int(perception_row[1]),
            "resource_tiles": int(perception_row[2]),
            "water_tiles": int(perception_row[3]),
        }
        actor_position = engine.get("actor_position") or {"x": 0, "y": 0}
        actor_x = float(actor_position.get("x", 0))
        actor_y = float(actor_position.get("y", 0))
        resource_rows = tier4.remote_view.execute_raw(
            f"""
            SELECT name, position_x + 0.5, position_y + 0.5, amount
            FROM resource_tile
            WHERE name IN ('iron-ore', 'copper-ore', 'coal', 'stone')
            QUALIFY row_number() OVER (
                PARTITION BY name
                ORDER BY power(position_x + 0.5 - {actor_x}, 2)
                       + power(position_y + 0.5 - {actor_y}, 2)
            ) = 1
            ORDER BY name
            """
        )
        nearest_resources = {
            str(row[0]): {
                "position": {"x": float(row[1]), "y": float(row[2])},
                "amount": int(row[3]) if row[3] is not None else None,
            }
            for row in resource_rows
        }
        water_rows = tier4.remote_view.execute_raw(
            f"""
            SELECT position_x, position_y
            FROM water_tile
            ORDER BY power(position_x - {actor_x}, 2)
                   + power(position_y - {actor_y}, 2)
            LIMIT 1
            """
        )
        nearest_water_tile = None
        if water_rows:
            nearest_water_tile = {
                "position": {
                    "x": float(water_rows[0][0]),
                    "y": float(water_rows[0][1]),
                },
                "usage": "search_hint_only",
                "walk_target": False,
                "validated_offshore_pump_anchor": False,
                "required_next_call": (
                    "placement_hints.find_offshore_pump_sites"
                ),
                "required_walk_target": "site.approach_position",
            }
        power_row = tier4.remote_view.execute_raw(
            """
            SELECT count(DISTINCT network_id)
            FROM power_networks
            WHERE tick = (SELECT max(tick) FROM power_networks)
            """
        )[0]
        errors: list[str] = []
        if active_mods is None:
            active_mods = self._read_active_mods()
        errors.extend(self._active_mod_errors(active_mods))
        manifest = self.store.manifest()
        errors.extend(
            boot_errors(boot, expected_scenario=manifest.get("scenario", "freeplay"))
        )
        expected_scenario_hash = manifest.get("hashes", {}).get("scenario")
        if expected_scenario_hash is not None:
            scenario_dir = (
                self.repo_root / "src" / "factorio" / "scenarios" / manifest.get("scenario", "freeplay")
            )
            if not scenario_dir.is_dir() or sha256_tree(scenario_dir) != expected_scenario_hash:
                errors.append("repo scenario differs from the campaign manifest hash")
        if engine.get("enemy_base_frequency") not in (0, 0.0):
            errors.append("enemy-base frequency is not zero")
        if engine.get("enemy_base_size") not in (0, 0.0):
            errors.append("enemy-base size is not zero")
        hostile_count = engine.get("hostile_combat_entity_count")
        if not isinstance(hostile_count, (int, float)):
            errors.append("hostile combat entity count is missing from preflight")
        elif int(hostile_count) > 0:
            errors.append(
                "hostile units, spawners, or turrets exist on a loaded surface"
            )
        if engine.get("tick_paused"):
            errors.append("continuous-simulation clock is paused")
        expected_game_speed = self.store.manifest().get(
            "game_speed", FREEPLAY_GAME_SPEED
        )
        if engine.get("game_speed") != expected_game_speed:
            errors.append(
                "game speed does not match campaign manifest "
                f"({engine.get('game_speed')!r} != {expected_game_speed!r})"
            )
        if not tier4.remote_view.is_loaded:
            errors.append("DuckDB RemoteView is not loaded")
        if not sync.is_running:
            errors.append("DuckDB live synchronization is not running")
        if perception["snapshotted_chunks"] == 0:
            errors.append("DuckDB has no completed freeplay chunk snapshots")
        if perception["resource_entities"] + perception["resource_tiles"] == 0:
            errors.append("DuckDB exposes no starting resources to the actor")

        parity: Optional[Dict[str, Any]] = None
        if checkpoint:
            expected = checkpoint["database_fingerprint"]
            parity = {
                "checkpoint_id": checkpoint["checkpoint_id"],
                "expected_entity_count": expected["entity_count"],
                "actual_entity_count": fingerprint["entity_count"],
                "expected_entity_digest": expected["entity_digest"],
                "actual_entity_digest": fingerprint["entity_digest"],
                "matches": (
                    expected["entity_count"] == fingerprint["entity_count"]
                    and expected["entity_digest"] == fingerprint["entity_digest"]
                ),
            }
            if not parity["matches"]:
                errors.append("resumed engine/DB entity fingerprint does not match checkpoint")
            if int(engine["tick"]) < int(checkpoint["game_tick_before"]):
                errors.append("resumed game tick predates the checkpoint")

        return {
            "captured_at": utc_now(),
            "valid": not errors,
            "errors": errors,
            "game_tick": int(engine["tick"]),
            "boot": boot,
            "active_mods": active_mods,
            "enemy_state": engine,
            "database_fingerprint": fingerprint,
            "database_perception": perception,
            "actor_state": {
                "position": actor_position,
                "inventory": engine.get("actor_inventory") or {},
            },
            "factory_state": {
                "entity_count": int(fingerprint["entity_count"]),
                "power_network_count": int(power_row[0]),
                "researched_technology_count": int(
                    engine.get("researched_technology_count", 0)
                ),
            },
            "nearest_resources": nearest_resources,
            "nearest_water_tile": nearest_water_tile,
            "database_sync": {
                "is_running": sync.is_running,
                "last_sequence": sync.last_sequence,
                "needs_rebuild": sync.needs_rebuild,
            },
            "resume_parity": parity,
        }

    async def checkpoint(self, reason: str = "manual") -> Dict[str, Any]:
        if self.checkpoints is None:
            raise FreeplayLaunchError("Checkpoint service is not ready")
        return await self.checkpoints.create(reason=reason)

    async def finish(
        self,
        *,
        reason: str,
        checkpoint: bool = True,
        execution_count: int = 0,
    ) -> Dict[str, Any]:
        if self._finished:
            return self.store.state()
        final_checkpoint = None
        try:
            current = CampaignStatus(self.store.state()["status"])
            if current == CampaignStatus.INVALID:
                reason = self.store.state().get("invalid_reason") or reason
                result = {
                    "schema_version": 1,
                    "campaign_id": self.store.campaign_id,
                    "classification": "invalid_environment",
                    "valid": False,
                    "reason": reason,
                    "updated_at": utc_now(),
                }
                self.store.write_result(result)
                return result
            if checkpoint and self.store.state()["status"] == CampaignStatus.RUNNING.value:
                final_checkpoint = await self.checkpoint(reason=reason)
            if self.session_id:
                last_tick = None
                if self.environment and self.environment.tier3:
                    last_tick = self.environment.tier3.get_game_tick()
                self.store.update_session(
                    self.session_id,
                    status="paused",
                    ended_at=utc_now(),
                    execution_count=execution_count,
                    last_game_tick=last_tick,
                )
            state = self.store.transition(
                CampaignStatus.PAUSED,
                expected={CampaignStatus.RUNNING},
                active_session_id=None,
            )
            result = {
                "schema_version": 1,
                "campaign_id": self.store.campaign_id,
                "classification": "paused",
                "valid": True,
                "reason": reason,
                "updated_at": utc_now(),
                "latest_checkpoint_id": state.get("latest_checkpoint_id"),
                "final_checkpoint": final_checkpoint,
                "runtime_sessions": list(self.store.iter_sessions()),
            }
            self.store.write_result(result)
            return result
        except Exception as exc:
            await self.invalidate(f"Finalization failed: {type(exc).__name__}: {exc}")
            raise
        finally:
            self._finished = True
            await self._shutdown_environment()
            self._release_lease()

    async def invalidate(self, reason: str) -> None:
        if not self.store.exists:
            return
        current = CampaignStatus(self.store.state()["status"])
        if current != CampaignStatus.INVALID:
            self.store.transition(
                CampaignStatus.INVALID,
                expected={current},
                active_session_id=None,
                invalid_reason=reason,
            )
        else:
            self.store.transition(
                CampaignStatus.INVALID,
                expected={CampaignStatus.INVALID},
                active_session_id=None,
                invalid_reason=reason,
            )
        if self.session_id:
            try:
                self.store.update_session(
                    self.session_id,
                    status="invalid",
                    ended_at=utc_now(),
                    invalid_reason=reason,
                )
            except CampaignStateError:
                pass
        self.store.write_result(
            {
                "schema_version": 1,
                "campaign_id": self.store.campaign_id,
                "classification": "invalid_environment",
                "valid": False,
                "reason": reason,
                "updated_at": utc_now(),
            }
        )

    async def _shutdown_environment(self) -> None:
        if self.environment is not None:
            await self.environment.shutdown()
            self.environment = None

    def _release_lease(self) -> None:
        if self._lease is not None:
            self._lease.release()
            self._lease = None
