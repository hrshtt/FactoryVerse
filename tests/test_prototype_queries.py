"""Tests for prototype query methods."""
import pytest
from FactoryVerse.dsl.prototypes import (
    get_item_prototypes,
    get_recipe_prototypes,
    reset_prototypes
)


class TestItemPrototypes:
    """Test ItemPrototypes fuel query methods."""
    
    def setup_method(self):
        """Reset prototypes before each test."""
        reset_prototypes()
    
    def test_get_fuel_items_all(self):
        """Test getting all fuel items."""
        protos = get_item_prototypes()
        all_fuel = protos.get_fuel_items()
        
        # Should include common fuels
        assert 'wood' in all_fuel
        assert 'coal' in all_fuel
        assert 'solid-fuel' in all_fuel
        assert 'uranium-fuel-cell' in all_fuel
        
        # Should not include non-fuel
        assert 'iron-plate' not in all_fuel
        assert 'copper-ore' not in all_fuel
    
    def test_get_fuel_items_by_category(self):
        """Test getting fuel items filtered by category."""
        protos = get_item_prototypes()
        
        chemical_fuels = protos.get_fuel_items('chemical')
        assert 'wood' in chemical_fuels
        assert 'coal' in chemical_fuels
        assert 'solid-fuel' in chemical_fuels
        assert 'uranium-fuel-cell' not in chemical_fuels
        
        nuclear_fuels = protos.get_fuel_items('nuclear')
        assert 'uranium-fuel-cell' in nuclear_fuels
        assert 'coal' not in nuclear_fuels
    
    def test_is_fuel(self):
        """Test fuel detection."""
        protos = get_item_prototypes()
        
        assert protos.is_fuel('coal') is True
        assert protos.is_fuel('wood') is True
        assert protos.is_fuel('uranium-fuel-cell') is True
        assert protos.is_fuel('iron-plate') is False
        assert protos.is_fuel('copper-ore') is False
    
    def test_get_fuel_category(self):
        """Test getting fuel category."""
        protos = get_item_prototypes()
        
        assert protos.get_fuel_category('coal') == 'chemical'
        assert protos.get_fuel_category('wood') == 'chemical'
        assert protos.get_fuel_category('uranium-fuel-cell') == 'nuclear'
        assert protos.get_fuel_category('iron-plate') is None


class TestRecipePrototypes:
    """Test RecipePrototypes query methods."""
    
    def setup_method(self):
        """Reset prototypes before each test."""
        reset_prototypes()
    
    def test_is_handcraftable(self):
        """Test handcraftability detection."""
        protos = get_recipe_prototypes()
        
        # Handcraftable recipes (category=crafting)
        assert protos.is_handcraftable('iron-gear-wheel') is True
        assert protos.is_handcraftable('copper-cable') is True
        assert protos.is_handcraftable('electronic-circuit') is True
        
        # Non-handcraftable recipes (category=smelting)
        assert protos.is_handcraftable('iron-plate') is False
        assert protos.is_handcraftable('copper-plate') is False
        assert protos.is_handcraftable('steel-plate') is False
    
    def test_get_recipe_category(self):
        """Test getting recipe category."""
        protos = get_recipe_prototypes()
        
        assert protos.get_recipe_category('iron-gear-wheel') == 'crafting'
        assert protos.get_recipe_category('iron-plate') == 'smelting'
        assert protos.get_recipe_category('copper-plate') == 'smelting'
        assert protos.get_recipe_category('nonexistent-recipe') is None
    
    def test_get_recipes_by_category(self):
        """Test getting recipes by category."""
        protos = get_recipe_prototypes()
        
        crafting_recipes = protos.get_recipes_by_category('crafting')
        assert 'iron-gear-wheel' in crafting_recipes
        assert 'copper-cable' in crafting_recipes
        assert len(crafting_recipes) > 100  # Should have many handcraftable recipes
        
        smelting_recipes = protos.get_recipes_by_category('smelting')
        assert 'iron-plate' in smelting_recipes
        assert 'copper-plate' in smelting_recipes
        assert 'steel-plate' in smelting_recipes
