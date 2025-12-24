"""Example 01: Basic Query and Walk

Demonstrates:
- Querying the database for resource patches
- Walking to a specific location
- Basic error handling and position verification
"""
from FactoryVerse.dsl.dsl import playing_factorio, walking, map_db, reachable
from FactoryVerse.dsl.types import MapPosition


async def query_and_walk_to_resource():
    """Query for nearest iron ore patch and walk to it."""
    
    with playing_factorio():
        # Get current position
        current_pos = reachable.get_current_position()
        print(f"Current position: ({current_pos.x}, {current_pos.y})")
        
        # Query database for nearest iron ore patch
        con = map_db.connection
        result = con.execute("""
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
            ORDER BY distance
            LIMIT 1
        """, [current_pos.x, current_pos.y]).fetchone()
        
        if not result:
            print("No iron ore patches found!")
            return
        
        patch_id, amount, x, y, distance = result
        print(f"Found iron ore patch {patch_id}:")
        print(f"  Amount: {amount}")
        print(f"  Location: ({x:.1f}, {y:.1f})")
        print(f"  Distance: {distance:.1f} tiles")
        
        # Walk to the patch centroid
        target_pos = MapPosition(x=x, y=y)
        print(f"\nWalking to iron ore patch...")
        
        try:
            await walking.to(target_pos)
            print("Arrived at destination!")
            
            # Verify new position
            new_pos = reachable.get_current_position()
            print(f"New position: ({new_pos.x:.1f}, {new_pos.y:.1f})")
            
        except Exception as e:
            print(f"Walking failed: {e}")


# This example demonstrates the fundamental pattern:
# 1. Query the database to find what you need
# 2. Use the query results to plan your action
# 3. Execute the action (walking in this case)
# 4. Verify the result
