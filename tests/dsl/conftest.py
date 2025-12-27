"""DSL-specific test fixtures.

Provides PlayingFactory context using configure() + playing_factorio()
similar to how the runtime boilerplate sets it up.
"""

import pytest
from typing import Generator
from pathlib import Path
import tempfile

from helpers.server import RconConnection


@pytest.fixture(scope="function")
def dsl_configured(rcon: RconConnection, agent_id: str) -> Generator[None, None, None]:
    """Configure DSL runtime for tests.

    Sets up the global DSL configuration using configure().
    Must be called before using playing_factorio() context.

    **Usage**:
    ```python
    def test_something(dsl_configured):
        with playing_factorio():
            await walking.to(MapPosition(10, 10))
    ```
    """
    from FactoryVerse.dsl.dsl import configure

    # Create temp directory for snapshot/db
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_dir = Path(tmpdir) / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        db_path = Path(tmpdir) / "test.duckdb"

        # Configure DSL (similar to boilerplate.py)
        configure(
            rcon,
            agent_id,
            snapshot_dir=snapshot_dir,
            db_path=db_path,
            agent_udp_port=None,  # Use dispatcher mode in tests
        )

        yield

        # Cleanup is automatic via tempdir


@pytest.fixture(scope="function")
def dsl_context(dsl_configured, test_ground: "TestGround", admin: "AdminInterface"):
    """Complete DSL test context with playing_factorio() helper.

    Combines DSL runtime with test setup helpers.

    **Usage**:
    ```python
    def test_workflow(dsl_context):
        # Setup
        dsl_context.test_ground.place_entity("stone-furnace", 10, 10)
        dsl_context.admin.add_items(1, {"coal": 50})

        # Test DSL - must use playing_factorio() context
        with dsl_context.playing():
            furnace = reachable.get_entity("stone-furnace")
            info = furnace.inspect()
    ```
    """
    return DSLTestContext(test_ground, admin)


class DSLTestContext:
    """Aggregate context for DSL tests."""

    def __init__(self, test_ground, admin):
        self.test_ground = test_ground
        self.admin = admin

    def playing(self):
        """Get playing_factorio() context manager.

        **Usage**:
        ```python
        with dsl_context.playing():
            # Use top-level affordances here
            await walking.to(MapPosition(10, 10))
            furnace = reachable.get_entity("stone-furnace")
        ```
        """
        from FactoryVerse.dsl.dsl import playing_factorio

        return playing_factorio()


@pytest.fixture(scope="function")
def with_prototypes() -> Generator[Path, None, None]:
    """Ensure prototype data is loaded.

    Provides path to prototype JSON for tests that need it.
    """
    from FactoryVerse.dsl.prototypes import get_entity_prototypes, get_item_prototypes

    # Trigger prototype loading
    entity_protos = get_entity_prototypes()
    item_protos = get_item_prototypes()

    assert len(entity_protos._prototypes) > 0, "Entity prototypes not loaded"
    assert len(item_protos._prototypes) > 0, "Item prototypes not loaded"

    # Return path for reference
    proto_path = Path(__file__).parent.parent.parent / "prototype-api.json"
    yield proto_path


@pytest.fixture(scope="function")
def unlocked_recipes(admin: "AdminInterface"):
    """Fixture that unlocks all recipes and technologies.

    **Usage**:
    ```python
    def test_advanced_crafting(dsl_context, unlocked_recipes):
        # All recipes available
        with dsl_context.playing():
            assembler = reachable.get_entity("assembling-machine-1")
            assembler.set_recipe("advanced-circuit")
    ```
    """
    admin.unlock_all_technologies()
    admin.enable_all_recipes()
