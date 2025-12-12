from dataclasses import dataclass
from typing import Literal, Optional, Union, List, Dict, Any

from dataclasses import dataclass, field

TechnologyName = Literal[
    "steam-power",
    "electronics",
    "automation-science-pack",
    "electric-mining-drill",
    "repair-pack",
    "radar",
    "bulk-inserter",
    "automation",
    "automation-2",
    "logistic-science-pack",
    "steel-processing",
    "military",
    "military-2",
    "fast-inserter",
    "logistics",
    "automobilism",
    "lamp",
    "solar-energy",
    "electric-energy-distribution-1",
    "advanced-material-processing",
    "engine",
    "landfill",
    "logistics-2",
    "stone-wall",
    "gate",
    "chemical-science-pack",
    "military-science-pack",
    "production-science-pack",
    "utility-science-pack",
    "military-3",
    "military-4",
    "uranium-ammo",
    "automation-3",
    "explosives",
    "cliff-explosives",
    "advanced-circuit",
    "processing-unit",
    "logistics-3",
    "rocketry",
    "explosive-rocketry",
    "rocket-fuel",
    "low-density-structure",
    "rocket-silo",
    "electric-energy-distribution-2",
    "electric-energy-accumulators",
    "advanced-material-processing-2",
    "effect-transmission",
    "lubricant",
    "electric-engine",
    "battery",
    "logistic-system",
    "fluid-handling",
    "oil-gathering",
    "oil-processing",
    "advanced-oil-processing",
    "coal-liquefaction",
    "sulfur-processing",
    "plastics",
    "defender",
    "distractor",
    "destroyer",
    "uranium-processing",
    "nuclear-power",
    "kovarex-enrichment-process",
    "nuclear-fuel-reprocessing",
    "artillery",
    "circuit-network",
]


@dataclass
class Ingredient:
    name: str
    amount: float
    type: str  # 'item' or 'fluid'

    def __repr__(self):
        return f"{self.amount}x {self.name}"


@dataclass
class Recipe:
    name: str
    ingredients: List[Ingredient]
    products: List[Ingredient]
    energy: float
    category: str = "crafting"

    @property
    def summary(self) -> str:
        """Returns a string optimized for LLM token efficiency."""
        ins = ", ".join([str(i) for i in self.ingredients])
        outs = ", ".join([str(p) for p in self.products])
        return f"Recipe[{self.name}]: Input({ins}) -> Output({outs})"


@dataclass
class Technology:
    name: str
    friendly_name: str
    description: str
    prerequisites: List[str]  # IDs of parent techs
    unlocks_recipes: List[str]  # IDs of recipes
    science_packs: List[Ingredient]
    count: int  # How many cycles
    time: int  # Time per cycle

    # Using field(repr=False) prevents massive recursive dumps when printing
    _graph_ref: "TechTree" = field(repr=False, default=None)

    @property
    def cost_summary(self) -> str:
        packs = ", ".join([f"{i.name}" for i in self.science_packs])
        return f"{self.count} cycles of [{packs}]"

    @property
    def is_essential(self) -> bool:
        """Heuristic to determine if this is a critical path tech based on name."""
        # This can be expanded based on your filtering logic
        keywords = [
            "logistics",
            "automation",
            "processing",
            "rocket",
            "science",
            "electronics",
            "engine",
            "fluid",
        ]
        return any(k in self.name for k in keywords)

    def get_parent_techs(self) -> List["Technology"]:
        """Resolves string IDs to actual objects."""
        if not self._graph_ref:
            return []
        return [
            self._graph_ref.get_tech(p)
            for p in self.prerequisites
            if self._graph_ref.get_tech(p)
        ]

    def to_prompt_format(self) -> str:
        """
        Creates a prompt-ready description for the LLM.
        """
        prereqs = ", ".join(self.prerequisites) if self.prerequisites else "None"
        unlocks = (
            ", ".join(self.unlocks_recipes)
            if self.unlocks_recipes
            else "Passive Bonuses"
        )

        return (
            f"TECH: {self.name}\n"
            f"  - Cost: {self.cost_summary}\n"
            f"  - Requires: {prereqs}\n"
            f"  - Unlocks: {unlocks}\n"
            f"  - Description: {self.description}"
        )


class TechTree:
    def __init__(self):
        self.technologies: Dict[str, Technology] = {}
        self.recipes: Dict[str, Recipe] = {}

    def add_tech(self, tech: Technology):
        tech._graph_ref = self
        self.technologies[tech.name] = tech

    def add_recipe(self, recipe: Recipe):
        self.recipes[recipe.name] = recipe

    def get_tech(self, name: str) -> Optional[Technology]:
        return self.technologies.get(name)

    def get_recipe(self, name: str) -> Optional[Recipe]:
        return self.recipes.get(name)

    def calculate_research_path(self, target_tech_name: str) -> List[Technology]:
        """
        Returns a topologically sorted list of technologies required to reach the target.
        This allows the LLM to see the 'Step-by-Step' plan instantly.
        """
        if target_tech_name not in self.technologies:
            raise ValueError(f"Technology {target_tech_name} not found.")

        visited = set()
        plan = []

        def dfs(current_name):
            if current_name in visited:
                return

            tech = self.get_tech(current_name)
            if not tech:
                return  # Base case or missing data handle

            # DFS on prerequisites first
            for prereq in tech.prerequisites:
                dfs(prereq)

            visited.add(current_name)
            plan.append(tech)

        dfs(target_tech_name)
        return plan

    @classmethod
    def from_json_dump(cls, data: dict, filter_config: dict = None) -> "TechTree":
        tree = cls()

        # 1. Load Recipes (Simplistic loader)
        # In a real scenario, you have to handle "normal" vs "expensive" blocks
        raw_recipes = data.get("recipe", {})
        for key, item in raw_recipes.items():
            # Factorio data structure is messy. This is a simplified parser.
            # Often data is in item['normal'] or item['expensive'] or directly in item
            recipe_data = item.get("normal", item) if "normal" in item else item

            ingredients = []
            for ing in recipe_data.get("ingredients", []):
                # Ingredients can be {"name": "x", "amount": 1} or ["x", 1]
                if isinstance(ing, dict):
                    ingredients.append(
                        Ingredient(
                            ing["name"], ing.get("amount", 1), ing.get("type", "item")
                        )
                    )
                elif isinstance(ing, list):
                    ingredients.append(Ingredient(ing[0], ing[1], "item"))

            products = []
            # 'result' (single) vs 'results' (multiple)
            if "results" in recipe_data:
                for prod in recipe_data["results"]:
                    # Products can be complex dicts with probability
                    if isinstance(prod, dict):
                        products.append(
                            Ingredient(
                                prod["name"],
                                prod.get("amount", 1),
                                prod.get("type", "item"),
                            )
                        )
                    elif isinstance(prod, list):
                        products.append(Ingredient(prod[0], prod[1], "item"))
            elif "result" in recipe_data:
                products.append(
                    Ingredient(
                        recipe_data["result"],
                        recipe_data.get("result_count", 1),
                        "item",
                    )
                )

            r = Recipe(
                name=item["name"],
                ingredients=ingredients,
                products=products,
                energy=recipe_data.get("energy_required", 0.5),
                category=item.get("category", "crafting"),
            )
            tree.add_recipe(r)

        # 2. Load Technologies
        raw_techs = data.get("technology", {})

        skip_names = filter_config.get("skip_names", []) if filter_config else []

        for key, item in raw_techs.items():
            # Apply basic filters
            if item.get("hidden", False):
                continue
            if any(s in item["name"] for s in skip_names):
                continue

            # Parse Ingredients (Science packs)
            unit = item.get("unit", {})
            ingredients = []
            for ing in unit.get("ingredients", []):
                ingredients.append(Ingredient(ing[0], ing[1], "item"))

            # Parse Effects to find Unlocked Recipes
            unlocked_recipes = []
            if "effects" in item:
                for eff in item["effects"]:
                    if eff.get("type") == "unlock-recipe":
                        unlocked_recipes.append(eff["recipe"])

            t = Technology(
                name=item["name"],
                friendly_name=(
                    item.get("localised_name", [item["name"]])[0]
                    if isinstance(item.get("localised_name"), list)
                    else item["name"]
                ),
                description=str(item.get("localised_description", "")),
                prerequisites=item.get("prerequisites", []),
                unlocks_recipes=unlocked_recipes,
                science_packs=ingredients,
                count=unit.get(
                    "count", 0
                ),  # formula handling is complex, defaulting to count
                time=unit.get("time", 30),
            )
            tree.add_tech(t)

        return tree
