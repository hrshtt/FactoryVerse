"""Trusted native-save, database-evidence, and scoring checkpoints."""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional

from FactoryVerse.game.tasks.sources import RCONSource

from .campaign import FreeplayCampaignStore
from .models import CampaignStatus, CheckpointRecord, utc_now
from .provenance import sha256_file


class CheckpointError(RuntimeError):
    pass


class FreeplayCheckpointService:
    """Creates immutable checkpoint artifacts through trusted Tier 3/4 state."""

    def __init__(self, store: FreeplayCampaignStore, environment: Any):
        self.store = store
        self.environment = environment

    async def capture_score(self, *, reason: str) -> Dict[str, Any]:
        tier3 = self.environment.tier3
        tier4 = self.environment.tier4
        if tier3 is None or tier4 is None or tier3.rcon_helper is None:
            raise CheckpointError("Runtime tiers are not ready for scoring")

        agent_numeric_id = tier4.agent_numeric_id or 1
        script_output = self.environment.config.infra_config.get_script_output_dir(
            tier3.instance
        )
        source = RCONSource(tier3.rcon_helper, script_output_dir=script_output)
        force = await source.get_force_production(agent_numeric_id)
        manual = await source.get_manual_production(agent_numeric_id)

        produced = {key: int(value) for key, value in force.get("input", {}).items()}
        consumed = {key: int(value) for key, value in force.get("output", {}).items()}
        crafted = {key: int(value) for key, value in manual.get("crafted", {}).items()}
        mined = {key: int(value) for key, value in manual.get("mined", {}).items()}
        # Surface-scoped force input counts are machine production. Character
        # crafting/mining are separate feeds and must not be subtracted again.
        automation = dict(produced)

        progression = tier3.run_lua(
            """
            local force = game.forces.player
            local researched = 0
            for _, technology in pairs(force.technologies) do
                if technology.researched then researched = researched + 1 end
            end
            return {
                tick = game.tick,
                rockets_launched = force.rockets_launched,
                researched_technology_count = researched
            }
            """
        )

        fingerprint: Dict[str, Any] = {}
        entity_counts: Dict[str, int] = {}
        power: Dict[str, Any] = {}
        if tier4.remote_view is not None and tier4.remote_view.is_loaded:
            fingerprint = tier4.remote_view.state_fingerprint()
            rows = tier4.remote_view.execute_raw(
                """
                SELECT entity_name, count(*)
                FROM map_entity
                GROUP BY entity_name
                ORDER BY entity_name
                """
            )
            entity_counts = {str(name): int(count) for name, count in rows}
            try:
                report = tier4.remote_view.power()
            except Exception:
                report = None
            if report is not None and report.sample_tick is not None:
                power = {
                    "sample_tick": int(report.sample_tick),
                    "source": report.source,
                    "network_count": len(report.networks),
                    "production_w": float(sum(n.production_w for n in report.networks)),
                    "consumption_w": float(sum(n.consumption_w for n in report.networks)),
                    "storage_j": float(sum(n.storage_j for n in report.networks)),
                }

        score = {
            "captured_at": utc_now(),
            "reason": reason,
            "game_tick": int(progression.get("tick", force.get("tick", 0))),
            "rockets_launched": int(progression.get("rockets_launched", 0)),
            "researched_technology_count": int(
                progression.get("researched_technology_count", 0)
            ),
            "produced_items": produced,
            "consumed_items": consumed,
            "manual_crafted_items": crafted,
            "manual_mined_items": mined,
            "automation_produced_items": automation,
            "automation_produced_total": int(sum(automation.values())),
            "entity_counts": entity_counts,
            "database_fingerprint": fingerprint,
            "power": power,
        }
        self.store.append_score(score)
        return score

    async def create(self, reason: str = "manual") -> Dict[str, Any]:
        tier3 = self.environment.tier3
        tier4 = self.environment.tier4
        if tier3 is None or tier4 is None or tier4.remote_view is None:
            raise CheckpointError("Runtime is not ready for checkpointing")

        state = self.store.state()
        previous_status = CampaignStatus(state["status"])
        self.store.transition(
            CampaignStatus.CHECKPOINTING,
            expected={CampaignStatus.RUNNING},
        )

        records = self.store.checkpoint_records()
        ordinal = len(records) + 1
        checkpoint_id = f"cp-{ordinal:06d}"
        previous_paused = False
        game_paused = False

        try:
            pause_state = tier3.run_lua(
                "local previous = game.tick_paused; game.tick_paused = true; "
                "return {previous=previous, tick=game.tick}",
                safe=True,
                silent=True,
            )
            previous_paused = bool(pause_state.get("previous", False))
            game_paused = True
            tick_before = int(pause_state["tick"])
            checkpoint_id = f"cp-{ordinal:06d}-tick-{tick_before}"
            checkpoint_dir = self.store.paths.checkpoints / checkpoint_id
            checkpoint_dir.mkdir(parents=True, exist_ok=False)
            save_name = f"fv-{self.store.campaign_id}-{checkpoint_id}"
            live_save = (
                self.environment.config.infra_config.get_server_output_dir(0)
                / "saves"
                / f"{save_name}.zip"
            )
            request_started = time.time()
            escaped_save_name = json.dumps(save_name)

            tier3.run_lua(
                f"game.server_save({escaped_save_name}); return true",
                safe=True,
                silent=True,
            )
            await self._wait_for_save(live_save, request_started)

            canonical_save = checkpoint_dir / "factorio-save.zip"
            shutil.copy2(live_save, canonical_save)

            database_path = checkpoint_dir / "map.duckdb"
            tier4.remote_view.checkpoint_database(database_path)
            fingerprint = tier4.remote_view.state_fingerprint()
            score = await self.capture_score(reason=f"checkpoint:{reason}")
            tick_after = tier3.get_game_tick()

            tier3.run_lua(
                f"game.tick_paused = {str(previous_paused).lower()}; return true",
                safe=True,
                silent=True,
            )
            game_paused = False

            record = CheckpointRecord(
                checkpoint_id=checkpoint_id,
                parent_checkpoint_id=(
                    records[-1]["checkpoint_id"] if records else None
                ),
                reason=reason,
                created_at=utc_now(),
                game_tick_before=int(tick_before),
                game_tick_after=int(tick_after),
                save_name=save_name,
                save_path=str(canonical_save.resolve()),
                save_sha256=sha256_file(canonical_save),
                save_size_bytes=canonical_save.stat().st_size,
                database_path=str(database_path.resolve()),
                database_sha256=sha256_file(database_path),
                database_fingerprint=fingerprint,
                score=score,
            )
            metadata_path = checkpoint_dir / "checkpoint.json"
            metadata_path.write_text(
                json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.store.add_checkpoint(record)
            self.store.transition(
                previous_status,
                expected={CampaignStatus.CHECKPOINTING},
            )
            return record.to_dict()
        except Exception:
            if game_paused:
                try:
                    tier3.run_lua(
                        f"game.tick_paused = {str(previous_paused).lower()}; return true",
                        safe=True,
                        silent=True,
                    )
                except Exception:
                    pass
            self.store.transition(
                CampaignStatus.INVALID,
                expected={CampaignStatus.CHECKPOINTING},
                invalid_reason=f"Checkpoint failed: {checkpoint_id}",
            )
            raise

    async def _wait_for_save(
        self, path: Path, request_started: float, timeout: float = 120.0
    ) -> None:
        deadline = time.monotonic() + timeout
        previous_size: Optional[int] = None
        stable_polls = 0
        while time.monotonic() < deadline:
            if path.exists():
                stat = path.stat()
                fresh = stat.st_mtime >= request_started - 1.0
                if fresh and stat.st_size > 0:
                    if previous_size == stat.st_size:
                        stable_polls += 1
                    else:
                        stable_polls = 0
                    previous_size = stat.st_size
                    if stable_polls >= 2:
                        return
            await asyncio.sleep(0.25)
        raise CheckpointError(f"Timed out waiting for native save: {path}")
