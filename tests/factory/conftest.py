"""DSL-specific test fixtures.

Provides AgentRuntime context using the new factory pattern.
"""

import pytest
from typing import Generator, TYPE_CHECKING
from pathlib import Path
import tempfile
import asyncio

if TYPE_CHECKING:
    from helpers.test_ground import TestGround
    from tests.conftest import AdminInterface

from helpers.server import RconConnection


@pytest.fixture(scope="function")
async def agent_runtime(rcon: RconConnection, agent_id: str) -> Generator:
    """Create and start an AgentRuntime for tests.

    Uses the new factory.py pattern with proper DI.

    **Usage**:
    ```python
    async def test_something(agent_runtime):
        furnace = agent_runtime.reachable_view_view_view.get_entity("stone-furnace")
        await agent_runtime.walking.walk_to(MapPosition(10, 10))
    ```
    """
    from FactoryVerse.runtime import create_runtime
    from FactoryVerse.config import get_config
    from FactoryVerse.infra.instance_manager import FactorioInstanceManager

    # Detect the Docker server's script-output directory for snapshots
    config = get_config()
    instance = FactorioInstanceManager.from_env(config)
    snapshot_dir = instance.script_output_dir

    # Use deterministic port allocation based on agent_id and server_index
    # This ensures the port matches Docker's port mappings
    server_index = instance.server_id if instance.type == "server" else None
    
    # Create runtime with deterministic UDP port allocation
    runtime = create_runtime(
        rcon_client=rcon.client,  # Access underlying RCON client
        agent_id=agent_id,
        udp_port=None,  # Auto-allocate deterministically
        snapshot_dir=snapshot_dir,  # Use Docker's script-output directory
        server_index=server_index,  # Use server index for deterministic port
    )

    # Start the runtime (starts async listener)
    await runtime.start()

    try:
        yield runtime
    finally:
        # Cleanup
        await runtime.stop()


@pytest.fixture(scope="function")
def dsl_context(agent_runtime, test_ground: "TestGround", admin: "AdminInterface"):
    """Complete DSL test context with AgentRuntime.

    Combines runtime with test setup helpers.

    **Usage**:
    ```python
    async def test_workflow(dsl_context):
        # Setup
        dsl_context.test_ground.place_entity("stone-furnace", 10, 10)
        dsl_context.admin.add_items(1, {"coal": 50})

        # Access runtime
        runtime = dsl_context.runtime
        furnace = runtime.reachable_view_view.get_entity("stone-furnace")
        info = furnace.inspect()
    ```
    """
    return DSLTestContext(agent_runtime, test_ground, admin)


class DSLTestContext:
    """Aggregate context for DSL tests."""

    def __init__(self, runtime, test_ground, admin):
        self.runtime = runtime
        self.test_ground = test_ground
        self.admin = admin

    # Convenience accessors to runtime affordances
    @property
    def walking(self):
        return self.runtime.walking

    @property
    def crafting(self):
        return self.runtime.crafting

    @property
    def inventory(self):
        return self.runtime.inventory

    @property
    def reachable(self):
        return self.runtime.reachable_view

    @property
    def resources(self):
        return self.runtime.resources

    @property
    def research(self):
        return self.runtime.research


@pytest.fixture(scope="function")
def with_prototypes() -> Generator[Path, None, None]:
    """Ensure prototype data is loaded.

    Provides path to prototype JSON for tests that need it.
    """
    from FactoryVerse.factory.prototypes import (
        get_entity_prototypes,
        get_item_prototypes,
    )

    # Trigger prototype loading
    entity_protos = get_entity_prototypes()
    item_protos = get_item_prototypes()

    assert len(entity_protos.data) > 0, "Entity prototypes not loaded"
    assert len(item_protos.items) > 0, "Item prototypes not loaded"

    # Return path for reference - fixture doesn't need to provide a path anymore
    yield None


@pytest.fixture(scope="function")
def unlocked_recipes(admin: "AdminInterface"):
    """Fixture that unlocks all recipes and technologies.

    **Usage**:
    ```python
    async def test_advanced_crafting(dsl_context, unlocked_recipes):
        # All recipes available
        assembler = dsl_context.reachable_view.get_entity("assembling-machine-1")
        # assembler.set_recipe("advanced-circuit")
    ```
    """
    admin.unlock_all_technologies()
    admin.enable_all_recipes()
