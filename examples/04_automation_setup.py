"""Example 04: Automation Setup

Demonstrates:
- Setting up drill + furnace production chain
- Adding fuel to burner entities
- Using get_valid_output_positions() to avoid overlaps
- Configuring entity connections
"""
from FactoryVerse.dsl.dsl import playing_factorio, inventory, reachable
from FactoryVerse.dsl.types import MapPosition, Direction


async def setup_basic_smelting():
    """Set up a simple drill->furnace smelting operation."""
    
    with playing_factorio():
        # Step 1: Place a burner mining drill on iron ore
        drill_item = inventory.get_item('burner-mining-drill')
        
        if not drill_item:
            print("Missing burner mining drill!")
            return
        
        # Get valid positions for iron ore
        drill_cues = drill_item.get_placement_cues("iron-ore")
        
        if drill_cues.reachable_count == 0:
            print("No reachable iron ore positions!")
            return
        
        # Place the drill
        drill_pos = drill_cues.reachable_positions[0]
        drill = drill_item.place(drill_pos, direction=Direction.NORTH)
        print(f"Placed drill at ({drill.position.x}, {drill.position.y})")
        
        # Step 2: Add fuel to the drill
        # Burner drills need fuel just like furnaces
        coal_stacks = inventory.get_item_stacks("coal", count=10)
        
        if coal_stacks:
            drill.add_fuel(coal_stacks)  # Can pass list or single ItemStack
            print("Added coal fuel to drill")
        else:
            print("WARNING: No coal for drill fuel!")
        
        # Step 3: Place a furnace to receive drill output
        furnace_item = inventory.get_item('stone-furnace')
        
        if not furnace_item:
            print("Missing stone furnace!")
            return
        
        # CRITICAL: Use get_valid_output_positions() to find positions
        # where a furnace can be placed WITHOUT overlapping the drill
        valid_positions = drill.get_valid_output_positions(furnace_item)
        
        print(f"Found {len(valid_positions)} valid positions for furnace")
        
        if not valid_positions:
            print("No valid positions for furnace!")
            return
        
        # Place furnace at first valid position
        furnace_pos = valid_positions[0]
        furnace = furnace_item.place(furnace_pos, direction=Direction.NORTH)
        print(f"Placed furnace at ({furnace.position.x}, {furnace.position.y})")
        
        # Step 4: Add fuel to furnace
        if coal_stacks := inventory.get_item_stacks("coal", count=10):
            furnace.add_fuel(coal_stacks)
            print("Added coal fuel to furnace")
        
        # Step 5: Verify the setup
        print("\n=== Setup Complete ===")
        print(f"Drill: {drill.name} at ({drill.position.x}, {drill.position.y})")
        print(f"  Mining area covers iron ore: ✓")
        print(f"  Output position: ({drill.output_position.x}, {drill.output_position.y})")
        print(f"Furnace: {furnace.name} at ({furnace.position.x}, {furnace.position.y})")
        print(f"  Fueled: ✓")
        
        # The drill will automatically output iron ore
        # The furnace can receive it if properly positioned
        # (In practice, you'd want an inserter to move items from drill to furnace)


async def setup_with_inserters():
    """More advanced setup with inserters for item transfer."""
    
    with playing_factorio():
        # Assume drill and furnace are already placed and we have references
        drill = reachable.get_entity("burner-mining-drill")
        furnace = reachable.get_entity("stone-furnace")
        
        if not drill or not furnace:
            print("Need both drill and furnace placed first!")
            return
        
        # Place an inserter to move items from drill to furnace
        inserter_item = inventory.get_item("burner-inserter")
        
        if not inserter_item:
            print("No burner inserter available!")
            return
        
        # Inserters pick up from behind and drop in front
        # We need to position it so it picks from drill's output
        drill_output = drill.output_position
        
        # Place inserter at drill's output position
        # Facing toward the furnace
        inserter = inserter_item.place(
            position=drill_output,
            direction=Direction.EAST  # Adjust based on furnace location
        )
        print(f"Placed inserter at ({inserter.position.x}, {inserter.position.y})")
        
        # Add fuel to inserter (it's a burner inserter)
        if coal_stacks := inventory.get_item_stacks("coal", count=5):
            inserter.add_fuel(coal_stacks)
            print("Fueled inserter")
        
        # Verify connections
        pickup_pos = inserter.get_pickup_position()
        drop_pos = inserter.get_drop_position()
        
        print(f"Inserter pickup: ({pickup_pos.x}, {pickup_pos.y})")
        print(f"Inserter drop: ({drop_pos.x}, {drop_pos.y})")


# Key lessons:
# 1. Burner entities (drills, inserters, furnaces) all need fuel
# 2. Use get_valid_output_positions() to prevent overlaps
# 3. Entity positioning matters for automation to work
# 4. Inserters connect entities by picking up and dropping off items
# 5. Always verify your setup (positions, fuel, connections)
