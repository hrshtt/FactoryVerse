"""Example 05: Full Workflow

Demonstrates:
- Complete query → plan → execute → verify cycle
- Setting up a complete production chain
- Multiple entity types working together
- Verification queries after actions
- Strategic bottleneck thinking
"""
from FactoryVerse.dsl.dsl import (
    playing_factorio, walking, map_db, reachable, 
    inventory, crafting
)
from FactoryVerse.dsl.types import MapPosition, Direction


async def bootstrap_iron_production():
    """
    Complete workflow: Find iron, set up automated mining and smelting.
    
    This demonstrates the strategic approach:
    1. Identify bottleneck (need iron plates)
    2. Query to understand state
    3. Plan minimal intervention
    4. Execute actions
    5. Verify results
    """
    
    with playing_factorio():
        print("=== PHASE 1: ASSESS SITUATION ===")
        
        # Check what we have
        current_pos = reachable.get_current_position()
        print(f"Current position: ({current_pos.x:.1f}, {current_pos.y:.1f})")
        
        drill_count = inventory.get_total('burner-mining-drill')
        furnace_count = inventory.get_total('stone-furnace')
        coal_count = inventory.get_total('coal')
        
        print(f"Inventory: {drill_count} drills, {furnace_count} furnaces, {coal_count} coal")
        
        # BOTTLENECK: Need automated iron plate production
        # SOLUTION: Place drill on iron, furnace to smelt
        
        
        print("\n=== PHASE 2: FIND RESOURCES ===")
        
        # Query for nearest iron ore patch
        con = map_db.connection
        iron_patch = con.execute("""
            SELECT 
                patch_id,
                total_amount,
                ST_X(centroid) as x,
                ST_Y(centroid) as y,
                SQRT(
                    POWER(ST_X(centroid) - ?, 2) + 
                    POWER(ST_Y(centroid) - ?, 2)
                ) as distance
            FROM resource_patch
            WHERE resource_name = 'iron-ore'
              AND total_amount > 1000  -- Only substantial patches
            ORDER BY distance
            LIMIT 1
        """, [current_pos.x, current_pos.y]).fetchone()
        
        if not iron_patch:
            print("No iron ore patches found!")
            return
        
        patch_id, amount, iron_x, iron_y, distance = iron_patch
        print(f"Found iron patch {patch_id}:")
        print(f"  Amount: {amount}")
        print(f"  Location: ({iron_x:.1f}, {iron_y:.1f})")
        print(f"  Distance: {distance:.1f} tiles")
        
        # Also check for coal (needed for fuel)
        coal_patch = con.execute("""
            SELECT 
                ST_X(centroid) as x,
                ST_Y(centroid) as y
            FROM resource_patch
            WHERE resource_name = 'coal'
            ORDER BY SQRT(
                POWER(ST_X(centroid) - ?, 2) + 
                POWER(ST_Y(centroid) - ?, 2)
            )
            LIMIT 1
        """, [iron_x, iron_y]).fetchone()
        
        if coal_patch:
            coal_x, coal_y = coal_patch
            print(f"Nearby coal at ({coal_x:.1f}, {coal_y:.1f})")
        
        
        print("\n=== PHASE 3: GATHER RESOURCES ===")
        
        # If we don't have enough coal, mine some first
        if coal_count < 20 and coal_patch:
            print("Mining coal for fuel...")
            await walking.to(MapPosition(x=coal_x, y=coal_y))
            
            coal_resources = reachable.get_resources("coal")
            if coal_resources:
                resource = coal_resources[0]
                # Mine 50 coal in batches
                for _ in range(2):  # 2 batches of 25
                    await resource.mine(max_count=25)
            
            coal_count = inventory.get_total('coal')
            print(f"Now have {coal_count} coal")
        
        
        print("\n=== PHASE 4: BUILD AUTOMATION ===")
        
        # Walk to iron patch
        print("Walking to iron ore patch...")
        await walking.to(MapPosition(x=iron_x, y=iron_y))
        
        # Get drill from inventory
        drill_item = inventory.get_item('burner-mining-drill')
        if not drill_item:
            print("ERROR: No drill available!")
            return
        
        # Get placement cues
        cues = drill_item.get_placement_cues("iron-ore")
        print(f"Found {cues.reachable_count} reachable drill positions")
        
        if cues.reachable_count == 0:
            print("ERROR: No valid drill positions in reach!")
            return
        
        # Place drill
        drill_pos = cues.reachable_positions[0]
        drill = drill_item.place(drill_pos, direction=Direction.NORTH)
        print(f"✓ Placed drill at ({drill.position.x}, {drill.position.y})")
        
        # Fuel the drill
        coal_for_drill = inventory.get_item_stacks("coal", count=10)
        drill.add_fuel(coal_for_drill)
        print("✓ Fueled drill")
        
        # Place furnace near drill output
        furnace_item = inventory.get_item('stone-furnace')
        if not furnace_item:
            print("ERROR: No furnace available!")
            return
        
        valid_positions = drill.get_valid_output_positions(furnace_item)
        if not valid_positions:
            print("ERROR: No valid furnace positions!")
            return
        
        furnace = furnace_item.place(valid_positions[0], direction=Direction.NORTH)
        print(f"✓ Placed furnace at ({furnace.position.x}, {furnace.position.y})")
        
        # Fuel the furnace
        coal_for_furnace = inventory.get_item_stacks("coal", count=10)
        furnace.add_fuel(coal_for_furnace)
        print("✓ Fueled furnace")
        
        
        print("\n=== PHASE 5: VERIFY SETUP ===")
        
        # Query database to confirm entities are placed
        placed_entities = con.execute("""
            SELECT entity_name, position.x, position.y
            FROM map_entity
            WHERE entity_name IN ('burner-mining-drill', 'stone-furnace')
              AND SQRT(
                  POWER(position.x - ?, 2) + 
                  POWER(position.y - ?, 2)
              ) < 20
        """, [iron_x, iron_y]).fetchall()
        
        print(f"Entities placed near iron patch:")
        for name, x, y in placed_entities:
            print(f"  {name} at ({x:.1f}, {y:.1f})")
        
        # Check drill's mining area
        search_area = drill.get_search_area()
        print(f"\nDrill search area: {search_area}")
        
        # Verify iron ore is in mining area
        tiles_in_area = con.execute("""
            SELECT COUNT(*) as tile_count, SUM(amount) as total_ore
            FROM resource_tile
            WHERE name = 'iron-ore'
              AND ST_Intersects(
                  ST_Point(position.x, position.y),
                  ?
              )
        """, [search_area]).fetchone()
        
        tile_count, total_ore = tiles_in_area
        print(f"Iron ore in drill area: {tile_count} tiles, {total_ore} total")
        
        
        print("\n=== SUCCESS ===")
        print("✓ Automated iron ore mining operational")
        print("✓ Smelting ready (needs inserter for full automation)")
        print("\nNext bottleneck: Need inserter to move ore from drill to furnace")
        print("Then: Scale up with more drills and furnaces")


# This example shows the complete strategic pattern:
# 1. Assess current state and identify bottleneck
# 2. Query database to find what you need
# 3. Plan the minimal intervention
# 4. Execute the plan step by step
# 5. Verify that reality matches your expectations
# 6. Identify the next bottleneck
#
# This is NOT a checklist to follow rigidly - it's a thinking framework.
# Adapt based on what you find and what bottlenecks you encounter.
