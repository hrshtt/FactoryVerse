"""Example 02: Mining Resources

Demonstrates:
- Finding resources with reachable.get_resources()
- Mining with proper batching (25 item limit per operation)
- Looping to mine larger quantities
- Checking inventory after mining
"""
from FactoryVerse.dsl.dsl import playing_factorio, reachable, inventory
from FactoryVerse.dsl.types import MapPosition


async def mine_iron_ore_batch():
    """Mine iron ore in batches, respecting the 25-item limit."""
    
    with playing_factorio():
        # Find nearby iron ore resources
        iron_resources = reachable.get_resources("iron-ore")
        
        if not iron_resources:
            print("No iron ore resources in reach!")
            return
        
        # Get the first resource (could be a patch or single tile)
        resource = iron_resources[0]
        print(f"Found: {resource.name}")
        
        # Check if it's a patch or single tile
        if hasattr(resource, 'total'):
            print(f"  Patch with {resource.total} total ore across {resource.count} tiles")
        elif hasattr(resource, 'amount'):
            print(f"  Single tile with {resource.amount} ore")
        
        # CRITICAL: Mining is limited to 25 items per operation
        # To mine more, you need to loop
        
        target_amount = 100
        total_mined = 0
        
        print(f"\nMining up to {target_amount} iron ore...")
        
        while total_mined < target_amount:
            # Calculate how much to mine in this batch (max 25)
            remaining = target_amount - total_mined
            batch_size = min(25, remaining)
            
            # Mine the batch
            items = await resource.mine(max_count=batch_size)
            
            # Count what we got
            batch_total = sum(stack.count for stack in items)
            total_mined += batch_total
            
            print(f"  Mined {batch_total} ore (total: {total_mined})")
            
            # If we got nothing, the resource is depleted
            if batch_total == 0:
                print("  Resource depleted!")
                break
        
        print(f"\nMining complete! Total mined: {total_mined}")
        
        # Verify inventory
        iron_ore_count = inventory.get_total('iron-ore')
        print(f"Total iron ore in inventory: {iron_ore_count}")


async def mine_trees_for_wood():
    """Mine trees to get wood (trees are also resources)."""
    
    with playing_factorio():
        # Trees are a different resource type
        trees = reachable.get_resources(resource_type="tree")
        
        if not trees:
            print("No trees in reach!")
            return
        
        # Trees are always BaseResource (single entities), not patches
        tree = trees[0]
        print(f"Found tree: {tree.name} at ({tree.position.x:.1f}, {tree.position.y:.1f})")
        
        # Mine the tree (max 25, but trees usually give less)
        items = await tree.mine(max_count=25)
        
        for stack in items:
            print(f"  Got {stack.count}x {stack.name}")


# Key takeaways:
# 1. Always respect the 25-item mining limit
# 2. Loop for larger quantities
# 3. Check batch_total == 0 to detect depletion
# 4. ResourceOrePatch vs BaseResource have different interfaces
# 5. Trees and rocks are also resources (resource_type="tree" or "simple-entity")
