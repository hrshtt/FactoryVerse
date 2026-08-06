import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from FactoryVerse.evals.freeplay import CampaignStatus, FreeplayCampaignStore
from FactoryVerse.evals.freeplay.checkpoint import FreeplayCheckpointService


class _FakeTier3:
    def __init__(self, server_output: Path):
        self.server_output = server_output
        self.tick = 100
        self.paused = False

    def get_game_tick(self):
        return self.tick

    def run_lua(self, code, **kwargs):
        if "game.tick_paused = true" in code:
            previous = self.paused
            self.paused = True
            return {"previous": previous, "tick": self.tick}
        if "game.server_save" in code:
            save_name = re.search(r'game\.server_save\("([^"]+)"\)', code).group(1)
            save_path = self.server_output / "saves" / f"{save_name}.zip"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(b"factorio-save")
            return True
        if "game.tick_paused = false" in code:
            self.paused = False
            return True
        raise AssertionError(f"Unexpected Lua: {code}")


class _FakeRemoteView:
    def checkpoint_database(self, destination):
        Path(destination).write_bytes(b"duckdb-evidence")

    def state_fingerprint(self):
        return {"entity_count": 2, "entity_digest": "42", "last_sequence": 7}


@pytest.mark.asyncio
async def test_checkpoint_quiesces_world_and_restores_continuous_clock(tmp_path):
    store = FreeplayCampaignStore(tmp_path / "campaigns", "checkpoint-test")
    store.create({"scenario": "freeplay"})
    store.transition(CampaignStatus.RUNNING, expected={CampaignStatus.DEFINED})

    server_output = tmp_path / "server_0"
    tier3 = _FakeTier3(server_output)
    tier4 = SimpleNamespace(remote_view=_FakeRemoteView())
    infra = SimpleNamespace(get_server_output_dir=lambda index: server_output)
    environment = SimpleNamespace(
        tier3=tier3,
        tier4=tier4,
        config=SimpleNamespace(infra_config=infra),
    )
    service = FreeplayCheckpointService(store, environment)

    async def _score(*, reason):
        score = {"reason": reason, "game_tick": tier3.tick}
        store.append_score(score)
        return score

    service.capture_score = _score
    record = await service.create(reason="unit_test")

    assert tier3.paused is False
    assert record["checkpoint_id"] == "cp-000001-tick-100"
    assert Path(record["save_path"]).read_bytes() == b"factorio-save"
    assert Path(record["database_path"]).read_bytes() == b"duckdb-evidence"
    assert store.state()["status"] == CampaignStatus.RUNNING.value
    assert store.resolve_checkpoint("latest")["save_sha256"] == record["save_sha256"]
