from types import SimpleNamespace

import pytest

from FactoryVerse.environment.config import RuntimeAccessProfile, RuntimeConfig
from FactoryVerse.environment.tiers.tier4_runtime import Tier4Runtime
from FactoryVerse.evals.freeplay.runtime_host import execution_deadline
from FactoryVerse.evals.freeplay.supervisor import (
    FREEPLAY_STARTING_INVENTORY,
    OFFSHORE_PUMP_DEBUG_INVENTORY,
    _freeplay_runtime_config,
)


def _runtime(profile: RuntimeAccessProfile) -> Tier4Runtime:
    tier3 = SimpleNamespace(rcon=object(), _action_listener=None)
    config = SimpleNamespace(tier4=RuntimeConfig(access_profile=profile))
    environment = SimpleNamespace(config=config, tier3=tier3)
    runtime = Tier4Runtime(environment)
    for name in (
        "_movement",
        "_crafting",
        "_mining",
        "_research",
        "_inventory",
        "_placement",
        "_entity_ops",
    ):
        setattr(runtime, name, None)
    return runtime


@pytest.mark.asyncio
async def test_production_runtime_is_persistent_without_raw_rcon_or_scenario():
    runtime = _runtime(RuntimeAccessProfile.PRODUCTION)

    assert await runtime.execute_code("answer = 41") == ""
    output = await runtime.execute_code(
        "print(answer + 1)\n"
        "print('rcon_client' in globals())\n"
        "print('scenario' in globals())"
    )

    assert output.splitlines() == ["42", "False", "False"]


@pytest.mark.asyncio
async def test_debug_runtime_retains_low_level_names():
    runtime = _runtime(RuntimeAccessProfile.DEBUG)

    output = await runtime.execute_code(
        "print(rcon_client is not None)\nprint('scenario' in globals())"
    )

    assert output.splitlines() == ["True", "True"]


@pytest.mark.asyncio
async def test_execution_deadline_recovers_from_runaway_python():
    runtime = _runtime(RuntimeAccessProfile.PRODUCTION)

    with execution_deadline(0.05):
        output = await runtime.execute_code("while True:\n    pass")

    assert "ExecutionTimedOut" in output


def test_freeplay_runtime_explicitly_mirrors_human_starter_inventory(tmp_path):
    config = _freeplay_runtime_config(
        manifest={"agent_id": "agent_1", "campaign_id": "starter-kit-test"},
        session_dir=tmp_path,
    )

    assert config.initial_inventory == {
        "burner-mining-drill": 1,
        "stone-furnace": 1,
        "wood": 1,
    }
    assert config.initial_inventory is not FREEPLAY_STARTING_INVENTORY
    assert config.access_profile == RuntimeAccessProfile.PRODUCTION
    assert config.database_path == tmp_path / "runtime.duckdb"


def test_freeplay_runtime_uses_manifest_pinned_debug_inventory(tmp_path):
    inventory = {
        "burner-mining-drill": 1,
        "stone-furnace": 1,
        "wood": 1,
        "iron-ore": 120,
        "copper-ore": 80,
        "coal": 80,
        "stone": 50,
    }
    config = _freeplay_runtime_config(
        manifest={
            "agent_id": "agent_1",
            "campaign_id": "notification-debug",
            "initial_inventory": inventory,
        },
        session_dir=tmp_path,
    )

    assert config.initial_inventory == inventory
    assert config.initial_inventory is not inventory


def test_offshore_pump_debug_inventory_is_finite_and_focused():
    assert OFFSHORE_PUMP_DEBUG_INVENTORY == {
        "offshore-pump": 1,
        "pipe": 4,
    }
