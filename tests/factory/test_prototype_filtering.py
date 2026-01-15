"""Tests for prototype filtering integration.

Validates that EntityPrototypes, ItemPrototypes, and RecipePrototypes
respect the filtering configuration and only return data for entities/items/recipes
that pass the filter.
"""

import pytest
from FactoryVerse.factory.prototypes import (
    get_entity_prototypes,
    get_item_prototypes,
    get_recipe_prototypes,
    reset_prototypes,
)
from FactoryVerse.prototype_data import reset_prototype_manager
from FactoryVerse.utils.filters import reset_filter_config


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset all singletons before each test."""
    reset_prototypes()
    reset_prototype_manager()
    reset_filter_config()
    yield
    reset_prototypes()
    reset_prototype_manager()
    reset_filter_config()


class TestEntityPrototypesFiltering:
    """Test that EntityPrototypes respects filtering."""

    def test_filtered_entity_is_accessible(self):
        """Filtered entities should be accessible via get_prototype()."""
        prototypes = get_entity_prototypes()

        # Get a known filtered entity (should exist in most configs)
        filtered_entities = list(prototypes._filtered_entities)
        if not filtered_entities:
            pytest.skip("No filtered entities available - check filter config")

        # Test first filtered entity
        entity_name = filtered_entities[0]
        proto = prototypes.get_prototype(entity_name)

        assert proto != {}, f"Filtered entity {entity_name} should return data"
        assert "name" in proto or "type" in proto or len(proto) > 0, \
            f"Entity {entity_name} should have prototype data"

    def test_non_filtered_entity_returns_empty(self):
        """Non-filtered entities should return empty dict."""
        prototypes = get_entity_prototypes()

        # Get all entities from raw data
        all_entities = set()
        ignore_categories = {
            "item", "recipe", "technology", "fluid", "tile",
            "virtual-signal", "achievement", "item-group", "item-subgroup",
            "recipe-category", "fuel-category", "resource-category",
            "module-category", "equipment-category", "ammo-category",
            "autoplace-control", "custom-input", "font", "gui-style",
            "mouse-cursor", "noise-layer", "particle", "sound", "sprite",
            "tile-effect", "tips-and-tricks-item-category",
            "tips-and-tricks-item", "trivial-smoke", "utility-constants",
            "utility-sounds", "utility-sprites",
        }

        for category, entities in prototypes.data.items():
            if category in ignore_categories:
                continue
            if isinstance(entities, dict):
                all_entities.update(entities.keys())

        # Find entities that are NOT in filtered list
        filtered_set = prototypes._filtered_entities
        non_filtered = all_entities - filtered_set

        if not non_filtered:
            pytest.skip("All entities are filtered - cannot test non-filtered case")

        # Test that non-filtered entity returns empty dict
        non_filtered_entity = list(non_filtered)[0]
        proto = prototypes.get_prototype(non_filtered_entity)

        assert proto == {}, \
            f"Non-filtered entity {non_filtered_entity} should return empty dict, got {proto}"

    def test_get_entity_type_respects_filtering(self):
        """get_entity_type() should only return types for filtered entities."""
        prototypes = get_entity_prototypes()

        filtered_entities = list(prototypes._filtered_entities)
        if not filtered_entities:
            pytest.skip("No filtered entities available")

        # Filtered entity should have a type
        entity_name = filtered_entities[0]
        entity_type = prototypes.get_entity_type(entity_name)
        assert entity_type is not None, \
            f"Filtered entity {entity_name} should have a type"

        # Non-filtered entity should return None
        all_entities = set()
        ignore_categories = {
            "item", "recipe", "technology", "fluid", "tile",
            "virtual-signal", "achievement", "item-group", "item-subgroup",
            "recipe-category", "fuel-category", "resource-category",
            "module-category", "equipment-category", "ammo-category",
            "autoplace-control", "custom-input", "font", "gui-style",
            "mouse-cursor", "noise-layer", "particle", "sound", "sprite",
            "tile-effect", "tips-and-tricks-item-category",
            "tips-and-tricks-item", "trivial-smoke", "utility-constants",
            "utility-sounds", "utility-sprites",
        }

        for category, entities in prototypes.data.items():
            if category in ignore_categories:
                continue
            if isinstance(entities, dict):
                all_entities.update(entities.keys())

        non_filtered = all_entities - prototypes._filtered_entities
        if non_filtered:
            non_filtered_entity = list(non_filtered)[0]
            entity_type = prototypes.get_entity_type(non_filtered_entity)
            assert entity_type is None, \
                f"Non-filtered entity {non_filtered_entity} should return None for type"


class TestItemPrototypesFiltering:
    """Test that ItemPrototypes respects filtering."""

    def test_filtered_item_is_accessible(self):
        """Filtered items should be accessible."""
        item_protos = get_item_prototypes()

        filtered_items = list(item_protos._filtered_items)
        if not filtered_items:
            pytest.skip("No filtered items available - check filter config")

        # Test first filtered item
        item_name = filtered_items[0]
        assert item_name in item_protos.items, \
            f"Filtered item {item_name} should be in items dict"

    def test_non_filtered_item_not_accessible(self):
        """Non-filtered items should not be in items dict."""
        item_protos = get_item_prototypes()

        # Get all items from raw data
        all_items = set(item_protos.data.get("item", {}).keys())
        filtered_set = item_protos._filtered_items
        non_filtered = all_items - filtered_set

        if not non_filtered:
            pytest.skip("All items are filtered - cannot test non-filtered case")

        # Test that non-filtered item is not in items dict
        non_filtered_item = list(non_filtered)[0]
        assert non_filtered_item not in item_protos.items, \
            f"Non-filtered item {non_filtered_item} should not be in items dict"

    def test_get_place_result_respects_filtering(self):
        """get_place_result() should only work for filtered items."""
        item_protos = get_item_prototypes()

        filtered_items = list(item_protos._filtered_items)
        if not filtered_items:
            pytest.skip("No filtered items available")

        # Find a placeable filtered item
        placeable_item = None
        for item_name in filtered_items:
            if item_name in item_protos.items:
                place_result = item_protos.items[item_name].get("place_result")
                if place_result:
                    placeable_item = item_name
                    break

        if placeable_item:
            result = item_protos.get_place_result(placeable_item)
            assert result is not None, \
                f"Filtered placeable item {placeable_item} should return place_result"

        # Non-filtered item should return None
        all_items = set(item_protos.data.get("item", {}).keys())
        non_filtered = all_items - item_protos._filtered_items
        if non_filtered:
            non_filtered_item = list(non_filtered)[0]
            result = item_protos.get_place_result(non_filtered_item)
            assert result is None, \
                f"Non-filtered item {non_filtered_item} should return None for place_result"


class TestRecipePrototypesFiltering:
    """Test that RecipePrototypes respects filtering."""

    def test_filtered_recipe_is_accessible(self):
        """Filtered recipes should be accessible."""
        recipe_protos = get_recipe_prototypes()

        filtered_recipes = list(recipe_protos._filtered_recipes)
        if not filtered_recipes:
            pytest.skip("No filtered recipes available - check filter config")

        # Test first filtered recipe
        recipe_name = filtered_recipes[0]
        assert recipe_name in recipe_protos.recipes, \
            f"Filtered recipe {recipe_name} should be in recipes dict"

    def test_non_filtered_recipe_not_accessible(self):
        """Non-filtered recipes should not be in recipes dict."""
        recipe_protos = get_recipe_prototypes()

        # Get all recipes from raw data
        all_recipes = set(recipe_protos.data.get("recipe", {}).keys())
        filtered_set = recipe_protos._filtered_recipes
        non_filtered = all_recipes - filtered_set

        if not non_filtered:
            pytest.skip("All recipes are filtered - cannot test non-filtered case")

        # Test that non-filtered recipe is not in recipes dict
        non_filtered_recipe = list(non_filtered)[0]
        assert non_filtered_recipe not in recipe_protos.recipes, \
            f"Non-filtered recipe {non_filtered_recipe} should not be in recipes dict"

    def test_is_handcraftable_respects_filtering(self):
        """is_handcraftable() should only work for filtered recipes."""
        recipe_protos = get_recipe_prototypes()

        filtered_recipes = list(recipe_protos._filtered_recipes)
        if not filtered_recipes:
            pytest.skip("No filtered recipes available")

        # Filtered recipe should work
        recipe_name = filtered_recipes[0]
        result = recipe_protos.is_handcraftable(recipe_name)
        # Result can be True or False, but should not raise error
        assert isinstance(result, bool), \
            f"is_handcraftable({recipe_name}) should return bool"

        # Non-filtered recipe should return False
        all_recipes = set(recipe_protos.data.get("recipe", {}).keys())
        non_filtered = all_recipes - recipe_protos._filtered_recipes
        if non_filtered:
            non_filtered_recipe = list(non_filtered)[0]
            result = recipe_protos.is_handcraftable(non_filtered_recipe)
            assert result is False, \
                f"Non-filtered recipe {non_filtered_recipe} should return False"

    def test_get_recipe_category_respects_filtering(self):
        """get_recipe_category() should only work for filtered recipes."""
        recipe_protos = get_recipe_prototypes()

        filtered_recipes = list(recipe_protos._filtered_recipes)
        if not filtered_recipes:
            pytest.skip("No filtered recipes available")

        # Filtered recipe should return category
        recipe_name = filtered_recipes[0]
        category = recipe_protos.get_recipe_category(recipe_name)
        assert category is not None, \
            f"Filtered recipe {recipe_name} should have a category"

        # Non-filtered recipe should return None
        all_recipes = set(recipe_protos.data.get("recipe", {}).keys())
        non_filtered = all_recipes - recipe_protos._filtered_recipes
        if non_filtered:
            non_filtered_recipe = list(non_filtered)[0]
            category = recipe_protos.get_recipe_category(non_filtered_recipe)
            assert category is None, \
                f"Non-filtered recipe {non_filtered_recipe} should return None for category"


class TestFilteringIntegration:
    """Test that filtering is properly integrated across all accessors."""

    def test_entity_prototype_uses_filtered_data(self):
        """EntityPrototypes should only build entity_type_map from filtered entities."""
        prototypes = get_entity_prototypes()

        # entity_type_map should only contain filtered entities
        for entity_name in prototypes.entity_type_map:
            assert entity_name in prototypes._filtered_entities, \
                f"entity_type_map contains non-filtered entity: {entity_name}"

    def test_item_prototypes_uses_filtered_data(self):
        """ItemPrototypes should only include filtered items."""
        item_protos = get_item_prototypes()

        # items dict should only contain filtered items
        for item_name in item_protos.items:
            assert item_name in item_protos._filtered_items, \
                f"items dict contains non-filtered item: {item_name}"

    def test_recipe_prototypes_uses_filtered_data(self):
        """RecipePrototypes should only include filtered recipes."""
        recipe_protos = get_recipe_prototypes()

        # recipes dict should only contain filtered recipes
        for recipe_name in recipe_protos.recipes:
            assert recipe_name in recipe_protos._filtered_recipes, \
                f"recipes dict contains non-filtered recipe: {recipe_name}"
