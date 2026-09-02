"""Live: the belt derivation against the iron_ore_saturated fixture (TRANSPORT §9.6).

The owner described this base in prose, with coordinates, before the
pipeline was run against it (§1.1). That description is the oracle; the
derived components are under test. An empty derivation cannot pass.

Owns a Docker server. Opt in and give it its own compose project::

    COMPOSE_PROJECT_NAME=fv-transport FV_RUN_LIVE_TRANSPORT_FIXTURE=1 \\
    uv run pytest -q tests/live/test_transport_fixture.py -vv

Needs ``.fv-output/server_0/saves/iron-saturated.zip`` (untracked fixture).
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

import pytest

from FactoryVerse.environment import Environment
from FactoryVerse.environment.config import (
    EnvironmentConfig,
    InfraConfig,
    InfraMode,
    SettingsConfig,
    get_config,
)
from FactoryVerse.environment.tiers.base import Tier
from FactoryVerse.game.agent import transport as T
from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase
from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("FV_RUN_LIVE_TRANSPORT_FIXTURE") != "1",
        reason="set FV_RUN_LIVE_TRANSPORT_FIXTURE=1 to own a server for the belt fixture",
    ),
]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / ".fv-output" / "server_0" / "saves" / "iron-saturated.zip"

# TRANSPORT_CONNECTIVITY_PLAN.md §1.1 — the owner-authored ground truth.
EXPECTED = [
    # (count, heads, tail(s), merges)
    (142, {(19.5, 10.5), (24.5, 73.5)}, {(26.5, 58.5)}, {(39.5, 58.5)}),
    (55, {(35.5, 53.5)}, {(-4.5, 55.5)}, set()),
    (55, {(35.5, 63.5)}, {(-4.5, 61.5)}, set()),
    (32, {(19.5, 17.5)}, {(-7.5, 21.5)}, set()),
]


def _rcon_json(rcon, lua_expr: str):
    return json.loads(rcon.send_command(f"/c rcon.print(helpers.table_to_json({lua_expr}))"))


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
    from factorio_rcon import RCONClient

    cfg = get_config()
    rcon = None
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            rcon = RCONClient(cfg.rcon_host, cfg.get_rcon_port("server_0"), cfg.rcon_password)
            rcon.send_command("/c rcon.print(game.tick)")
            break
        except Exception:  # noqa: BLE001
            rcon = None
            time.sleep(2)
    if rcon is None:
        await env.shutdown()
        pytest.fail("server_0 RCON never came up")
    try:
        yield env, rcon
    finally:
        with contextlib.suppress(Exception):
            rcon.close()
        with contextlib.suppress(Exception):
            await env.shutdown()


def _xy(keys):
    return {(k[1], k[2]) for k in keys}


async def test_fixture_decomposes_into_the_four_named_components(booted_fixture):
    env, rcon = booted_fixture
    # Ask for the boot pass explicitly: a save carries its snapshot bookkeeping
    # but the host directory may be empty (found live 2026-08-29), and this
    # test does not initialise Tier 4, which would otherwise reconcile it.
    _rcon_json(rcon, 'remote.call("map", "boot", "transport_fixture")')
    # wait for the boot reconciliation to ingest the pre-charted world (Phase 1B)
    t0 = time.time()
    while time.time() - t0 < 300:
        report = _rcon_json(rcon, 'remote.call("map", "get_boot_report")')
        if report["phase"] != "INITIAL_SNAPSHOTTING" and report["queue"]["pending"] == 0:
            break
        time.sleep(2)
    assert report["entities"]["tracked"] >= 380, report

    snapshot_dir = Path(get_config().get_snapshot_dir("server_0"))
    db = SnapshotDatabase(":memory:")
    db.ensure_schema()
    result = SnapshotLoader(db.connection, snapshot_dir).load_all()
    belts = db.connection.execute("SELECT count(*) FROM transport_belt").fetchone()[0]
    assert belts == 284, f"expected 284 belts in the map model, got {belts} ({result})"

    lines = T.TransportReads(lambda: db.connection, lambda: "map_entity:fixture").lines()
    got = [(c.count, _xy(c.heads), _xy(c.tails), _xy(c.merges)) for c in lines]
    assert len(lines) == 4, [c.count for c in lines]
    for expected in EXPECTED:
        assert expected in got, f"missing component {expected}; derived: {got}"
