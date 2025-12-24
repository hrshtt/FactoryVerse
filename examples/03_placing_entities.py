"""Example 03: Placing Entities

Demonstrates:
- Getting items from inventory
- Using get_placement_cues() for validation
- Placing entities with proper direction
- Ghost placement for later building
- Understanding tile vs entity coordinates
"""
from FactoryVerse.dsl.dsl import playing_factorio, inventory, reachable
from FactoryVerse.dsl.types import MapPosition, Direction


async def place_furnace_simple():
    """Basic entity placement."""
    
    with playing_factorio():
        # Get a furnace from inventory
        furnace_item = inventory.get_item('stone-furnace')
        
        if not furnace_item:
            print("No stone furnace in inventory!")
            return
        
        # Get current position
        pos = reachable.get_current_position()
        
        # Place furnace 5 tiles east
        # Furnaces are 2x2, so center will be on integer coordinate
        placement_pos = MapPosition(x=pos.x + 5, y=pos.y)
        
        try:
            furnace = furnace_item.place(
                position=placement_pos,
                direction=Direction.NORTH  # Direction usually doesn't matter for furnaces
            )
            print(f"Placed {furnace.name} at ({furnace.position.x}, {furnace.position.y})")
            
        except Exception as e:
            print(f"Placement failed: {e}")


async def place_drill_with_validation():
    """Place a drill using placement cues for validation."""
    
    with playing_factorio():
        drill_item = inventory.get_item('burner-mining-drill')
        
        if not drill_item:
            print("No burner mining drill in inventory!")
            return
        
        # Get placement cues for iron ore
        # This returns ALL valid positions in scanned chunks
        cues = drill_item.get_placement_cues("iron-ore")
        
        print(f"Found {cues.count} total valid positions")
        print(f"  {cues.reachable_count} are within reach")
        
        # BEST PRACTICE: Use reachable_positions first
        if cues.reachable_count > 0:
            # Place at first reachable position
            pos = cues.reachable_positions[0]
            
            drill = drill_item.place(
                position=pos,
                direction=Direction.NORTH
            )
            print(f"Placed drill at ({drill.position.x}, {drill.position.y})")
            
        else:
            print("No reachable positions! Need to walk closer first.")
            
            # Could walk to a position from cues.positions
            # then place from there


async def place_ghosts_for_later():
    """Place ghost entities for building in bulk later."""
    
    with playing_factorio():
        drill_item = inventory.get_item('burner-mining-drill')
        
        if not drill_item:
            print("No burner mining drill in inventory!")
            return
        
        # Get cues for coal
        cues = drill_item.get_placement_cues("coal")
        
        # Place ghosts at first 5 positions (label them for organization)
        ghosts_placed = 0
        for pos in cues.positions[:5]:
            try:
                ghost = drill_item.place_ghost(
                    position=pos,
                    direction=Direction.NORTH,
                    label="coal-mining-setup"
                )
                ghosts_placed += 1
                
            except Exception as e:
                print(f"Ghost placement failed at ({pos.x}, {pos.y}): {e}")
        
        print(f"Placed {ghosts_placed} ghost drills")
        
        # Later, you can build all ghosts with the same label:
        # from FactoryVerse.dsl.dsl import ghosts
        # await ghosts.build_ghosts(label="coal-mining-setup", count=32)


# Key coordinate understanding:
# - Tiles have centers at half-integers: (0.5, 0.5), (1.5, 1.5), etc.
# - Odd-sized entities (1x1, 3x3) center on tile centers (half-integers)
# - Even-sized entities (2x2, 4x4) center on tile boundaries (integers)
# - get_placement_cues() returns TILE centers, not entity centers
# - For a 2x2 drill, the entity center might not match the cue position exactly
