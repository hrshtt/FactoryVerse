"""Entity implementations package.

Each module contains related entity classes that share similar behavior.
All entities inherit from BaseEntity and use mixins for capabilities.
"""

from .container import Container, WoodenChest, IronChest, SteelChest, ShipWreck
from .furnace import Furnace, StoneFurnace, SteelFurnace, ElectricFurnace
from .assembler import (
    ProcessingMachine,
    AssemblingMachine,
    ChemicalPlant,
    OilRefinery,
    Centrifuge,
    RocketSilo,
)
from .mining_drill import ElectricMiningDrill, BurnerMiningDrill

__all__ = [
    # Containers
    "Container",
    "WoodenChest",
    "IronChest",
    "SteelChest",
    "ShipWreck",
    # Furnaces
    "Furnace",
    "StoneFurnace",
    "SteelFurnace",
    "ElectricFurnace",
    # Processing machines
    "ProcessingMachine",
    "AssemblingMachine",
    "ChemicalPlant",
    "OilRefinery",
    "Centrifuge",
    "RocketSilo",
    # Mining drills
    "ElectricMiningDrill",
    "BurnerMiningDrill",
]
