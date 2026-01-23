"""Common configurations shared across task definitions.

This module provides shared starting inventories and other common
configurations used by multiple task types.
"""

# Standard lab inventory for throughput tasks
# Provides everything needed for building automated factories
LAB_STARTING_INVENTORY: dict[str, int] = {
    # Fuel
    "coal": 500,
    # Mining infrastructure
    "burner-mining-drill": 50,
    "electric-mining-drill": 50,
    # Storage
    "wooden-chest": 10,
    # Inserters
    "burner-inserter": 50,
    "inserter": 50,
    # Logistics
    "transport-belt": 500,
    "underground-belt": 100,
    "medium-electric-pole": 500,
    "pipe": 500,
    "pipe-to-ground": 100,
    # Smelting
    "stone-furnace": 10,
    "electric-furnace": 10,
    # Power
    "boiler": 2,
    "offshore-pump": 2,
    "steam-engine": 2,
    # Assembly
    "assembling-machine-2": 10,
    # Oil processing
    "pumpjack": 10,
    "oil-refinery": 5,
    "chemical-plant": 5,
    "storage-tank": 10,
}

# Minimal inventory for simpler tasks
MINIMAL_STARTING_INVENTORY: dict[str, int] = {
    "coal": 100,
    "burner-mining-drill": 10,
    "stone-furnace": 5,
    "wooden-chest": 5,
    "burner-inserter": 10,
    "transport-belt": 100,
}

# Empty inventory for freeplay/sandbox
EMPTY_STARTING_INVENTORY: dict[str, int] = {}
