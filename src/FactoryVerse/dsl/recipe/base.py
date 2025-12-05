from dataclasses import dataclass
from typing import List, Dict, Any, Literal, ClassVar, Optional


BasicRecipeName = Literal[
    "bulk-inserter",
    "basic-oil-processing",
    "advanced-oil-processing",
    "coal-liquefaction",
    "heavy-oil-cracking",
    "light-oil-cracking",
    "sulfuric-acid",
    "plastic-bar",
    "solid-fuel-from-light-oil",
    "solid-fuel-from-petroleum-gas",
    "solid-fuel-from-heavy-oil",
    "sulfur",
    "lubricant",
    "wooden-chest",
    "iron-stick",
    "stone-furnace",
    "boiler",
    "steam-engine",
    "iron-gear-wheel",
    "electronic-circuit",
    "transport-belt",
    "electric-mining-drill",
    "burner-mining-drill",
    "inserter",
    "fast-inserter",
    "long-handed-inserter",
    "burner-inserter",
    "pipe",
    "offshore-pump",
    "copper-cable",
    "small-electric-pole",
    "radar",
    "pipe-to-ground",
    "assembling-machine-1",
    "repair-pack",
    "automation-science-pack",
    "logistic-science-pack",
    "lab",
    "stone-wall",
    "assembling-machine-2",
    "splitter",
    "underground-belt",
    "car",
    "engine-unit",
    "iron-chest",
    "big-electric-pole",
    "medium-electric-pole",
    "steel-furnace",
    "gate",
    "steel-chest",
    "fast-underground-belt",
    "fast-splitter",
    "landfill",
    "fast-transport-belt",
    "solar-panel",
    "copper-plate",
    "iron-plate",
    "stone-brick",
    "steel-plate",
    "cliff-explosives",
    "rocket",
    "explosive-rocket",
    "express-transport-belt",
    "assembling-machine-3",
    "rocket-launcher",
    "chemical-science-pack",
    "military-science-pack",
    "production-science-pack",
    "utility-science-pack",
    "express-underground-belt",
    "express-splitter",
    "advanced-circuit",
    "processing-unit",
    "passive-provider-chest",
    "active-provider-chest",
    "storage-chest",
    "buffer-chest",
    "requester-chest",
    "rocket-silo",
    "cargo-landing-pad",
    "substation",
    "accumulator",
    "electric-furnace",
    "beacon",
    "pumpjack",
    "oil-refinery",
    "electric-engine-unit",
    "explosives",
    "battery",
    "pump",
    "chemical-plant",
    "low-density-structure",
    "rocket-fuel",
    "rocket-part",
    "satellite",
    "nuclear-reactor",
    "centrifuge",
    "uranium-processing",
    "kovarex-enrichment-process",
    "nuclear-fuel",
    "nuclear-fuel-reprocessing",
    "uranium-fuel-cell",
    "heat-exchanger",
    "heat-pipe",
    "steam-turbine",
]

RecipeCategory = Literal[
    "advanced-crafting",
    "centrifuging",
    "chemistry",
    "crafting",
    "crafting-with-fluid",
    "oil-processing",
    "rocket-building",
    "smelting",
]


@dataclass
class Ingredient:
    name: str
    count: int
    type: Literal["item", "fluid"]


@dataclass
class Result:
    name: str
    count: int
    type: Literal["item", "fluid"]

@dataclass
class BaseRecipe:
    name: str
    type: str
    ingredients: List[Ingredient]
    category: RecipeCategory
    enabled: bool
    results: List[Result]
    
    def is_hand_craftable(self) -> bool:
        """Check if a recipe is hand-craftable."""
        return self.category == "crafting"


@dataclass
class Recipes:
    recipes: List[BaseRecipe]
    
    _registry: ClassVar[Optional[Dict[str, BaseRecipe]]] = None  # Class-level registry

    def __init__(self, data: List[Dict[str, Any]]):
        # self.recipes = [BaseRecipe(**recipe) for recipe in data]
        recipes = []
        for recipe in data:
            recipe = BaseRecipe(
                name=recipe["name"],
                type=recipe["type"],
                ingredients=[Ingredient(**ingredient) for ingredient in recipe["ingredients"]],
                results=[Result(**result) for result in recipe["results"]],
                category=recipe.get("category", "crafting"),
                enabled=recipe.get("enabled", True),
            )
            if recipe.name not in BasicRecipeName:
                print(f"[WARNING] Recipe {recipe.name} is not implemented in FactoryVerse. Skipping...")
                continue
            assert recipe.category in RecipeCategory, f"Invalid recipe category: {recipe.category}"
            recipes.append(recipe)
        # Build registry
        if Recipes._registry is None:
            Recipes._registry = {}
        for recipe in self.recipes:
            Recipes._registry[recipe.name] = recipe

    @classmethod
    def __getitem__(cls, recipe_name: BasicRecipeName) -> BaseRecipe:
        """Get recipe by name with type safety."""
        if cls._registry is None:
            raise ValueError("Recipes registry not initialized. Create a Recipes instance first.")
        if recipe_name not in cls._registry:
            raise KeyError(f"Recipe '{recipe_name}' not found in registry")
        return cls._registry[recipe_name]