"""Test handcraftability validation in inventory.check_recipe_count()."""
import pytest
from unittest.mock import Mock, patch
from FactoryVerse.dsl.agent import AgentInventory


class TestHandcraftabilityValidation:
    """Test handcraftability validation in check_recipe_count."""
    
    @patch('FactoryVerse.dsl.prototypes.get_recipe_prototypes')
    def test_handcraftable_recipe_allowed(self, mock_get_protos):
        """Test that handcraftable recipes work normally."""
        # Setup mocks
        mock_protos = Mock()
        mock_protos.is_handcraftable.return_value = True
        mock_get_protos.return_value = mock_protos
        
        mock_factory = Mock()
        mock_factory.inventory.check_recipe_count.return_value = 10
        
        # Test
        inventory = AgentInventory(mock_factory)
        count = inventory.check_recipe_count('iron-gear-wheel')
        
        assert count == 10
        mock_factory.inventory.check_recipe_count.assert_called_once_with('iron-gear-wheel')
    
    @patch('FactoryVerse.dsl.prototypes.get_recipe_prototypes')
    def test_smelting_recipe_rejected(self, mock_get_protos):
        """Test that smelting recipes are rejected with helpful message."""
        # Setup mocks
        mock_protos = Mock()
        mock_protos.is_handcraftable.return_value = False
        mock_protos.get_recipe_category.return_value = 'smelting'
        mock_get_protos.return_value = mock_protos
        
        mock_factory = Mock()
        
        # Test
        inventory = AgentInventory(mock_factory)
        
        with pytest.raises(ValueError) as exc_info:
            inventory.check_recipe_count('copper-plate')
        
        error_msg = str(exc_info.value)
        assert "Cannot handcraft 'copper-plate'" in error_msg
        assert "requires smelting in a furnace" in error_msg
        assert "stone-furnace" in error_msg
    
    @patch('FactoryVerse.dsl.prototypes.get_recipe_prototypes')
    def test_chemistry_recipe_rejected(self, mock_get_protos):
        """Test that chemistry recipes are rejected with category info."""
        # Setup mocks
        mock_protos = Mock()
        mock_protos.is_handcraftable.return_value = False
        mock_protos.get_recipe_category.return_value = 'chemistry'
        mock_get_protos.return_value = mock_protos
        
        mock_factory = Mock()
        
        # Test
        inventory = AgentInventory(mock_factory)
        
        with pytest.raises(ValueError) as exc_info:
            inventory.check_recipe_count('sulfuric-acid')
        
        error_msg = str(exc_info.value)
        assert "Cannot handcraft 'sulfuric-acid'" in error_msg
        assert "requires category='chemistry' machine" in error_msg


