"""Generate categorical reference lists for LLM guidance."""
import json
from typing import Dict, List
from pathlib import Path


class CategoricalReferenceGenerator:
    """Generate categorical reference lists from filtered prototype data."""
    
    def __init__(self):
        """Initialize generator using shared prototype data."""
        from FactoryVerse.prototype_data import get_prototype_manager
        from FactoryVerse.filtering.filters import get_filter_config
        
        manager = get_prototype_manager()
        self.data = manager.get_raw_data()
        self.filters = get_filter_config()
    
    def generate_fuel_reference(self) -> str:
        """Generate fuel items reference (filtered by item config)."""
        fuel_by_category = {}
        
        # Get filtered items
        filtered_items = set(self.filters.filter_items(self.data))
        
        if 'item' in self.data:
            for item_name, item_data in self.data['item'].items():
                # Skip if not in filtered list
                if item_name not in filtered_items:
                    continue
                
                if 'fuel_value' in item_data:
                    fuel_cat = item_data.get('fuel_category', 'chemical')
                    if fuel_cat not in fuel_by_category:
                        fuel_by_category[fuel_cat] = []
                    fuel_by_category[fuel_cat].append(item_name)
        
        lines = ["## Fuel Items\n\n"]
        for category in sorted(fuel_by_category.keys()):
            items = sorted(fuel_by_category[category])
            lines.append(f"**{category}**: {', '.join(items)}\n\n")
        
        return "".join(lines)
    
    def generate_recipe_reference(self) -> str:
        """Generate recipe categories reference (filtered by recipe config)."""
        recipes_by_category = {}
        
        # Get filtered recipes
        filtered_recipes = set(self.filters.filter_recipes(self.data))
        
        if 'recipe' in self.data:
            for recipe_name, recipe_data in self.data['recipe'].items():
                # Skip if not in filtered list
                if recipe_name not in filtered_recipes:
                    continue
                
                category = recipe_data.get('category', 'crafting')
                if category not in recipes_by_category:
                    recipes_by_category[category] = []
                recipes_by_category[category].append(recipe_name)
        
        lines = ["## Recipes\n\n"]
        
        # Handcraftable first
        if 'crafting' in recipes_by_category:
            handcraft = sorted(recipes_by_category['crafting'])
            lines.append(f"**Handcraftable (crafting)**: {len(handcraft)} recipes\n\n")
            # Show ALL handcraftable recipes (they're already filtered by config)
            lines.append(f"{', '.join(handcraft)}\n\n")
        
        # Machine-only categories
        if len(recipes_by_category) > 1:  # More than just 'crafting'
            lines.append("**Machine-Only Categories**:\n\n")
            for category in sorted(recipes_by_category.keys()):
                if category == 'crafting':
                    continue
                recipes = sorted(recipes_by_category[category])
                lines.append(f"- **{category}**: {len(recipes)} recipes\n")
                lines.append(f"  - {', '.join(recipes)}\n")
        
        return "".join(lines)
    
    def generate_item_subgroups_reference(self) -> str:
        """Generate item subgroups reference (filtered by item config)."""
        items_by_subgroup = {}
        
        # Get filtered items
        filtered_items = set(self.filters.filter_items(self.data))
        
        if 'item' in self.data:
            for item_name, item_data in self.data['item'].items():
                # Skip if not in filtered list
                if item_name not in filtered_items:
                    continue
                
                subgroup = item_data.get('subgroup', 'other')
                if subgroup not in items_by_subgroup:
                    items_by_subgroup[subgroup] = []
                items_by_subgroup[subgroup].append(item_name)
        
        lines = ["## Item Subgroups\n\n"]
        
        for subgroup in sorted(items_by_subgroup.keys()):
            items = sorted(items_by_subgroup[subgroup])
            lines.append(f"**{subgroup}**: {', '.join(items)}\n\n")
        
        return "".join(lines)
    
    def generate_combined_reference(self) -> str:
        """Generate complete categorical reference."""
        lines = [
            "# Categorical Game References\n\n",
            "This section provides categorical lists of game elements to guide your actions.\n\n",
            self.generate_fuel_reference(),
            self.generate_recipe_reference(),
            "\n",
            self.generate_item_subgroups_reference(),
        ]
        return "".join(lines)

