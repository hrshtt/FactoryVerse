import asyncio
import sys
import os
from unittest.mock import MagicMock, AsyncMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.FactoryVerse.dsl.agent import MiningAction, CraftingAction, PlayingFactory
from src.FactoryVerse.dsl.item.base import ItemStack

async def test_mining_return_type():
    print("Testing MiningAction.mine return type...")
    
    # Mock factory
    factory = MagicMock(spec=PlayingFactory)
    
    # Payload from user request
    mining_payload = {
        'action_id': 'mine_1137465_1', 
        'agent_id': 1, 
        'result': {
            'reason': 'completed', 
            'entity_name': 'stone', 
            'position': {'x': 78.5, 'y': 31.5}, 
            'mode': 'incremental', 
            'count': 25, 
            'actual_products': {'stone': 25}, 
            'actual_ticks': 3025
        }
    }
    
    factory.mine_resource.return_value = {'queued': True, 'action_id': 'mine_1137465_1'}
    factory._await_action = AsyncMock(return_value=mining_payload)
    
    mining = MiningAction(factory)
    items = await mining.mine('stone', 25)
    
    print(f"Result type: {type(items)}")
    print(f"Items: {items}")
    
    assert isinstance(items, list), "Result should be a list"
    assert all(isinstance(item, ItemStack) for item in items), "All items should be ItemStacks"
    assert len(items) == 1
    assert items[0].name == 'stone'
    assert items[0].count == 25
    print("✅ MiningAction.mine passed")

async def test_crafting_return_type():
    print("\nTesting CraftingAction.craft return type...")
    
    # Mock factory
    factory = MagicMock(spec=PlayingFactory)
    
    # Payload from user request
    crafting_payload = {
        'action_id': 'craft_enqueue_1234221_1', 
        'agent_id': 1, 
        'result': {
            'recipe': 'stone-furnace', 
            'count_requested': 5, 
            'count_queued': 5, 
            'count_crafted': 5, 
            'products': {'stone-furnace': 5}, 
            'actual_ticks': 155
        }
    }
    
    factory.craft_enqueue.return_value = {'queued': True, 'action_id': 'craft_enqueue_1234221_1'}
    factory._await_action = AsyncMock(return_value=crafting_payload)
    
    crafting = CraftingAction(factory)
    items = await crafting.craft('stone-furnace', 5)
    
    print(f"Result type: {type(items)}")
    print(f"Items: {items}")
    
    assert isinstance(items, list), "Result should be a list"
    assert all(isinstance(item, ItemStack) for item in items), "All items should be ItemStacks"
    assert len(items) == 1
    assert items[0].name == 'stone-furnace'
    assert items[0].count == 5
    print("✅ CraftingAction.craft passed")

if __name__ == "__main__":
    asyncio.run(test_mining_return_type())
    asyncio.run(test_crafting_return_type())
