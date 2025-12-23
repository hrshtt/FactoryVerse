import json
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Union
from functools import lru_cache
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Semantic Data Structures (Pure Information, No Game Logic) ---

@dataclass(frozen=True)
class KnowledgeIngredient:
    name: str
    amount: float
    type: str  # 'item' or 'fluid'

    def __repr__(self):
        return f"{self.amount}x {self.name}"

@dataclass(frozen=True)
class KnowledgeRecipe:
    name: str
    category: str
    ingredients: List[KnowledgeIngredient]
    products: List[KnowledgeIngredient]
    energy: float
    unlocked_by_tech: Optional[str] = None # Name of the tech

    @property
    def summary(self) -> str:
        ins = ", ".join([str(i) for i in self.ingredients])
        outs = ", ".join([str(p) for p in self.products])
        return f"Recipe['{self.name}'] ({self.category}): {ins} -> {outs}"

@dataclass(frozen=True)
class KnowledgeEntity:
    name: str
    type: str
    crafting_categories: List[str] # What categories can this machine craft?
    mining_speed: float = 0
    inventory_size: int = 0
    
    @property
    def capabilities(self) -> str:
        if self.crafting_categories:
            return f"Crafts: [{', '.join(self.crafting_categories)}]"
        if self.mining_speed > 0:
            return f"Mines resources (Speed: {self.mining_speed})"
        return "Storage/Structure"

@dataclass(frozen=True)
class KnowledgeTech:
    name: str
    prerequisites: List[str]
    unlocks_recipes: List[str]
    unit: Dict # Cost information

    @property
    def cost_summary(self) -> str:
        if not self.unit or 'ingredients' not in self.unit:
            return "Unknown Cost"
        
        ingredients = self.unit['ingredients']
        # ingredients can be a list of [name, count] or {name: name, amount: count}
        cost_str = []
        for ing in ingredients:
            if isinstance(ing, list):
                cost_str.append(f"{ing[1]}x {ing[0]}")
            elif isinstance(ing, dict):
                 cost_str.append(f"{ing.get('amount', 1)}x {ing.get('name', 'unknown')}")
        
        count = self.unit.get('count', 'X')
        time = self.unit.get('time', '?')
        
        return f"{count} cycles of [{', '.join(cost_str)}] ({time}s/cycle)"

# --- The Knowledge Engine ---

class Factoriopedia:
    """
    The Static Knowledge Base. 
    This is a Singleton. It does NOT require an RCON connection.
    It represents the 'Wiki' or 'Handbook' the agent references.
    """
    _instance = None
    _data = None # The raw loaded JSON

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Factoriopedia, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self._load_data()
        self._initialized = True

    def _load_data(self):
        from FactoryVerse.prototype_data import get_prototype_manager
        
        manager = get_prototype_manager()
        self._raw = manager.get_raw_data()
        logger.info(f"Loaded Factorio data from PrototypeDataManager")
        
        self.recipes: Dict[str, KnowledgeRecipe] = {}
        self.entities: Dict[str, KnowledgeEntity] = {}
        self.technologies: Dict[str, KnowledgeTech] = {}
        
        # Indices
        self.items_to_recipes: Dict[str, List[str]] = {} # Item Name -> List[Recipe Name] (Produced by)
        self.recipes_using_item: Dict[str, List[str]] = {} # Item Name -> List[Recipe Name] (Used in)
        self.tech_unlocks: Dict[str, str] = {} # Recipe Name -> Tech Name
        
        self._build_indices()

    def _build_indices(self):
        # 1. Parse Recipes & Build Reverse Index (Item -> Recipe)
        raw_recipes = self._raw.get("recipe", {})
        for name, data in raw_recipes.items():
            # Handle standard/expensive variations if present, default to normal/standard
            # Factorio data structure for recipes can be complex. 
            # Sometimes it's directly under the key, sometimes under 'normal' or 'expensive'
            r_data = data.get("normal", data) if "normal" in data else data
            
            # Skip if data is malformed
            if not isinstance(r_data, dict): continue

            # Parse Ingredients
            ings = []
            raw_ings = r_data.get("ingredients", [])
            for i in raw_ings:
                if isinstance(i, dict): 
                    ings.append(KnowledgeIngredient(i.get('name', 'unknown'), i.get('amount', 1), i.get('type', 'item')))
                elif isinstance(i, list) and len(i) >= 2: 
                    ings.append(KnowledgeIngredient(i[0], i[1], 'item'))
                
                # Index usage
                ing_name = i.get('name') if isinstance(i, dict) else i[0]
                if ing_name not in self.recipes_using_item:
                    self.recipes_using_item[ing_name] = []
                self.recipes_using_item[ing_name].append(name)

            # Parse Products
            prods = []
            if "results" in r_data:
                for res in r_data["results"]:
                    if isinstance(res, dict):
                         prods.append(KnowledgeIngredient(res.get('name', 'unknown'), res.get('amount', 1), res.get('type', 'item')))
                    elif isinstance(res, list) and len(res) >= 2:
                         prods.append(KnowledgeIngredient(res[0], res[1], 'item'))
            elif "result" in r_data:
                # Simple single result recipe
                count = r_data.get("result_count", 1)
                prods.append(KnowledgeIngredient(r_data["result"], count, "item"))

            # Create Knowledge Object
            rec = KnowledgeRecipe(
                name=name,
                category=r_data.get("category", "crafting"),
                ingredients=ings,
                products=prods,
                energy=float(r_data.get("energy_required", 0.5))
            )
            self.recipes[name] = rec
            
            # Indexing: How do I make this Item?
            for p in prods:
                if p.name not in self.items_to_recipes:
                    self.items_to_recipes[p.name] = []
                self.items_to_recipes[p.name].append(name)

        # 2. Parse Entities (Capabilities)
        # We need to scan multiple categories of entities
        entity_categories = ["assembling-machine", "furnace", "mining-drill", "rocket-silo"]
        for category in entity_categories:
            raw_cat_entities = self._raw.get(category, {})
            for name, data in raw_cat_entities.items():
                crafting_categories = data.get("crafting_categories", [])
                # Some entities like mining drills output resources but don't have crafting categories in the same way
                mining_speed = float(data.get("mining_speed", 0))
                
                ent = KnowledgeEntity(
                    name=name,
                    type=category,
                    crafting_categories=crafting_categories,
                    mining_speed=mining_speed,
                    inventory_size=int(data.get("inventory_size", 0) or 0)
                )
                self.entities[name] = ent

        # 3. Parse Tech (Unlock mapping)
        raw_techs = self._raw.get("technology", {})
        for t_name, t_data in raw_techs.items():
             effects = t_data.get("effects", [])
             unlocks = []
             for eff in effects:
                 if eff.get("type") == "unlock-recipe":
                     recipe_name = eff["recipe"]
                     unlocks.append(recipe_name)
                     # Update recipe with unlock info
                     if recipe_name in self.recipes:
                         # Use object.__setattr__ to bypass frozen check for this one-time init
                         object.__setattr__(self.recipes[recipe_name], 'unlocked_by_tech', t_name)
            
             tech = KnowledgeTech(
                 name=t_name,
                 prerequisites=t_data.get("prerequisites", []),
                 unlocks_recipes=unlocks,
                 unit=t_data.get("unit", {})
             )
             self.technologies[t_name] = tech


    # --- The LLM Tool Interface ---
    
    def lookup_item(self, item_name: str) -> str:
        """
        [Tool] Detailed 'Wiki Page' for an item.
        Explains how to make it, what it is used for, and relevant tech.
        """
        info = [f"=== FACTORIOPEDIA: {item_name} ==="]
        
        # 1. Provenance: How to make it
        making_recipes = self.items_to_recipes.get(item_name, [])
        if making_recipes:
            info.append("Produced by Recipes:")
            for r_name in making_recipes:
                rec = self.recipes.get(r_name)
                if rec:
                    tech_req = f" (Requires Tech: {rec.unlocked_by_tech})" if rec.unlocked_by_tech else " (Available: Start)"
                    info.append(f"  - {rec.summary}{tech_req}")
                    # Add info about where to craft it
                    crafting_machines = self._find_machines_for_category(rec.category)
                    if crafting_machines:
                        info.append(f"    Crafted in: {', '.join(crafting_machines[:3])}" + ("..." if len(crafting_machines)>3 else ""))
        else:
            info.append("Source: Raw Resource (Mine it) or specialized creation")

        # 2. Usage: What is it used for?
        using_recipes = self.recipes_using_item.get(item_name, [])
        if using_recipes:
            info.append(f"Used as ingredient in {len(using_recipes)} recipes, including:")
            for r_name in using_recipes: # Limit output
                 info.append(f"  - {r_name}")
            # if len(using_recipes) > 5:
            #     info.append(f"  ... and {len(using_recipes)-5} more.")
        
        return "\n".join(info)

    def find_crafting_machine(self, recipe_name: str) -> str:
        """
        [Tool] Finds which entity allows crafting a specific recipe.
        """
        if recipe_name not in self.recipes:
            return f"Unknown recipe: {recipe_name}"
        
        rec = self.recipes[recipe_name]
        cat = rec.category
        valid_entities = self._find_machines_for_category(cat)
        
        return f"Recipe '{recipe_name}' (Category: {cat}) can be crafted in: {', '.join(valid_entities)}"

    def _find_machines_for_category(self, category: str) -> List[str]:
        return [e.name for e in self.entities.values() if category in e.crafting_categories]

    def get_tech_tree_path(self, target_tech: str) -> str:
        """
        [Tool] Returns the dependency chain to reach a technology.
        """
        if target_tech not in self.technologies:
            return f"Unknown technology: {target_tech}"
        
        path = []
        visited = set()
        
        def dfs(current_name):
            if current_name in visited: return
            visited.add(current_name)
            
            tech = self.technologies.get(current_name)
            if not tech: return
            
            for prereq in tech.prerequisites:
                dfs(prereq)
            path.append(tech)

        dfs(target_tech)
        
        # Format output
        output = [f"Research Path for '{target_tech}':"]
        for step_idx, tech in enumerate(path):
            output.append(f"{step_idx+1}. {tech.name}")
            output.append(f"   Cost: {tech.cost_summary}")
            if tech.unlocks_recipes:
                output.append(f"   Unlocks: {', '.join(tech.unlocks_recipes)}")
        
        return "\n".join(output)

    def get_tech_unlocks(self, tech_name: str) -> str:
        """
        [Tool] What does this technology unlock?
        """
        if tech_name not in self.technologies:
             return f"Unknown technology: {tech_name}"
        
        tech = self.technologies[tech_name]
        if not tech.unlocks_recipes:
            return f"Technology '{tech_name}' unlocks no recipes (likely passive bonuses)."
            
        return f"Technology '{tech_name}' unlocks:\n" + "\n".join([f"- {r}" for r in tech.unlocks_recipes])

    # --- LLM Helper Methods ---

    def system_prompt(self) -> str:
        """
        [Helper] Returns a string describing how to use the Factoriopedia tools.
        Inject this into the agent's system prompt.
        """
        return """
## Factoriopedia Knowledge Tools
You have access to a static knowledge base called 'Factoriopedia'. Use these tools to plan your actions:

- `factoriopedia.lookup_item(item_name)`: Get recipes, usage, and tech requirements for an item.
- `factoriopedia.find_crafting_machine(recipe_name)`: Find which machine crafts a recipe.
- `factoriopedia.get_tech_tree_path(target_tech)`: Find the research path and costs for a technology.
- `factoriopedia.get_tech_unlocks(tech_name)`: See what a technology unlocks.

ALWAYS consult Factoriopedia before crafting complex items or researching technologies to understand dependencies.
"""

    # --- LLM Helper Methods ---

    def system_prompt(self) -> str:
        """
        [Helper] Returns a string describing how to use the Factoriopedia tools.
        Inject this into the agent's system prompt.
        """
        return """
## Factoriopedia Knowledge Tools
You have access to a static knowledge base called 'Factoriopedia'. Use these tools to plan your actions:

- `factoriopedia.lookup_item(item_name)`: Get recipes, usage, and tech requirements for an item.
- `factoriopedia.find_crafting_machine(recipe_name)`: Find which machine crafts a recipe.
- `factoriopedia.get_tech_tree_path(target_tech)`: Find the research path and costs for a technology.
- `factoriopedia.get_tech_unlocks(tech_name)`: See what a technology unlocks.

ALWAYS consult Factoriopedia before crafting complex items or researching technologies to understand dependencies.
"""

# Example usage for testing (will not run in final agent context unless called)
if __name__ == "__main__":
    wiki = Factoriopedia()
    # Test lookup
    print(wiki.lookup_item("iron-plate"))
    print("-" * 20)
    print(wiki.find_crafting_machine("iron-gear-wheel"))
    print("-" * 20)
    print(wiki.get_tech_tree_path("logistics-2"))