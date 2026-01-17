"""
Pytest configuration for FactoryVerse tests using the Environment module.
"""

import pytest
import os
import shutil
import asyncio
from pathlib import Path
from typing import AsyncGenerator, Generator, Dict, Any

from FactoryVerse.environment.environment import Environment, Tier
from FactoryVerse.environment.config import (
    EnvironmentConfig,
    RuntimeVariant,
    InfraMode,
    SettingsConfig,
    RuntimeConfig,
    InfraConfig,
)
from FactoryVerse.config import get_config

# ============================================================================
# CONFIGURATION HELPERS
# ============================================================================


def _create_test_config(**overrides) -> EnvironmentConfig:
    """Create test configuration with overrides.

    Supports deep merging of tier configs:
    - _create_test_config(tier2={"scenario": "freeplay"})
    - _create_test_config(tier4={"variant": RuntimeVariant.FULL})

    Args:
        **overrides: Configuration overrides (tier2, tier4, etc.)

    Returns:
        EnvironmentConfig with overrides applied
    """
    base_config = EnvironmentConfig.for_testing()

    # Deep merge overrides
    for tier_key, tier_overrides in overrides.items():
        if tier_key.startswith("tier") and hasattr(base_config, tier_key):
            tier_attr = getattr(base_config, tier_key)
            if isinstance(tier_overrides, dict):
                # Merge dict into tier config
                tier_dict = tier_attr.dict()
                tier_dict.update(tier_overrides)
                # Reconstruct tier config
                tier_class = type(tier_attr)
                setattr(base_config, tier_key, tier_class(**tier_dict))
            else:
                setattr(base_config, tier_key, tier_overrides)
        else:
            # Direct config attribute
            setattr(base_config, tier_key, tier_overrides)

    return base_config


def _discover_scenarios() -> list[str]:
    """Discover available scenarios at test collection time.

    Returns:
        List of scenario names that have control.lua files
    """
    config = get_config()
    return config.list_scenarios(include_local=False)  # Only repo scenarios for tests


# Discover scenarios once at module load time (for parametrization)
_AVAILABLE_SCENARIOS = _discover_scenarios()

# ============================================================================
# ENVIRONMENT FIXTURES
# ============================================================================


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def environment() -> AsyncGenerator[Environment, None]:
    """
    Function-scoped Environment fixture for testing.

    Initializes a fresh environment for each test with:
    - Independent session directory
    - Minimal runtime (no DuckDB unless requested)
    - Test scenario
    """
    # Create environment for testing
    # We use MINIMAL variant by default for speed, unless test requests FULL
    env = Environment.for_testing(
        scenario="test-ground",
        variant="minimal",
    )

    try:
        # Initialize up to Runtime (Tier 4)
        await env.initialize(up_to=Tier.RUNTIME)
        yield env
    finally:
        # Ensure clean shutdown
        await env.shutdown()

        # Cleanup session directory if it exists
        if env.tier4 and env.tier4.session_dir and env.tier4.session_dir.exists():
            try:
                shutil.rmtree(env.tier4.session_dir)
            except Exception:
                pass


@pytest.fixture(scope="function")
async def full_environment() -> AsyncGenerator[Environment, None]:
    """
    Environment with FULL runtime (DuckDB, RemoteView).

    Note: This is now independent of `environment` fixture to avoid
    unnecessary shutdown/reinit cycles.
    """
    config = _create_test_config(tier4={"variant": RuntimeVariant.FULL})
    env = Environment(config=config)

    try:
        await env.initialize(up_to=Tier.RUNTIME)
        yield env
    finally:
        await env.shutdown()

        # Cleanup session directory
        if env.tier4 and env.tier4.session_dir and env.tier4.session_dir.exists():
            try:
                shutil.rmtree(env.tier4.session_dir)
            except Exception:
                pass


# ============================================================================
# FACTORY FIXTURES
# ============================================================================


@pytest.fixture
def environment_factory():
    """Factory for creating environments with custom configurations.

    Usage:
        async def test_custom(environment_factory):
            env = await environment_factory(
                tier2={"scenario": "freeplay"},
                tier4={"variant": RuntimeVariant.FULL},
            )
            try:
                # ... test ...
            finally:
                await env.shutdown()
    """

    async def _factory(**overrides) -> Environment:
        config = _create_test_config(**overrides)
        env = Environment(config=config)
        await env.initialize(up_to=Tier.RUNTIME)
        return env

    return _factory


# ============================================================================
# PARAMETRIZED FIXTURES
# ============================================================================


@pytest.fixture(
    scope="function",
    params=[
        RuntimeVariant.MINIMAL,
        RuntimeVariant.FULL,
    ],
    ids=["minimal", "full"],
)
async def environment_variant(request) -> AsyncGenerator[Environment, None]:
    """Environment with parametrized runtime variant.

    Tests using this fixture will run twice (once per variant).
    This ensures features work in both MINIMAL and FULL variants.

    Usage:
        async def test_feature(environment_variant):
            # Test runs with both MINIMAL and FULL variants
            assert environment_variant.tier4 is not None
    """
    variant = request.param
    config = _create_test_config(tier4={"variant": variant})
    env = Environment(config=config)

    try:
        await env.initialize(up_to=Tier.RUNTIME)
        yield env
    finally:
        await env.shutdown()

        # Cleanup session directory
        if env.tier4 and env.tier4.session_dir and env.tier4.session_dir.exists():
            try:
                shutil.rmtree(env.tier4.session_dir)
            except Exception:
                pass


@pytest.fixture(
    scope="function",
    params=_AVAILABLE_SCENARIOS if _AVAILABLE_SCENARIOS else ["test-ground"],
    ids=lambda x: f"scenario-{x}",
)
async def environment_scenario(request) -> AsyncGenerator[Environment, None]:
    """Environment with parametrized scenario (discovered at runtime).

    Tests using this fixture will run once per available scenario.
    Scenarios are discovered from the filesystem at test collection time.

    Usage:
        async def test_scenario_behavior(environment_scenario):
            # Test runs for each available scenario
            scenario = environment_scenario.tier2.current_scenario
            assert scenario is not None
    """
    scenario = request.param
    config = _create_test_config(tier2={"scenario": scenario})
    env = Environment(config=config)

    try:
        await env.initialize(up_to=Tier.RUNTIME)
        yield env
    finally:
        await env.shutdown()

        # Cleanup session directory
        if env.tier4 and env.tier4.session_dir and env.tier4.session_dir.exists():
            try:
                shutil.rmtree(env.tier4.session_dir)
            except Exception:
                pass


# ============================================================================
# NAMED SCENARIO FIXTURES (for common scenarios)
# ============================================================================


@pytest.fixture(scope="function")
async def freeplay_environment() -> AsyncGenerator[Environment, None]:
    """Environment with freeplay scenario."""
    config = _create_test_config(tier2={"scenario": "freeplay"})
    env = Environment(config=config)

    try:
        await env.initialize(up_to=Tier.RUNTIME)
        yield env
    finally:
        await env.shutdown()

        if env.tier4 and env.tier4.session_dir and env.tier4.session_dir.exists():
            try:
                shutil.rmtree(env.tier4.session_dir)
            except Exception:
                pass


@pytest.fixture(scope="function")
async def lab_environment() -> AsyncGenerator[Environment, None]:
    """Environment with lab scenario."""
    config = _create_test_config(tier2={"scenario": "default_lab_scenario"})
    env = Environment(config=config)

    try:
        await env.initialize(up_to=Tier.RUNTIME)
        yield env
    finally:
        await env.shutdown()

        if env.tier4 and env.tier4.session_dir and env.tier4.session_dir.exists():
            try:
                shutil.rmtree(env.tier4.session_dir)
            except Exception:
                pass


# ============================================================================
# DISCOVERY FIXTURES
# ============================================================================


@pytest.fixture(scope="session")
def available_scenarios() -> list[str]:
    """List of available scenarios discovered at test collection time.

    This fixture provides the list of scenarios that were discovered
    from the filesystem. Use this for custom parametrization or to
    skip tests when scenarios are missing.

    Usage:
        def test_with_custom_param(available_scenarios):
            if "freeplay" not in available_scenarios:
                pytest.skip("freeplay scenario not available")
    """
    return _AVAILABLE_SCENARIOS


# ============================================================================
# COMPONENT FIXTURES
# ============================================================================


@pytest.fixture(scope="function")
def tier4(environment: Environment):
    """Access to Tier 4 (Runtime)."""
    return environment.tier4


@pytest.fixture(scope="function")
def agent(tier4):
    """Access to Agent actions (wrapper around embodied actions)."""
    # In the future, we might want a unified agent object
    # For now, return the embodied actions dict for direct access
    return tier4.embodied_actions


@pytest.fixture(scope="function")
def rcon(environment: Environment):
    """Access to RCON client."""
    return environment.tier3.rcon_helper


@pytest.fixture(scope="function")
def reachable_view(tier4):
    """Access to ReachableView."""
    return tier4.reachable_view


@pytest.fixture(scope="function")
def remote_view(full_environment: Environment):
    """Access to RemoteView (requires full environment)."""
    return full_environment.tier4.remote_view


# ============================================================================
# LEGACY COMPATIBILITY (Temporary)
# ============================================================================


@pytest.fixture(scope="function")
def legacy_agent_interface(agent, rcon, tier4):
    """
    Adapter to mimic old AgentInterface for easier migration.
    """

    class LegacyAdapter:
        def __init__(self):
            self.rcon = rcon
            self.actions = agent
            self.agent_id = tier4.agent_id

        def inspect(self, *args, **kwargs):
            return self.rcon.call(self.agent_id, "inspect", *args)

        def get_position(self):
            return self.rcon.call(self.agent_id, "get_position")

        def get_inventory(self):
            return self.rcon.call(self.agent_id, "get_inventory_items")

        # Add more adapters as needed during migration

    return LegacyAdapter()
