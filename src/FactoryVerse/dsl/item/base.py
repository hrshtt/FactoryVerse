import pydantic
from typing import List, Optional, Union, Any, Dict, Tuple, Literal


ItemSubgroup = Literal[
    "barrel",
    "intermediate-product",
    "module",
    "raw-material",
    "raw-resource",
    "science-pack",
    "terrain",
    "uranium-processing",
]
ItemName = Literal[
    "stone-brick",
    "wood",
    "coal",
    "stone",
    "iron-ore",
    "copper-ore",
    "iron-plate",
    "copper-plate",
    "copper-cable",
    "iron-stick",
    "iron-gear-wheel",
    "electronic-circuit",
    "steel-plate",
    "engine-unit",
    "solid-fuel",
    "rocket-fuel",
    "concrete",
    "refined-concrete",
    "hazard-concrete",
    "refined-hazard-concrete",
    "landfill",
    "uranium-ore",
    "advanced-circuit",
    "processing-unit",
    "sulfur",
    "barrel",
    "plastic-bar",
    "electric-engine-unit",
    "explosives",
    "battery",
    "flying-robot-frame",
    "low-density-structure",
    "nuclear-fuel",
    "rocket-part",
    "uranium-235",
    "uranium-238",
    "uranium-fuel-cell",
    "depleted-uranium-fuel-cell",
    "empty-module-slot",
    "science",
    "water-barrel",
    "sulfuric-acid-barrel",
    "crude-oil-barrel",
    "heavy-oil-barrel",
    "light-oil-barrel",
    "petroleum-gas-barrel",
    "lubricant-barrel",
]

PlaceableItemSubgroup = Literal[
    "belt",
    "energy",
    "energy-pipe-distribution",
    "extraction-machine",
    "inserter",
    "module",
    "production-machine",
    "smelting-machine",
    "storage",
]

PlaceableItemName = Literal[
    "wooden-chest",
    "stone-furnace",
    "burner-mining-drill",
    "electric-mining-drill",
    "burner-inserter",
    "inserter",
    "fast-inserter",
    "long-handed-inserter",
    "offshore-pump",
    "pipe",
    "boiler",
    "steam-engine",
    "small-electric-pole",
    "pipe-to-ground",
    "assembling-machine-1",
    "assembling-machine-2",
    "lab",
    "electric-furnace",
    "iron-chest",
    "big-electric-pole",
    "medium-electric-pole",
    "steel-furnace",
    "steel-chest",
    "solar-panel",
    "accumulator",
    "transport-belt",
    "fast-transport-belt",
    "express-transport-belt",
    "bulk-inserter",
    "assembling-machine-3",
    "underground-belt",
    "fast-underground-belt",
    "express-underground-belt",
    "splitter",
    "fast-splitter",
    "express-splitter",
    "loader",
    "fast-loader",
    "express-loader",
    "substation",
    "beacon",
    "storage-tank",
    "pump",
    "pumpjack",
    "oil-refinery",
    "chemical-plant",
    "nuclear-reactor",
    "centrifuge",
    "heat-exchanger",
    "steam-turbine",
    "heat-pipe",
]


class Item(pydantic.BaseModel):
    """Base class for all items."""

    name: Union[ItemName, PlaceableItemName]
    subgroup: Union[ItemSubgroup, PlaceableItemSubgroup]
    stack_size: Optional[int] = None


class RawMaterial(Item):
    subgroup: ItemSubgroup = "raw-material"


class RawResource(Item):
    subgroup: ItemSubgroup = "raw-resource"


class IntermediateProduct(Item):
    subgroup: ItemSubgroup = "intermediate-product"


class Module(Item):
    subgroup: ItemSubgroup = "module"


class SciencePack(Item):
    subgroup: ItemSubgroup = "science-pack"


class Fuel(Item):
    fuel_value: Optional[float] = None  
    fuel_category: Optional[Literal["chemical", "nuclear"]] = None
    burnt_result: Optional[ItemName] = None
    fuel_acceleration_multiplier: Optional[float] = None
    fuel_top_speed_multiplier: Optional[float] = None


class PlaceAsEntityItem(Item):
    place_result: PlaceableItemName

