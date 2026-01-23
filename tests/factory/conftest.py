"""Factory-specific test fixtures.

Provides fixtures for testing the factory domain module (entities, prototypes, etc).
"""

import pytest
from typing import Generator


@pytest.fixture(scope="function")
def with_prototypes() -> Generator[None, None, None]:
    """Ensure prototype data is loaded.

    Triggers prototype loading and validates data is available.
    """
    from FactoryVerse.game.factory.prototypes import (
        get_entity_prototypes,
        get_item_prototypes,
    )

    # Trigger prototype loading
    entity_protos = get_entity_prototypes()
    item_protos = get_item_prototypes()

    assert len(entity_protos.data) > 0, "Entity prototypes not loaded"
    assert len(item_protos.items) > 0, "Item prototypes not loaded"

    yield None
