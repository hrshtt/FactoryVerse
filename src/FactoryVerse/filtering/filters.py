"""Filtering system - single source of truth for entity/recipe/item filtering.

This module provides the FilterConfig class which loads fv_filters.yaml
and applies filtering logic to Factorio prototype data.

All filtering across the codebase (DuckDB schema, categorical references,
Lua mod) should use this single source of truth.
"""

import yaml
from pathlib import Path
from typing import Dict, List, Set, Optional
import fnmatch


def _find_repo_root() -> Path:
    """Find repository root by looking for fv_filters.yaml.
    
    Returns:
        Path to repository root
    """
    current = Path(__file__).resolve().parent
    
    # Walk up directory tree
    for _ in range(10):
        if (current / "fv_filters.yaml").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    
    # Fallback to current directory
    return Path.cwd()


class FilterConfig:
    """Load and apply filtering configuration from fv_filters.yaml."""
    
    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize filter config.
        
        Args:
            config_file: Path to fv_filters.yaml configuration file.
                        If None, auto-detects at repository root.
            
        Raises:
            FileNotFoundError: If config file doesn't exist
        """
        if config_file is None:
            # Auto-detect at repo root
            repo_root = _find_repo_root()
            config_path = repo_root / "fv_filters.yaml"
        else:
            config_path = Path(config_file)
        
        if not config_path.exists():
            raise FileNotFoundError(
                f"Filter config not found: {config_path}\n"
                f"Searched in: {config_path.parent}"
            )
        
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
    
    def _matches_pattern(self, name: str, patterns: List[str]) -> bool:
        """
        Check if name matches any glob pattern.
        
        Args:
            name: Entity/recipe/item name to check
            patterns: List of glob patterns (e.g., ["crash-site-*", "parameter-*"])
            
        Returns:
            True if name matches any pattern
        """
        return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)
    
    def _filter_by_subgroup(self, 
                           items: Dict[str, dict], 
                           include_subgroups: List[str],
                           exclude_subgroups: List[str]) -> Set[str]:
        """
        Filter items by subgroup.
        
        Args:
            items: Dict of item_name -> item_data
            include_subgroups: List of subgroups to include
            exclude_subgroups: List of subgroups to exclude
            
        Returns:
            Set of item names that pass the filter
        """
        result = set()
        
        for item_name, item_data in items.items():
            subgroup = item_data.get('subgroup', '')
            
            # Check exclusions first
            if subgroup in exclude_subgroups:
                continue
            
            # Check inclusions
            if subgroup in include_subgroups:
                result.add(item_name)
        
        return result
    
    def filter_entities(self, prototype_data: dict) -> List[str]:
        """
        Filter entities based on config.
        
        Args:
            prototype_data: Full prototype data dump from Factorio
            
        Returns:
            Sorted list of entity names that pass the filter
        """
        entity_config = self.config['entities']
        
        # Start with explicit includes (if any)
        if entity_config['include']:
            result = set(entity_config['include'])
        else:
            # Collect all entities from included subgroups
            result = set()
            
            # Iterate over all entity categories
            for category, entities in prototype_data.items():
                if not isinstance(entities, dict):
                    continue
                
                # Filter by subgroup
                filtered = self._filter_by_subgroup(
                    entities,
                    entity_config['include_subgroups'],
                    entity_config['exclude_subgroups']
                )
                result.update(filtered)
        
        # Apply explicit exclusions (glob patterns)
        exclude_patterns = entity_config['exclude']
        result = {name for name in result 
                 if not self._matches_pattern(name, exclude_patterns)}
        
        return sorted(result)
    
    def filter_recipes(self, prototype_data: dict) -> List[str]:
        """
        Filter recipes based on config.
        
        Recipes are filtered by:
        1. Category (e.g., 'crafting', 'smelting')
        2. Result item subgroup (to exclude military/combat recipes)
        
        Args:
            prototype_data: Full prototype data dump from Factorio
            
        Returns:
            Sorted list of recipe names that pass the filter
        """
        recipe_config = self.config['recipes']
        recipes = prototype_data.get('recipe', {})
        
        # Build a map of all items across all categories (item, ammo, capsule, etc.)
        all_items = {}
        for category, items in prototype_data.items():
            if isinstance(items, dict):
                all_items.update(items)
        
        # Get exclude subgroups from items config (reuse for consistency)
        exclude_subgroups = set(self.config.get('items', {}).get('exclude_subgroups', []))
        
        # Start with explicit includes (if any)
        if recipe_config['include']:
            result = set(recipe_config['include'])
        else:
            # Filter by category (not subgroup!)
            result = set()
            include_categories = set(recipe_config.get('include_categories', []))
            exclude_categories = set(recipe_config.get('exclude_categories', []))
            
            for recipe_name, recipe_data in recipes.items():
                # Skip hidden recipes
                if recipe_data.get('hidden'):
                    continue
                
                # Skip recipes that place entities (these are entity placement, not crafting)
                if 'place_result' in recipe_data:
                    continue
                
                category = recipe_data.get('category', 'crafting')
                
                # Check category exclusions
                if category in exclude_categories:
                    continue
                
                # Check category inclusions (if specified, otherwise include all)
                if include_categories and category not in include_categories:
                    continue
                
                # Check result item subgroup (to exclude military/combat recipes)
                # Get the first result item
                results = recipe_data.get('results', [])
                if results and isinstance(results, list) and len(results) > 0:
                    result_item_name = results[0].get('name')
                    if result_item_name and result_item_name in all_items:
                        item_subgroup = all_items[result_item_name].get('subgroup', '')
                        if item_subgroup in exclude_subgroups:
                            continue
                
                result.add(recipe_name)
        
        # Apply explicit exclusions (glob patterns)
        exclude_patterns = recipe_config['exclude']
        result = {name for name in result 
                 if not self._matches_pattern(name, exclude_patterns)}
        
        return sorted(result)
    
    def filter_items(self, prototype_data: dict) -> List[str]:
        """
        Filter items based on config.
        
        Args:
            prototype_data: Full prototype data dump from Factorio
            
        Returns:
            Sorted list of item names that pass the filter
        """
        item_config = self.config['items']
        items = prototype_data.get('item', {})
        
        # Start with explicit includes (if any)
        if item_config['include']:
            result = set(item_config['include'])
        else:
            # Filter by subgroup
            result = self._filter_by_subgroup(
                items,
                item_config['include_subgroups'],
                item_config['exclude_subgroups']
            )
        
        # Apply explicit exclusions (glob patterns)
        exclude_patterns = item_config['exclude']
        result = {name for name in result 
                 if not self._matches_pattern(name, exclude_patterns)}
        
        return sorted(result)
    
    def get_resource_entities(self, prototype_data: dict) -> List[str]:
        """
        Get resource entities (trees, rocks).
        
        Args:
            prototype_data: Full prototype data dump from Factorio
            
        Returns:
            Sorted list of resource entity names
        """
        config = self.config['resource_entities']
        
        if config['include_all']:
            # Include all trees and rocks
            result = set()
            result.update(prototype_data.get('tree', {}).keys())
            result.update(prototype_data.get('simple-entity', {}).keys())
        else:
            result = set()
        
        # Apply exclusions
        exclude_patterns = config['exclude']
        result = {name for name in result 
                 if not self._matches_pattern(name, exclude_patterns)}
        
        return sorted(result)
    
    def get_resource_tiles(self, prototype_data: dict) -> List[str]:
        """
        Get resource tiles (ore patches).
        
        Args:
            prototype_data: Full prototype data dump from Factorio
            
        Returns:
            Sorted list of resource tile names
        """
        config = self.config['resource_tiles']
        
        if config['include_all']:
            result = set(prototype_data.get('resource', {}).keys())
        else:
            result = set()
        
        # Apply exclusions
        exclude_patterns = config['exclude']
        result = {name for name in result 
                 if not self._matches_pattern(name, exclude_patterns)}
        
        return sorted(result)


# Singleton instance
_filter_config: Optional[FilterConfig] = None


def get_filter_config(config_file: Optional[str] = None) -> FilterConfig:
    """
    Get the global filter config singleton.
    
    Args:
        config_file: Path to fv_filters.yaml (only used on first call).
                    If None, auto-detects at repository root.
        
    Returns:
        FilterConfig instance (singleton)
    """
    global _filter_config
    if _filter_config is None:
        _filter_config = FilterConfig(config_file)
    return _filter_config


def reset_filter_config():
    """Reset the singleton (useful for testing)."""
    global _filter_config
    _filter_config = None


__all__ = [
    'FilterConfig',
    'get_filter_config',
    'reset_filter_config',
]
