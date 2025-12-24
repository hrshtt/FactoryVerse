"""Tests for fuel validation in Furnace.add_fuel() method."""
import pytest
from unittest.mock import Mock, patch
from FactoryVerse.dsl.entity.base import Furnace
from FactoryVerse.dsl.item.base import Item, ItemStack


class TestFurnaceFuelValidation:
    """Test fuel type validation in furnaces."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Mock factory
        self.mock_factory = Mock()
        
    @patch('FactoryVerse.dsl.prototypes.get_item_prototypes')
    def test_valid_chemical_fuel_for_stone_furnace(self, mock_get_protos):
        """Test that valid chemical fuel is accepted by stone furnace."""
        # Setup mock
        mock_protos = Mock()
        mock_protos.is_fuel.return_value = True
        mock_protos.get_fuel_category.return_value = 'chemical'
        mock_get_protos.return_value = mock_protos
        
        # Create furnace
        furnace = Furnace(
            name='stone-furnace',
            position=Mock(x=0, y=0),
            factory=self.mock_factory
        )
        
        # Add coal (valid chemical fuel)
        coal = ItemStack(name='coal', count=10)
        furnace.add_fuel(coal)
        
        # Verify put_inventory_item was called
        self.mock_factory.put_inventory_item.assert_called_once_with(
            'stone-furnace', furnace.position, 'fuel', 'coal', 10
        )
    
    @patch('FactoryVerse.dsl.prototypes.get_item_prototypes')
    def test_non_fuel_item_rejected(self, mock_get_protos):
        """Test that non-fuel items are rejected."""
        # Setup mock
        mock_protos = Mock()
        mock_protos.is_fuel.return_value = False
        mock_protos.get_fuel_items.return_value = ['wood', 'coal', 'solid-fuel']
        mock_get_protos.return_value = mock_protos
        
        # Create furnace
        furnace = Furnace(
            name='stone-furnace',
            position=Mock(x=0, y=0),
            factory=self.mock_factory
        )
        
        # Try to add iron plate (not fuel)
        iron_plate = ItemStack(name='iron-plate', count=10)
        
        with pytest.raises(ValueError) as exc_info:
            furnace.add_fuel(iron_plate)
        
        assert "Cannot add 'iron-plate' as fuel" in str(exc_info.value)
        assert "Valid fuel items:" in str(exc_info.value)
    
    @patch('FactoryVerse.dsl.prototypes.get_item_prototypes')
    def test_nuclear_fuel_rejected_by_stone_furnace(self, mock_get_protos):
        """Test that nuclear fuel is rejected by stone furnace."""
        # Setup mock
        mock_protos = Mock()
        mock_protos.is_fuel.return_value = True
        mock_protos.get_fuel_category.return_value = 'nuclear'
        mock_get_protos.return_value = mock_protos
        
        # Create furnace
        furnace = Furnace(
            name='stone-furnace',
            position=Mock(x=0, y=0),
            factory=self.mock_factory
        )
        
        # Try to add uranium fuel cell
        uranium_cell = ItemStack(name='uranium-fuel-cell', count=1)
        
        with pytest.raises(ValueError) as exc_info:
            furnace.add_fuel(uranium_cell)
        
        assert "fuel_category=nuclear" in str(exc_info.value)
        assert "only accept chemical fuels" in str(exc_info.value)
    
    @patch('FactoryVerse.dsl.prototypes.get_item_prototypes')
    def test_electric_furnace_rejects_all_fuel(self, mock_get_protos):
        """Test that electric furnace rejects all fuel."""
        # Setup mock
        mock_protos = Mock()
        mock_protos.is_fuel.return_value = True
        mock_protos.get_fuel_category.return_value = 'chemical'
        mock_get_protos.return_value = mock_protos
        
        # Create electric furnace
        furnace = Furnace(
            name='electric-furnace',
            position=Mock(x=0, y=0),
            factory=self.mock_factory
        )
        
        # Try to add coal
        coal = ItemStack(name='coal', count=10)
        
        with pytest.raises(ValueError) as exc_info:
            furnace.add_fuel(coal)
        
        assert "Electric furnaces use electricity, not fuel" in str(exc_info.value)
