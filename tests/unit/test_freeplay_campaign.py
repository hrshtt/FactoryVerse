import json

import pytest

from FactoryVerse.evals.freeplay import (
    CampaignLeaseError,
    CampaignStatus,
    CheckpointRecord,
    FreeplayCampaignStore,
    RuntimeSessionRecord,
)


def test_campaign_create_state_session_and_checkpoint_lineage(tmp_path):
    store = FreeplayCampaignStore(tmp_path, "rocket-run-01")
    manifest = store.create(
        {
            "scenario": "freeplay",
            "seed": 44340,
            "enemies_enabled": False,
        }
    )

    assert manifest["campaign_id"] == "rocket-run-01"
    assert store.state()["status"] == CampaignStatus.DEFINED.value
    assert store.paths.server_output.is_dir()
    assert store.paths.server_mods.is_dir()
    assert store.paths.compose == store.paths.root / "server-compose.yml"

    session = RuntimeSessionRecord(
        session_id="session-1",
        actor_id="agent_1",
        started_at="2026-08-06T00:00:00+00:00",
        access_profile="production",
        harness="codex",
        model="example-model",
    )
    session_path = store.start_session(session)
    store.update_session("session-1", status="running", execution_count=2)
    assert json.loads(session_path.read_text())["execution_count"] == 2

    store.transition(
        CampaignStatus.PROVISIONING,
        expected={CampaignStatus.DEFINED},
    )
    record = CheckpointRecord(
        checkpoint_id="cp-000001-tick-10",
        parent_checkpoint_id=None,
        reason="test",
        created_at="2026-08-06T00:01:00+00:00",
        game_tick_before=10,
        game_tick_after=11,
        save_name="save-1",
        save_path="/tmp/save.zip",
        save_sha256="a" * 64,
        save_size_bytes=10,
        database_path="/tmp/map.duckdb",
        database_sha256="b" * 64,
        database_fingerprint={"entity_count": 1, "entity_digest": "2"},
        score={"rockets_launched": 0},
    )
    store.add_checkpoint(record)

    assert store.resolve_checkpoint("latest")["checkpoint_id"] == record.checkpoint_id
    assert store.state()["latest_checkpoint_id"] == record.checkpoint_id


def test_campaign_id_cannot_escape_root(tmp_path):
    with pytest.raises(ValueError):
        FreeplayCampaignStore(tmp_path, "../outside")


def test_campaign_lease_has_one_owner(tmp_path):
    store = FreeplayCampaignStore(tmp_path, "exclusive")
    store.create({"scenario": "freeplay"})

    first = store.lease("session-a").acquire()
    try:
        with pytest.raises(CampaignLeaseError):
            store.lease("session-b").acquire()
    finally:
        first.release()

    second = store.lease("session-b").acquire()
    second.release()
