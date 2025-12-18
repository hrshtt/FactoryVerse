"""Generate technology and recipe information for agent system prompts.

This module provides concise, actionable tech/recipe information for the agent,
focusing on what's immediately available and actionable.
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class TechInfo:
    """Concise technology information for agent."""
    name: str
    has_trigger: bool
    trigger_desc: Optional[str]
    science_packs: List[tuple[str, int]]  # [(name, amount), ...]
    cycles: int
    unlocks: List[str]
    can_research: bool


@dataclass
class RecipeInfo:
    """Concise recipe information for agent."""
    name: str
    ingredients: List[tuple[str, int]]
    products: List[tuple[str, int]]
    time: float
    category: str


class TechRecipePromptGenerator:
    """Generate concise tech/recipe prompts for agent."""
    
    def __init__(self, data_dump_path: Optional[Path] = None):
        """Initialize generator.
        
        Args:
            data_dump_path: Path to factorio-data-dump.json
        """
        if data_dump_path is None:
            # Default to repo root
            data_dump_path = Path(__file__).parent.parent.parent.parent / "factorio-data-dump.json"
        
        self.data_dump_path = data_dump_path
        self.data = self._load_data()
        self._build_recipe_tech_mapping()
    
    def _load_data(self) -> Dict[str, Any]:
        """Load factorio data dump."""
        with open(self.data_dump_path, 'r') as f:
            return json.load(f)
    
    def _build_recipe_tech_mapping(self):
        """Build mapping from recipe to unlocking technology."""
        self.recipe_to_tech: Dict[str, str] = {}
        for tech_name, tech_data in self.data['technology'].items():
            for effect in tech_data.get('effects', []):
                if effect.get('type') == 'unlock-recipe':
                    self.recipe_to_tech[effect['recipe']] = tech_name
    
    def get_available_technologies(self, researched: List[str]) -> List[TechInfo]:
        """Get technologies available to research now.
        
        Args:
            researched: List of already researched technology names
            
        Returns:
            List of TechInfo for available technologies
        """
        available = []
        
        for tech_name, tech_data in self.data['technology'].items():
            # Skip if already researched or hidden
            if tech_name in researched or tech_data.get('hidden', False):
                continue
            
            # Check prerequisites
            prereqs = tech_data.get('prerequisites', [])
            if not all(p in researched for p in prereqs):
                continue
            
            # Parse technology
            trigger = tech_data.get('research_trigger')
            has_trigger = trigger is not None
            
            # Trigger description
            trigger_desc = None
            if has_trigger:
                trigger_type = trigger.get('type')
                if trigger_type == 'craft-item':
                    trigger_desc = f"Craft {trigger['count']}x {trigger['item']}"
                elif trigger_type == 'mine-entity':
                    trigger_desc = f"Mine {trigger['count']}x {trigger['item']}"
            
            # Science packs
            unit = tech_data.get('unit', {})
            science_packs = [(ing[0], ing[1]) for ing in unit.get('ingredients', [])]
            cycles = unit.get('count', 0)
            
            # Unlocks
            unlocks = [e['recipe'] for e in tech_data.get('effects', []) if e.get('type') == 'unlock-recipe']
            
            available.append(TechInfo(
                name=tech_name,
                has_trigger=has_trigger,
                trigger_desc=trigger_desc,
                science_packs=science_packs,
                cycles=cycles,
                unlocks=unlocks,
                can_research=True
            ))
        
        return available
    
    def get_enabled_recipes(self, enabled_recipe_names: List[str]) -> List[RecipeInfo]:
        """Get information for enabled recipes.
        
        Args:
            enabled_recipe_names: List of enabled recipe names
            
        Returns:
            List of RecipeInfo for enabled recipes
        """
        recipes = []
        
        for recipe_name in enabled_recipe_names:
            recipe_data = self.data['recipe'].get(recipe_name)
            if not recipe_data:
                continue
            
            # Parse ingredients
            ingredients = []
            for ing in recipe_data.get('ingredients', []):
                if isinstance(ing, dict):
                    ingredients.append((ing['name'], ing.get('amount', 1)))
                elif isinstance(ing, list):
                    ingredients.append((ing[0], ing[1]))
            
            # Parse products
            products = []
            if 'results' in recipe_data:
                for prod in recipe_data['results']:
                    if isinstance(prod, dict):
                        products.append((prod['name'], prod.get('amount', 1)))
                    elif isinstance(prod, list):
                        products.append((prod[0], prod[1]))
            elif 'result' in recipe_data:
                products.append((recipe_data['result'], recipe_data.get('result_count', 1)))
            
            recipes.append(RecipeInfo(
                name=recipe_name,
                ingredients=ingredients,
                products=products,
                time=recipe_data.get('energy_required', 0.5),
                category=recipe_data.get('category', 'crafting')
            ))
        
        return recipes
    
    def generate_tech_section(self, researched: List[str], limit: int = 10) -> str:
        """Generate markdown section for available technologies.
        
        Args:
            researched: List of researched technology names
            limit: Maximum number of technologies to show
            
        Returns:
            Markdown formatted technology section
        """
        available = self.get_available_technologies(researched)
        
        if not available:
            return "## Available Technologies\n\n*No technologies available to research*\n"
        
        lines = [f"## Available Technologies ({len(available)} total)\n"]
        
        # Show up to limit
        for tech in available[:limit]:
            lines.append(f"### {tech.name}")
            
            if tech.has_trigger:
                lines.append(f"- **Unlock**: {tech.trigger_desc} (automatic)")
            else:
                lines.append(f"- **Research**: {tech.cycles} cycles")
                if tech.science_packs:
                    packs_str = ", ".join([f"{amt}x {name}" for name, amt in tech.science_packs])
                    lines.append(f"- **Packs/cycle**: {packs_str}")
                    total_str = ", ".join([f"{amt * tech.cycles}x {name}" for name, amt in tech.science_packs])
                    lines.append(f"- **Total packs**: {total_str}")
            
            if tech.unlocks:
                unlocks_str = ", ".join(tech.unlocks[:3])
                if len(tech.unlocks) > 3:
                    unlocks_str += f" (+{len(tech.unlocks) - 3} more)"
                lines.append(f"- **Unlocks**: {unlocks_str}")
            
            lines.append("")
        
        if len(available) > limit:
            lines.append(f"*...and {len(available) - limit} more technologies*\n")
        
        return "\n".join(lines)
    
    def generate_recipe_section(self, enabled_recipe_names: List[str], limit: int = 15) -> str:
        """Generate markdown section for enabled recipes.
        
        Args:
            enabled_recipe_names: List of enabled recipe names
            limit: Maximum number of recipes to show
            
        Returns:
            Markdown formatted recipe section
        """
        recipes = self.get_enabled_recipes(enabled_recipe_names)
        
        if not recipes:
            return "## Available Recipes\n\n*No recipes available*\n"
        
        lines = [f"## Available Recipes ({len(recipes)} total)\n"]
        
        # Show up to limit
        for recipe in recipes[:limit]:
            ing_str = " + ".join([f"{amt}x {name}" for name, amt in recipe.ingredients])
            prod_str = " + ".join([f"{amt}x {name}" for name, amt in recipe.products])
            lines.append(f"- **{recipe.name}**: {ing_str} → {prod_str} ({recipe.time}s)")
        
        if len(recipes) > limit:
            lines.append(f"\n*...and {len(recipes) - limit} more recipes*\n")
        
        return "\n".join(lines)
    
    def generate_combined_prompt(
        self,
        researched: List[str],
        enabled_recipes: List[str],
        tech_limit: int = 10,
        recipe_limit: int = 15
    ) -> str:
        """Generate combined tech + recipe prompt section.
        
        Args:
            researched: List of researched technology names
            enabled_recipes: List of enabled recipe names
            tech_limit: Max technologies to show
            recipe_limit: Max recipes to show
            
        Returns:
            Markdown formatted combined section
        """
        sections = []
        sections.append("# Technology & Recipes\n")
        sections.append(self.generate_tech_section(researched, tech_limit))
        sections.append(self.generate_recipe_section(enabled_recipes, recipe_limit))
        
        return "\n".join(sections)
