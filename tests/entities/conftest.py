"""Entity test fixtures.

Provides fixtures for testing entity capabilities, inspection states,
and type system compliance.
"""

import pytest
from typing import Dict, List, Any


@pytest.fixture(scope="function")
def entity_setup_with_resources(test_ground, admin):
    """Factory for setting up entities with their required environments.

    Returns a function that sets up an entity with proper environment
    (ore for miners, water for offshore pumps, etc.)
    """

    def _setup(entity_name: str, x: float, y: float) -> Dict[str, Any]:
        """Setup entity with required environment.

        Args:
            entity_name: Name of entity to place
            x, y: Position to place at

        Returns:
            Dict with 'success', 'position', 'metadata'
        """
        # Clear area first - use (left_top, right_bottom) tuples
        half = 5  # 10/2 for 10x10 area
        test_ground.clear_area((x - half, y - half), (x + half, y + half))

        # Setup environment based on entity type
        if "mining-drill" in entity_name:
            test_ground.place_resource_patch("iron-ore", x, y, size=8, amount=5000)
        elif entity_name == "pumpjack":
            test_ground.place_resource_patch("crude-oil", x, y, size=3, amount=50000)
        elif entity_name == "offshore-pump":
            # Place water tiles - offshore pump needs water
            for dx in range(5):
                for dy in range(5):
                    test_ground.place_water_tile(x + dx, y + dy)

        # Place the entity
        result = test_ground.place_entity(entity_name, x, y)

        return result

    return _setup


@pytest.fixture(scope="function")
def burner_entities() -> List[str]:
    """List of entity names that should have burner capability."""
    return [
        "burner-mining-drill",
        "burner-inserter",
        "stone-furnace",
        "steel-furnace",
        "boiler",
    ]


@pytest.fixture(scope="function")
def electric_entities() -> List[str]:
    """List of entity names that should have electric capability."""
    return [
        "electric-mining-drill",
        "assembling-machine-1",
        "assembling-machine-2",
        "assembling-machine-3",
        "electric-furnace",
        "inserter",
        "fast-inserter",
        "lab",
        "radar",
        "beacon",
    ]


@pytest.fixture(scope="function")
def miner_entities() -> List[str]:
    """List of entity names that should have miner capability."""
    return [
        "burner-mining-drill",
        "electric-mining-drill",
    ]


@pytest.fixture(scope="function")
def crafter_entities() -> List[str]:
    """List of entity names that should have crafter capability."""
    return [
        "stone-furnace",
        "steel-furnace",
        "electric-furnace",
        "assembling-machine-1",
        "assembling-machine-2",
        "assembling-machine-3",
        "chemical-plant",
        "oil-refinery",
    ]


@pytest.fixture(scope="function")
def inserter_entities() -> List[str]:
    """List of entity names that should have inserter capability."""
    return [
        "inserter",
        "fast-inserter",
        "long-handed-inserter",
        "filter-inserter",
        "stack-inserter",
        "bulk-inserter",
        "burner-inserter",
    ]


@pytest.fixture(scope="function")
def belt_entities() -> List[str]:
    """List of entity names that should have belt capability."""
    return [
        "transport-belt",
        "fast-transport-belt",
        "express-transport-belt",
        "underground-belt",
        "fast-underground-belt",
        "express-underground-belt",
        "splitter",
        "fast-splitter",
        "express-splitter",
    ]


@pytest.fixture(scope="function")
def fluid_entities() -> List[str]:
    """List of entity names that should have fluid capability."""
    return [
        "pipe",
        "pipe-to-ground",
        "storage-tank",
        "pump",
        "offshore-pump",
        "boiler",
        "chemical-plant",
        "oil-refinery",
    ]


@pytest.fixture(scope="function")
def container_entities() -> List[str]:
    """List of entity names that should be Container implementations."""
    return [
        "wooden-chest",
        "iron-chest",
        "steel-chest",
    ]


@pytest.fixture(scope="function")
def capability_entity_map(
    burner_entities,
    electric_entities,
    miner_entities,
    crafter_entities,
    inserter_entities,
    belt_entities,
    fluid_entities,
    container_entities,
) -> Dict[str, List[str]]:
    """Map of capability names to entity names that should have them."""
    return {
        "BurnerMixin": burner_entities,
        "ElectricMixin": electric_entities,
        "MinerMixin": miner_entities,
        "CrafterMixin": crafter_entities,
        "InserterMixin": inserter_entities,
        "BeltMixin": belt_entities,
        "FluidMixin": fluid_entities,
        "Container": container_entities,
    }
