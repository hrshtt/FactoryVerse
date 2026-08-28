"""SCENARIO_BOOT_CONTRACT_DEFERRED.md §9 — the checks that need a world.

Boots a dedicated Docker server per test module on ports that are not owned
by another campaign, then asks the running world what it is. Run with::

    FV_RUN_LIVE_SCENARIO_BOOT_TESTS=1 \\
    FV_RCON_SERVER_PORT_BASE=39500 FV_GAME_PORT_BASE=48397 \\
    FV_AGENT_PORT_BASE=48602 FV_SNAPSHOT_PORT_BASE=48800 FV_ENABLE_UDP_PORT=48600 \\
    uv run pytest -q tests/live/test_scenario_boot_contract.py -vv

The joining-human check additionally needs a real client connected to the
booted server; set FV_LIVE_HUMAN_CLIENT=1 once one has joined.
"""

from __future__ import annotations

import os

import pytest

from FactoryVerse.environment import Environment, Tier
from FactoryVerse.environment.boot_probe import boot_errors, probe_boot
from FactoryVerse.environment.config import (
    EnvironmentConfig,
    FactoryVerseConfig,
    InfraConfig,
    InfraMode,
    PythonConfig,
    SettingsConfig,
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("FV_RUN_LIVE_SCENARIO_BOOT_TESTS") != "1",
        reason="set FV_RUN_LIVE_SCENARIO_BOOT_TESTS=1 to boot a server for these checks",
    ),
]


async def _boot(seed: int):
    infra = FactoryVerseConfig(map_gen_seed=seed)
    config = EnvironmentConfig(
        tier1=InfraConfig(mode=InfraMode.SERVER),
        tier2=SettingsConfig(scenario="freeplay", peaceful=True),
        tier3=PythonConfig(instance="server_0"),
    )
    config._infra_config = infra
    env = Environment(config=config)
    await env.initialize(up_to=Tier.PYTHON_INFRA)
    return env


@pytest.fixture(scope="module")
async def booted():
    env = await _boot(seed=44340)
    try:
        yield env, probe_boot(env.tier3)
    finally:
        await env.shutdown()


async def test_the_scenario_that_booted_is_the_one_named(booted):
    _, probe = booted
    assert probe["loaded_scenario"] == "freeplay", probe["interfaces"]
    assert probe["contract"]["name"] == "freeplay"
    assert "freeplay" not in probe["interfaces"], "base freeplay must not be loaded alongside ours"
    assert probe["world"]["always_day"] is True


async def test_the_world_was_generated_from_the_mounted_settings(booted):
    _, probe = booted
    assert probe["world"]["seed"] == 44340
    assert probe["world"]["no_enemies_mode"] is True
    assert probe["world"]["peaceful_mode"] is True
    assert probe["world"]["enemy_base"]["frequency"] == 0


async def test_the_world_contains_no_enemies(booted):
    env, _ = booted
    # Generate the fixed comparison area from §7 before counting.
    env.tier3.run_lua(
        "local s = game.surfaces[1]; s.request_to_generate_chunks({0,0}, 8); "
        "s.force_generate_chunk_requests(); return true"
    )
    probe = probe_boot(env.tier3)
    assert probe["enemies"] == {"total": 0, "spawners": 0, "worms": 0, "units": 0}


async def test_observer_policy_is_readable_and_on(booted):
    _, probe = booted
    assert probe["observer"] is not None
    assert probe["observer"]["enabled"] is True
    assert boot_errors(probe, expected_scenario="freeplay") == []


async def test_snapshot_ingestion_tracks_what_is_charted(booted):
    _, probe = booted
    ingestion = probe["ingestion"]
    assert ingestion["available"], "fv_snapshot 'map' interface missing"
    # Before Tier 4 creates an agent nothing has charted anything, so both
    # counts are legitimately zero here. The invariant is that nothing
    # charted goes untracked; on a pre-built save this is the check that
    # goes red (TRANSPORT §13).
    assert ingestion["tracked_chunks"] >= ingestion["charted_chunks"]


async def test_a_different_seed_makes_a_different_world(booted):
    env_a, probe_a = booted
    digest_a = env_a.tier3.run_lua(
        "local s = game.surfaces[1]; return s.count_entities_filtered{type='resource', area={{-64,-64},{64,64}}}"
    )
    await env_a.shutdown()
    env_b = await _boot(seed=44341)
    try:
        probe_b = probe_boot(env_b.tier3)
        digest_b = env_b.tier3.run_lua(
            "local s = game.surfaces[1]; return s.count_entities_filtered{type='resource', area={{-64,-64},{64,64}}}"
        )
        assert probe_b["world"]["seed"] == 44341
        assert probe_a["world"]["seed"] != probe_b["world"]["seed"]
        assert digest_a != digest_b, "two seeds generated the same resource layout"
    finally:
        await env_b.shutdown()


@pytest.mark.skipif(
    os.environ.get("FV_LIVE_HUMAN_CLIENT") != "1",
    reason="needs a human client connected to the booted server; set FV_LIVE_HUMAN_CLIENT=1",
)
async def test_a_joining_human_has_no_character_and_alters_nothing(booted):
    env, _ = booted
    before = env.tier3.run_lua(
        "local s = game.surfaces[1]; return s.count_entities_filtered{force='player'}"
    )
    status = env.tier3.run_lua("return remote.call('spectator', 'get_spectator_status')")
    assert status["connected_players"], "no human is connected"
    for player in status["connected_players"]:
        assert player["has_character"] is False, player
        assert player["controller"] == 5, f"expected defines.controllers.spectator (5 in 2.0.76), got {player}"
    after = env.tier3.run_lua(
        "local s = game.surfaces[1]; return s.count_entities_filtered{force='player'}"
    )
    assert before == after
