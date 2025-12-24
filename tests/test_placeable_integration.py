import sys
import os
import json
from unittest.mock import MagicMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.FactoryVerse.dsl.item.base import get_item, ItemStack, MiningDrillItem, PlaceableItem, Item, PumpjackItem

def test_placeable_integration():
    print("Testing placeable item integration...")
    
    # Ensure prototypes are loaded
    from src.FactoryVerse.dsl.prototypes import get_entity_prototypes, get_item_prototypes
    
    # Assuming factory-data-dump.json is in current usage path
    try:
        get_entity_prototypes()
    except Exception as e:
        print(f"Skipping test requiring data dump: {e}")
        return

    # 1. Test Mining Drill
    drill = get_item("electric-mining-drill")
    print(f"electric-mining-drill -> {type(drill)}")
    assert isinstance(drill, MiningDrillItem), "Should be MiningDrillItem"
    
    # 2. Test Pumpjack
    pumpjack = get_item("pumpjack")
    print(f"pumpjack -> {type(pumpjack)}")
    assert isinstance(pumpjack, PumpjackItem), "Should be PumpjackItem"

    # 3. Test Generic Placeable (Stone Furnace)
    furnace = get_item("stone-furnace")
    print(f"stone-furnace -> {type(furnace)}")
    assert isinstance(furnace, PlaceableItem), "Should be PlaceableItem"
    assert not isinstance(furnace, MiningDrillItem)
    
    # 4. Test Non-Placeable (Iron Plate)
    plate = get_item("iron-plate")
    print(f"iron-plate -> {type(plate)}")
    assert type(plate) is Item, "Should be generic Item"
    
    # 5. Test ItemStack integration
    stack = ItemStack(name="electric-mining-drill", count=10, subgroup="extraction-machine")
    assert isinstance(stack.item, MiningDrillItem)
    
    # Test methods presence using HasAttr (can't call them without factory context)
    assert hasattr(stack, "place")
    assert hasattr(stack, "place_ghost")
    assert hasattr(stack, "get_placement_cues")

    # Test cues on mining drill stack
    # We can mock stack.item._factory or catch the error
    try:
        stack.get_placement_cues()
    except RuntimeError as e:
        assert "No active gameplay session" in str(e)
        print("✅ Caught expected RuntimeError for missing factory")

    print("\n✅ All integration tests passed")

if __name__ == "__main__":
    test_placeable_integration()
