"""Prototype data access - minimal loader providing raw dict access.

This module provides:
- get_width_height(): Helper for collision box dimensions
- EntityPrototypes: Singleton providing get_prototype(name) -> Dict[str, Any]
- ItemPrototypes: Singleton for item data access
- RecipePrototypes: Singleton for recipe data access

Note: Geometric position calculations (vector rotation, drop/pickup positions)
are now handled by fv_placement_hints mod in Lua using engine-provided values.

All property accessors are defined on BaseEntity, mixins, and implementations.
"""

from typing import Tuple, List, Dict, Any, Optional


def get_width_height(bbox: List[List[float]]) -> Tuple[float, float]:
    """Calculate width and height from a bounding box.

    Args:
        bbox: A list of two points, e.g., [[x1, y1], [x2, y2]],
              representing opposite corners of the bounding box.

    Returns:
        Tuple of (width, height).
    """
    (x1, y1) = bbox[0]
    (x2, y2) = bbox[1]
    width = abs(x1 - x2)
    height = abs(y1 - y2)
    return width, height


class EntityPrototypes:
    """Minimal prototype data accessor - provides raw dict access.

    All property accessors are defined on BaseEntity, mixins, and implementations.
    This class only provides data loading and lookup.
    Respects filtering - only returns entities that pass the filter.
    """

    def __init__(self):
        from FactoryVerse.game.factory.prototype_data import get_prototype_manager

        manager = get_prototype_manager()
        self.data = manager.get_raw_data()
        self._filtered_entities = set(manager.get_filtered_entities())

        # Build reverse map: entity_name -> category (type)
        # Only include entities that pass the filter. Shared denylist so
        # the filter scope and this accessor can never disagree (L3.3).
        from FactoryVerse.utils.filters import NON_ENTITY_CATEGORIES

        ignore_categories = NON_ENTITY_CATEGORIES

        self.entity_type_map: Dict[str, str] = {}
        for category, entities in self.data.items():
            if category in ignore_categories:
                continue
            if isinstance(entities, dict):
                for entity_name in entities:
                    # Only include filtered entities
                    if entity_name in self._filtered_entities:
                        self.entity_type_map[entity_name] = category

    def get_entity_type(self, entity_name: str) -> Optional[str]:
        """Get the prototype category (type) for an entity name.

        Only returns types for entities that pass the filter.

        Args:
            entity_name: Name of the entity (e.g., "stone-furnace")

        Returns:
            Category string (e.g., "furnace") or None if not found or filtered out
        """
        return self.entity_type_map.get(entity_name)

    def get_prototype(self, entity_name: str) -> Dict[str, Any]:
        """Get prototype data as raw dict for an entity.

        Only returns data for entities that pass the filter.

        Args:
            entity_name: Name of the entity (e.g., "electric-mining-drill")

        Returns:
            Raw prototype data dict, or empty dict if not found or filtered out

        Example:
            >>> prototypes = get_entity_prototypes()
            >>> drill_data = prototypes.get_prototype("electric-mining-drill")
            >>> output_vec = drill_data["vector_to_place_result"]
        """
        # Check if entity passes filter first
        if entity_name not in self._filtered_entities:
            return {}

        entity_type = self.get_entity_type(entity_name)
        if entity_type and entity_type in self.data:
            entities = self.data[entity_type]
            if isinstance(entities, dict) and entity_name in entities:
                return entities[entity_name]
        return {}


class ItemPrototypes:
    """Prototype accessor for items.

    Respects filtering - only returns items that pass the filter.
    """

    def __init__(self):
        from FactoryVerse.game.factory.prototype_data import get_prototype_manager

        manager = get_prototype_manager()
        self.data = manager.get_raw_data()
        self._filtered_items = set(manager.get_filtered_items())

        # item data is usually under data['item']
        # Only include filtered items
        all_items = self.data.get("item", {})
        self.items = {
            name: data
            for name, data in all_items.items()
            if name in self._filtered_items
        }

        # Build fuel items cache (only from filtered items)
        self._fuel_items_cache: Dict[str, List[str]] = {}
        self._build_fuel_cache()

    def _build_fuel_cache(self):
        """Build cache of fuel items by category."""
        for item_name, item_data in self.items.items():
            if "fuel_value" in item_data:
                fuel_cat = item_data.get("fuel_category", "chemical")
                if fuel_cat not in self._fuel_items_cache:
                    self._fuel_items_cache[fuel_cat] = []
                self._fuel_items_cache[fuel_cat].append(item_name)

    def get_fuel_items(self, category: Optional[str] = None) -> List[str]:
        """Get list of fuel items, optionally filtered by category.

        Args:
            category: Optional fuel category ('chemical', 'nuclear')

        Returns:
            List of fuel item names
        """
        if category:
            return self._fuel_items_cache.get(category, [])
        # Return all fuel items
        all_fuel = []
        for items in self._fuel_items_cache.values():
            all_fuel.extend(items)
        return all_fuel

    def is_fuel(self, item_name: str) -> bool:
        """Check if an item is fuel.

        Args:
            item_name: Name of the item to check

        Returns:
            True if the item can be used as fuel
        """
        return any(item_name in items for items in self._fuel_items_cache.values())

    def get_fuel_category(self, item_name: str) -> Optional[str]:
        """Get fuel category for an item.

        Args:
            item_name: Name of the item

        Returns:
            Fuel category ('chemical', 'nuclear') or None if not fuel
        """
        for category, items in self._fuel_items_cache.items():
            if item_name in items:
                return category
        return None

    def get_place_result(self, item_name: str) -> Optional[str]:
        """Get the entity name that this item places, if any.

        Only returns results for items that pass the filter.
        """
        # Check if item passes filter first
        if item_name not in self._filtered_items:
            return None
        item_data = self.items.get(item_name)
        if not item_data:
            return None
        return item_data.get("place_result")


class RecipePrototypes:
    """Prototype accessor for recipes.

    Respects filtering - only returns recipes that pass the filter.
    """

    def __init__(self):
        from FactoryVerse.game.factory.prototype_data import get_prototype_manager

        manager = get_prototype_manager()
        self.data = manager.get_raw_data()
        self._filtered_recipes = set(manager.get_filtered_recipes())

        # recipe data is usually under data['recipe']
        # Only include filtered recipes
        all_recipes = self.data.get("recipe", {})
        self.recipes = {
            name: data
            for name, data in all_recipes.items()
            if name in self._filtered_recipes
        }

        # Build recipe category cache (only from filtered recipes)
        self._by_category_cache: Dict[str, List[str]] = {}
        self._build_category_cache()

    def _build_category_cache(self):
        """Build cache of recipes by category."""
        for recipe_name, recipe_data in self.recipes.items():
            category = recipe_data.get("category", "crafting")
            if category not in self._by_category_cache:
                self._by_category_cache[category] = []
            self._by_category_cache[category].append(recipe_name)

    def get_recipes_by_category(self, category: str) -> List[str]:
        """Get recipes in a specific category.

        Args:
            category: Recipe category (e.g., 'crafting', 'smelting', 'chemistry')

        Returns:
            List of recipe names in that category
        """
        return self._by_category_cache.get(category, [])

    def is_handcraftable(self, recipe_name: str) -> bool:
        """Check if a recipe can be handcrafted.

        Only checks recipes that pass the filter.

        Args:
            recipe_name: Name of the recipe

        Returns:
            True if recipe has category='crafting' (handcraftable)
        """
        # Check if recipe passes filter first
        if recipe_name not in self._filtered_recipes:
            return False
        recipe_data = self.recipes.get(recipe_name)
        if not recipe_data:
            return False
        return recipe_data.get("category", "crafting") == "crafting"

    def get_recipe_category(self, recipe_name: str) -> Optional[str]:
        """Get the category of a recipe.

        Only returns categories for recipes that pass the filter.

        Args:
            recipe_name: Name of the recipe

        Returns:
            Recipe category or None if recipe not found or filtered out
        """
        # Check if recipe passes filter first
        if recipe_name not in self._filtered_recipes:
            return None
        recipe_data = self.recipes.get(recipe_name)
        if not recipe_data:
            return None
        return recipe_data.get("category", "crafting")


# Singleton instances - owned by this module
_prototypes: Optional[EntityPrototypes] = None
_item_prototypes: Optional[ItemPrototypes] = None
_recipe_prototypes: Optional[RecipePrototypes] = None


def get_entity_prototypes() -> EntityPrototypes:
    """Get the global entity prototypes singleton instance.

    The singleton is instantiated on first call and reused for subsequent calls.

    Returns:
        EntityPrototypes instance (singleton, instantiated on first call)

    Example:
        >>> prototypes = get_entity_prototypes()
        >>> drill_data = prototypes.get_prototype("electric-mining-drill")
        >>> output_vec = drill_data["vector_to_place_result"]
    """
    global _prototypes
    if _prototypes is None:
        _prototypes = EntityPrototypes()
    return _prototypes


def reset_prototypes():
    """Reset the singleton instances (useful for testing or reloading).

    After calling this, the next call to get_*_prototypes() will create new
    instances from the dump file.
    """
    global _prototypes
    global _item_prototypes
    global _recipe_prototypes
    _prototypes = None
    _item_prototypes = None
    _recipe_prototypes = None


def get_item_prototypes() -> ItemPrototypes:
    """Get the global item prototypes singleton instance."""
    global _item_prototypes
    if _item_prototypes is None:
        _item_prototypes = ItemPrototypes()
    return _item_prototypes


def get_recipe_prototypes() -> RecipePrototypes:
    """Get the global recipe prototypes singleton instance.

    Returns:
        RecipePrototypes instance (singleton, instantiated on first call)
    """
    global _recipe_prototypes
    if _recipe_prototypes is None:
        _recipe_prototypes = RecipePrototypes()
    return _recipe_prototypes
