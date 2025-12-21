from dataclasses import dataclass
from typing import List, Dict, Any, Literal, Optional, get_args


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
    "parameters",
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
    _registry: Dict[str, BaseRecipe]  # Instance-level registry

    def __init__(self, data: List[Dict[str, Any]]):
        # self.recipes = [BaseRecipe(**recipe) for recipe in data]
        recipes = []
        for recipe in data:

            # Robust results parsing
            results_data = recipe.get("results")
            if results_data:
                results_list = [
                    Result(
                        name=r.get("name"),
                        count=r.get("amount", r.get("count", 1)),
                        type=r.get("type", "item")
                    ) for r in results_data
                ]
            else:
                # Infer from 'result' field or recipe name
                result_name = recipe.get("result", recipe["name"])
                # result_count usually comes with result, or defaults to 1
                result_count = recipe.get("result_count", 1) 
                results_list = [Result(name=result_name, count=result_count, type="item")]

            recipe = BaseRecipe(
                name=recipe["name"],
                type=recipe.get("type", "recipe"),
                ingredients=[
                    Ingredient(
                        name=i["name"],
                        type=i.get("type", "item"),
                        count=i.get("amount", i.get("count", 1))
                    ) for i in recipe["ingredients"]
                ],
                results=results_list,
                category=recipe.get("category", "crafting"),
                enabled=recipe.get("enabled", True),
            )
            # if recipe.name not in get_args(BasicRecipeName):
            #     print(f"[WARNING] Recipe {recipe.name} is not implemented in FactoryVerse. Skipping...")
            #     continue
            assert recipe.category in get_args(RecipeCategory), f"Invalid recipe category: {recipe.category}"
            recipes.append(recipe)
        
        self.recipes = recipes
        
        # Build instance-level registry
        self._registry = {}
        for recipe in self.recipes:
            self._registry[recipe.name] = recipe

    def __getitem__(self, recipe_name: str) -> BaseRecipe:
        """Get recipe by name.
        
        Args:
            recipe_name: Name of the recipe to retrieve
            
        Returns:
            BaseRecipe object
            
        Raises:
            KeyError: If recipe not found in registry
        """
        if recipe_name not in self._registry:
            available = list(self._registry.keys())[:10]  # Show first 10 for debugging
            raise KeyError(
                f"Recipe '{recipe_name}' not found in registry. "
                f"Registry has {len(self._registry)} recipes. "
                f"First few: {available}"
            )
        return self._registry[recipe_name]