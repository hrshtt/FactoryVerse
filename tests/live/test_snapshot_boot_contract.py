"""Live: the snapshot boot contract (TRANSPORT_CONNECTIVITY_PLAN §13).

A save charted long before the mods existed — the iron_ore_saturated fixture —
must be ingested at boot: the chunk tracker learns every charted chunk, the
chunks holding tracked-force entities are flagged, and the phase machine ends
in MAINTENANCE with a non-zero consideration count. Before 2026-08-29 this
fixture produced 0 chunks, 0 entities and a healthy-looking MAINTENANCE.

Owns a Docker server. Opt in and give it its own ports::

    COMPOSE_PROJECT_NAME=fv-snapshot-boot FV_RUN_LIVE_SNAPSHOT_BOOT=1 \\
    uv run pytest -q tests/live/test_snapshot_boot_contract.py -vv

Needs ``.fv-output/server_0/saves/iron-saturated.zip`` (untracked fixture).
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

import pytest

from FactoryVerse.environment.config import (
    EnvironmentConfig,
    InfraConfig,
    InfraMode,
    SettingsConfig,
    get_config,
)
from FactoryVerse.environment import Environment
from FactoryVerse.environment.tiers.base import Tier

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("FV_RUN_LIVE_SNAPSHOT_BOOT") != "1",
        reason="set FV_RUN_LIVE_SNAPSHOT_BOOT=1 to own a server for the boot contract",
    ),
]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / ".fv-output" / "server_0" / "saves" / "iron-saturated.zip"
# Ground truth from the fixture's owner-authored description (TRANSPORT §1):
# 284 belts + 44 poles + 24 drills + 30 inserters + 10 furnaces + 2 engines +
# 2 chests + boiler + pump = 398 placed entities; the plan measured 404 with
# the character and incidental entities.
MIN_TRACKED_ENTITIES = 380


def _rcon_json(rcon, lua_expr: str):
    out = rcon.send_command(f"/c rcon.print(helpers.table_to_json({lua_expr}))")
    return json.loads(out)


@pytest.fixture(scope="module")
async def booted_fixture():
    if not FIXTURE.exists():
        pytest.skip(f"fixture missing: {FIXTURE}")
    env = Environment(
        config=EnvironmentConfig(
            tier1=InfraConfig(mode=InfraMode.SERVER, server_count=1),
            tier2=SettingsConfig(scenario="lab-grid", peaceful=True),
        )
    )
    await env.initialize(up_to=Tier.FACTORIO_INFRA)
    await env.tier1.start_server(scenario="lab-grid", num_instances=1, save="iron-saturated")
    from factorio_rcon import RCONClient, RCONConnectError

    cfg = get_config()
    port = cfg.get_rcon_port("server_0")
    rcon = None
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            rcon = RCONClient(cfg.rcon_host, port, cfg.rcon_password)
            rcon.send_command("/c rcon.print(game.tick)")
            break
        except Exception:  # noqa: BLE001 — boot is racing; retry
            rcon = None
            time.sleep(2)
    if rcon is None:
        await env.shutdown()
        pytest.fail("server_0 RCON never came up")
    try:
        yield rcon
    finally:
        with contextlib.suppress(Exception):
            rcon.close()
        with contextlib.suppress(Exception):
            await env.shutdown()


async def test_boot_ingests_a_pre_charted_world(booted_fixture):
    rcon = booted_fixture
    t0 = time.time()
    report = None
    # Wait for the queue to drain: the boot pass queues, the state machine snapshots.
    while time.time() - t0 < 300:
        report = _rcon_json(rcon, 'remote.call("map", "get_boot_report")')
        if report["phase"] != "INITIAL_SNAPSHOTTING" and report["queue"]["pending"] == 0:
            break
        time.sleep(2)
    assert report is not None
    elapsed = time.time() - t0
    print(f"boot report after {elapsed:.1f}s: {json.dumps(report)}")

    assert report["reason"] in ("on_init", "on_configuration_changed"), report["reason"]
    assert report["chunks"]["charted"] > 0, "boot pass found no charted chunks"
    assert report["chunks"]["with_entities"] > 0
    assert report["phase"] == "MAINTENANCE", report["phase"]
    assert report["tracker"]["with_entities"] > 0
    assert report["entities"]["tracked"] >= MIN_TRACKED_ENTITIES, report["entities"]

    charted = _rcon_json(rcon, 'remote.call("map", "get_charted_chunks")')
    assert len(charted) > 0, "get_charted_chunks() is still empty after boot"
    assert len(charted) == report["tracker"]["with_entities"]

    status = _rcon_json(rcon, 'remote.call("map", "get_snapshot_status")')
    assert status["chunks_considered"] > 0
    assert status["completed_chunks"] >= report["chunks"]["with_entities"]
