from dataclasses import dataclass
from typing import List, Dict, Any, Literal, Optional, get_args, Union, TYPE_CHECKING
from FactoryVerse.dsl.mixins import FactoryContextMixin

if TYPE_CHECKING:
    from FactoryVerse.dsl.agent import PlayingFactory


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
class BaseRecipe(FactoryContextMixin):
    """Base class for all recipes. Contains data properties.
    
    **For Agents**: Use this to understand what ingredients are needed for a recipe.
    If the recipe is hand-craftable (category='crafting'), it will be a 
    HandCraftableRecipe and you can call .craft() on it.
    """
    name: str
    type: str
    ingredients: List[Ingredient]
    category: RecipeCategory
    enabled: bool
    results: List[Result]
    
    def is_hand_craftable(self) -> bool:
        """Check if a recipe is hand-craftable."""
        return self.category == "crafting"
    
    def __repr__(self) -> str:
        ins = ", ".join([f"{i.count}x {i.name}" for i in self.ingredients])
        outs = ", ".join([f"{r.count}x {r.name}" for r in self.results])
        return f"Recipe({self.name})[{self.category}]: {ins} -> {outs}"


class HandCraftableRecipe(BaseRecipe):
    """A recipe that can be crafted by the agent's own hands."""
    
    async def craft(self, count: int = 1, timeout: Optional[int] = None):
        """Craft this recipe using the agent's hands.
        
        **For Agents**: Only works for category='crafting' recipes.
        
        Args:
            count: Number of times to craft
            timeout: Optional timeout for the async action
        """
        return await self._factory.crafting.craft(self.name, count, timeout)


class Recipes:
    """Registry for all recipes available in the game."""
    
    def __init__(self, data: List[Dict[str, Any]]):
        self._registry: Dict[str, BaseRecipe] = {}
        
        for recipe_data in data:
            # Robust results parsing
            results_data = recipe_data.get("results")
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
                result_name = recipe_data.get("result", recipe_data["name"])
                result_count = recipe_data.get("result_count", 1) 
                results_list = [Result(name=result_name, count=result_count, type="item")]

            # Ingredients parsing
            ingredients = [
                Ingredient(
                    name=i["name"],
                    type=i.get("type", "item"),
                    count=i.get("amount", i.get("count", 1))
                ) for i in recipe_data["ingredients"]
            ]

            category = recipe_data.get("category", "crafting")
            
            # Determine class based on category
            recipe_class = HandCraftableRecipe if category == "crafting" else BaseRecipe
            
            recipe_obj = recipe_class(
                name=recipe_data["name"],
                type=recipe_data.get("type", "recipe"),
                ingredients=ingredients,
                results=results_list,
                category=category,
                enabled=recipe_data.get("enabled", True),
            )
            
            # if recipe_obj.name not in get_args(BasicRecipeName):
            #     print(f"[WARNING] Recipe {recipe_obj.name} is not implemented in FactoryVerse. Skipping...")
            #     continue
            assert recipe_obj.category in get_args(RecipeCategory), f"Invalid recipe category: {recipe_obj.category}"
            self._registry[recipe_obj.name] = recipe_obj

    def __getitem__(self, recipe_name: str) -> Union[HandCraftableRecipe, BaseRecipe]:
        """Get recipe by name using index access.
        
        **For Agents**: Use crafting['recipe-name'] to get a recipe object.
        Example: 
            # Hand-craft gear wheels
            await crafting['iron-gear-wheel'].craft(5)
            
            # Check ingredients for iron plate (cannot be handcrafted)
            ingredients = crafting['iron-plate'].ingredients
        """
        if recipe_name not in self._registry:
            # Try to provide helpful error with suggestions
            available = list(self._registry.keys())[:10]
            raise KeyError(
                f"Recipe '{recipe_name}' not found. "
                f"Available recipes include: {', '.join(available)}..."
            )
        return self._registry[recipe_name]

    def __iter__(self):
        return iter(self._registry.values())

    def __len__(self) -> int:
        return len(self._registry)