"""
Asynchronous DSL Entity Behavior Tests

Tests for interactions with Factorio entities like furnaces, drills, and inserters.
Verifies that entities process items correctly over time.
"""

import pytest
import asyncio
import time
from FactoryVerse.dsl.agent import PlayingFactory, MapPosition, Direction

@pytest.mark.asyncio
@pytest.mark.dsl
class TestEntityBehaviors:
    """Test DSL entity behavior and interaction."""

    @pytest.fixture(autouse=True)
    async def speed_up_game(self, factory_instance: PlayingFactory, test_ground):
        """Speed up game and reset area during tests."""
        factory_instance._rcon.send_command("/c game.speed = 100.0")
        test_ground.reset_test_area()
        yield
        factory_instance._rcon.send_command("/c game.speed = 1.0")

    async def test_furnace_smelting(self, factory_instance: PlayingFactory, test_ground):
        """Test that a furnace correctly smelts ore into plates."""
        # 1. Setup: Place furnace and teleport agent
        requested_pos = MapPosition(x=10, y=10)
        
        # Teleport away first to ensure no collision during placement
        factory_instance._rcon.send_command('/c remote.call("agent_1", "teleport", {x=0, y=0})')
        factory_instance._rcon.send_command('/c remote.call("admin", "add_items", 1, {["stone-furnace"]=1, ["coal"]=10, ["iron-ore"]=10})')
        
        # Place it
        res = test_ground.place_entity("stone-furnace", x=requested_pos.x, y=requested_pos.y)
        pos = MapPosition(x=res["metadata"]["position"]["x"], y=res["metadata"]["position"]["y"])
        
        # Teleport to a safe distance (1.5 offset from center)
        factory_instance._rcon.send_command(f'/c remote.call("agent_1", "teleport", {{x={pos.x + 1.5}, y={pos.y}}})')
        
        # 2. Preparation: Clear inventory and provide fuel/ore
        factory_instance._rcon.send_command('/c remote.call("admin", "clear_inventory", 1)')
        factory_instance._rcon.send_command('/c remote.call("admin", "add_items", 1, {["coal"]=5, ["iron-ore"]=5})')
        
        # 3. Action: Put fuel and ore into furnace
        factory_instance.put_inventory_item("stone-furnace", position=pos, inventory_type="fuel", item_name="coal", count=5)
        factory_instance.put_inventory_item("stone-furnace", position=pos, inventory_type="input", item_name="iron-ore", count=5)
        
        # 4. Verification: Check progress and status
        # Initial check
        info = factory_instance.inspect_entity("stone-furnace", position=pos)
        print(f"\n[DEBUG] Furnace initial state: {info['status']}, progress: {info.get('crafting_progress', 0)}")
        assert info["status"] == "working"
        
        # Wait for smelting to finish (needs ~0.3s per plate at 10x speed)
        await asyncio.sleep(5)
        
        # Final check
        info = factory_instance.inspect_entity("stone-furnace", position=pos)
        print(f"[DEBUG] Furnace final state: {info['status']}, output: {info.get('inventories', {}).get('output', {})}")
        
        # Output should have iron-plates
        output = info.get("inventories", {}).get("output", {})
        assert output.get("iron-plate", 0) >= 1
        
        # 5. Extraction: Take items out
        factory_instance.take_inventory_item("stone-furnace", position=pos, inventory_type="output", item_name="iron-plate")
        
        # Verify agent has them
        inv = factory_instance.inventory.get_total("iron-plate")
        assert inv >= 1

    async def test_inserter_transfer(self, factory_instance: PlayingFactory, test_ground):
        """Test that an inserter transfers items between two containers."""
        # 1. Setup: Place two wooden chests and an inserter
        factory_instance._rcon.send_command('/c remote.call("agent_1", "teleport", {x=0, y=0})')
        
        res1 = test_ground.place_entity("wooden-chest", x=20.5, y=20.5)
        chest1_pos = MapPosition(x=res1["metadata"]["position"]["x"], y=res1["metadata"]["position"]["y"])
        
        # Teleport near for placing the rest (offset to avoid collision)
        factory_instance._rcon.send_command(f'/c remote.call("agent_1", "teleport", {{x=21.5, y=23}})')
        factory_instance._rcon.send_command('/c remote.call("admin", "add_items", 1, {["burner-inserter"]=1, ["wooden-chest"]=1, ["coal"]=10, ["iron-plate"]=20})')
        
        res_ins = factory_instance.place_entity("burner-inserter", position=MapPosition(x=21.5, y=20.5), direction=Direction.EAST)
        inserter_pos = MapPosition(x=res_ins["position"]["x"], y=res_ins["position"]["y"])
        
        res2 = factory_instance.place_entity("wooden-chest", position=MapPosition(x=22.5, y=20.5))
        chest2_pos = MapPosition(x=res2["position"]["x"], y=res2["position"]["y"])
        
        # Provide power (infinite energy source)
        test_ground.place_entity("electric-energy-interface", x=21.5, y=21.5)
        
        # 2. Action: Provide fuel to inserter and items to source chest (chest2, because inserter is reversed)
        factory_instance.put_inventory_item("burner-inserter", position=inserter_pos, inventory_type="fuel", item_name="coal", count=5)
        factory_instance.put_inventory_item("wooden-chest", position=chest2_pos, inventory_type="chest", item_name="iron-plate", count=10)
        
        # Diagnostic: Check inserter status
        ins_info = factory_instance.inspect_entity("burner-inserter", position=inserter_pos)
        print(f"\n[DEBUG] Inserter status: {ins_info['status']}, held: {ins_info.get('held_item', 'none')}")
        
        # 3. Verification: Wait and check dest chest (with retries and diagnostics)
        for i in range(10):
            await asyncio.sleep(1)
            info = factory_instance.inspect_entity("wooden-chest", position=chest1_pos)
            output = info.get("inventories", {}).get("chest", {})
            if output.get("iron-plate", 0) > 0:
                print(f"[DEBUG] Transfer success! Dest chest contents: {output}")
                break
            
            ins_info = factory_instance.inspect_entity("burner-inserter", position=inserter_pos)
            print(f"[DEBUG] Waiting for transfer: inserter status={ins_info['status']}, held={ins_info.get('held_item', 'none')}, pickup={ins_info.get('pickup_position')}, drop={ins_info.get('drop_position')}")
        
        info = factory_instance.inspect_entity("wooden-chest", position=chest1_pos)
        output = info.get("inventories", {}).get("chest", {})
        assert output.get("iron-plate", 0) > 0

    async def test_mining_drill_burner(self, factory_instance: PlayingFactory, test_ground):
        """Test that a burner mining drill mines resources into an attached container."""
        # 1. Setup: Place ore, drill (2x2), and chest (1x1)
        test_ground.place_iron_patch(x=30, y=30, size=2, amount=1000)
        
        # Teleport away for patch placement, then near but offset
        factory_instance._rcon.send_command(f'/c remote.call("agent_1", "teleport", {{x=33, y=33}})')
        factory_instance._rcon.send_command('/c remote.call("admin", "add_items", 1, {["burner-mining-drill"]=1, ["wooden-chest"]=1, ["coal"]=10})')
        
        res_drill = factory_instance.place_entity("burner-mining-drill", position=MapPosition(x=30, y=30), direction=Direction.NORTH)
        drill_pos = MapPosition(x=res_drill["position"]["x"], y=res_drill["position"]["y"])
        
        # 2. Setup: Place chest in drop location
        # Burner mining drill facing North (0) at (30,30) drops at (29.5, 28.7)
        # So we place a chest at (29.5, 28.5) to catch it.
        res_chest = factory_instance.place_entity("wooden-chest", position=MapPosition(x=29.5, y=28.5))
        chest_pos = MapPosition(x=res_chest["position"]["x"], y=res_chest["position"]["y"])
        
        # 3. Action: Provide fuel to drill
        factory_instance.put_inventory_item("burner-mining-drill", position=drill_pos, inventory_type="fuel", item_name="coal", count=5)
        
        # 4. Verification: Wait and check chest (with retries)
        for i in range(10):
            await asyncio.sleep(1)
            info = factory_instance.inspect_entity("wooden-chest", position=chest_pos)
            contents = info.get("inventories", {}).get("chest", {})
            if contents.get("iron-ore", 0) > 0:
                print(f"[DEBUG] Mining success! Drill output chest: {contents}")
                break
                
            drill_info = factory_instance.inspect_entity("burner-mining-drill", position=drill_pos)
            print(f"[DEBUG] Waiting for mining: status={drill_info['status']}, progress={drill_info.get('mining_progress', 0)}, drop_pos={drill_info.get('drop_position')}")
        
        info = factory_instance.inspect_entity("wooden-chest", position=chest_pos)
        contents = info.get("inventories", {}).get("chest", {})
        assert contents.get("iron-ore", 0) > 0

    async def test_assembling_machine_recipe(self, factory_instance: PlayingFactory, test_ground):
        """Test setting and verifying recipe on an assembling machine."""
        # 1. Setup: Place assembler
        factory_instance._rcon.send_command('/c game.forces.player.technologies["automation"].researched = true')
        factory_instance._rcon.send_command('/c remote.call("agent_1", "teleport", {x=42, y=42})')
        factory_instance._rcon.send_command('/c remote.call("admin", "add_items", 1, {["assembling-machine-1"]=1})')
        
        res = factory_instance.place_entity("assembling-machine-1", position=MapPosition(x=40, y=40))
        pos = MapPosition(x=res["position"]["x"], y=res["position"]["y"])
        
        # Provide power
        test_ground.place_entity("electric-energy-interface", x=40, y=42)
        
        # 2. Get entity instance from DSL
        assembler = factory_instance.reachable_entities.get_entity("assembling-machine-1", pos)
        assert assembler is not None
        
        # 3. Action: Set recipe using string
        assembler.set_recipe("iron-gear-wheel")
        
        # 4. Verification: Inspect and check recipe
        info = assembler.inspect(raw_data=True)
        assert info.get("recipe") == "iron-gear-wheel"
        
        # 5. Action: Set recipe using Recipe object
        from FactoryVerse.dsl.dsl import crafting
        assembler.set_recipe(crafting["copper-cable"])
        
        # 6. Verification: Inspect and check recipe
        info = assembler.inspect(raw_data=True)
        assert info.get("recipe") == "copper-cable"

        # 7. Action: Clear recipe
        assembler.set_recipe(None)
        info = assembler.inspect(raw_data=True)
        assert info.get("recipe") is None
