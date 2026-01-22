"""Entity implementations package.

Each module contains related entity classes that share similar behavior.
All entities inherit from BaseEntity and use mixins for capabilities.
"""

# Containers
from .container import Container, WoodenChest, IronChest, SteelChest, ShipWreck

# Furnaces
from .furnace import Furnace, StoneFurnace, SteelFurnace, ElectricFurnace

# Processing machines
from .assembler import (
    ProcessingMachine,
    AssemblingMachine,
    ChemicalPlant,
    OilRefinery,
    Centrifuge,
    RocketSilo,
)

# Mining drills
from .mining_drill import ElectricMiningDrill, BurnerMiningDrill

# Pumpjack
from .pumpjack import Pumpjack

# Pumps
from .pump import OffshorePump, Pump

# Pipes and fluid storage
from .pipe import Pipe, PipeToGround, StorageTank

# Solar panel
from .solar_panel import SolarPanel

# Inserters
from .inserter import (
    Inserter,
    FastInserter,
    LongHandedInserter,
    FilterInserter,
    StackInserter,
    StackFilterInserter,
    BulkInserter,
    BurnerInserter,
)

# Transport belts
from .transport import (
    TransportBelt,
    FastTransportBelt,
    ExpressTransportBelt,
    UndergroundBelt,
    FastUndergroundBelt,
    ExpressUndergroundBelt,
    Splitter,
    FastSplitter,
    ExpressSplitter,
    Loader,
    FastLoader,
    ExpressLoader,
)

# Electric poles
from .electric_pole import (
    ElectricPole,
    SmallElectricPole,
    MediumElectricPole,
    BigElectricPole,
    Substation,
)

# New entities
from .lab import Lab
from .accumulator import Accumulator
from .generator import Boiler, SteamEngine, SteamTurbine

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
    # Pumpjack
    "Pumpjack",
    # Pumps
    "OffshorePump",
    "Pump",
    # Pipes and fluid storage
    "Pipe",
    "PipeToGround",
    "StorageTank",
    # Solar panel
    "SolarPanel",
    # Inserters
    "Inserter",
    "FastInserter",
    "LongHandedInserter",
    "FilterInserter",
    "StackInserter",
    "StackFilterInserter",
    "BulkInserter",
    "BurnerInserter",
    # Transport belts
    "TransportBelt",
    "FastTransportBelt",
    "ExpressTransportBelt",
    "UndergroundBelt",
    "FastUndergroundBelt",
    "ExpressUndergroundBelt",
    "Splitter",
    "FastSplitter",
    "ExpressSplitter",
    "Loader",
    "FastLoader",
    "ExpressLoader",
    # Electric poles
    "ElectricPole",
    "SmallElectricPole",
    "MediumElectricPole",
    "BigElectricPole",
    "Substation",
    # New entities
    "Lab",
    "Accumulator",
    "Boiler",
    "SteamEngine",
    "SteamTurbine",
]
