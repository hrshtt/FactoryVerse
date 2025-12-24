from FactoryVerse.dsl.item.base import ItemStack
from FactoryVerse.dsl.entity.base import Furnace, BurnerMiningDrill, Container
from FactoryVerse.dsl.agent import PlayingFactory
from FactoryVerse.dsl.types import MapPosition
from unittest.mock import MagicMock

def test_contract():
    # Setup mock factory
    mock_factory = MagicMock()
    from FactoryVerse.dsl.types import _playing_factory
    _playing_factory.set(mock_factory)
    
    pos = MapPosition(0, 0)
    
    # 1. Test Furnace (should now use CrafterMixin.add_ingredients)
    furnace = Furnace(name="stone-furnace", position=pos)
    stacks = [ItemStack("iron-ore", 5)]
    
    print("Testing furnace.add_ingredients([ItemStack])")
    furnace.add_ingredients(stacks)
    mock_factory.put_inventory_item.assert_called_with("stone-furnace", pos, "input", "iron-ore", 5)
    
    # 2. Test Furnace add_fuel (strictly List[ItemStack])
    print("Testing furnace.add_fuel([ItemStack])")
    # Mock validate_fuel to bypass prototype lookup
    furnace._validate_fuel = MagicMock() 
    furnace.add_fuel(stacks)
    mock_factory.put_inventory_item.assert_called_with("stone-furnace", pos, "fuel", "iron-ore", 5)
    
    # 3. Test Container.store_items
    print("Testing container.store_items([ItemStack])")
    container = Container(name="wooden-chest", position=pos)
    container.store_items(stacks)
    mock_factory.put_inventory_item.assert_called_with("wooden-chest", pos, "chest", "iron-ore", 5)
    
    # 4. Test Agent.take_inventory_item (returns List[ItemStack])
    print("Testing agent.take_inventory_item returns list")
    from FactoryVerse.dsl.agent import PlayingFactory
    agent = PlayingFactory(MagicMock(), "agent_1", recipes=MagicMock(), tech_tree=MagicMock())
    agent._execute_and_parse_json = MagicMock(return_value={"name": "iron-plate", "count": 10})
    result = agent.take_inventory_item("iron-chest", pos, "chest", "iron-plate", 10)
    
    assert isinstance(result, list)
    assert isinstance(result[0], ItemStack)
    assert result[0].name == "iron-plate"
    assert result[0].count == 10
    
    print("All tests passed!")

if __name__ == "__main__":
    test_contract()
