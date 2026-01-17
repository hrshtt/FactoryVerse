"""
Pytest configuration for FactoryVerse tests using the Environment module.
"""

import pytest
import os
import shutil
import asyncio
from pathlib import Path
from typing import AsyncGenerator, Generator

from FactoryVerse.environment.environment import Environment, Tier
from FactoryVerse.environment.config import RuntimeVariant

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
async def full_environment(
    environment: Environment,
) -> AsyncGenerator[Environment, None]:
    """
    Environment with FULL runtime (DuckDB, RemoteView).
    """
    # Re-configure for full runtime
    # Note: efficient reuse/upgrade of existing environment would be optimization
    # For now, just create a new one to be safe and simple
    await environment.shutdown()

    env = Environment.for_testing(
        scenario="test-ground",
        variant="full",
    )

    try:
        await env.initialize(up_to=Tier.RUNTIME)
        yield env
    finally:
        await env.shutdown()


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
