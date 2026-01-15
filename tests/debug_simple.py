#!/usr/bin/env python3
"""
Simplified Evidence Gathering - Test one property at a time
"""

import json
from factorio_rcon import RCONClient


def test_entity(entity_name: str):
    """Test a single entity's properties."""
    print(f"\n{'=' * 80}")
    print(f"ENTITY: {entity_name}")
    print(f"{'=' * 80}")

    rcon = RCONClient("localhost", 27100, "factorio")
    rcon.send_command("/c rcon.print('hello')")
    rcon.send_command("/c rcon.print('hello')")

    # Clear and place
    x, y = 10, 10
    rcon.send_command(
        f"/c remote.call('test_ground', 'clear_area', {{left_top={{x=7, y=7}}, right_bottom={{x=13, y=13}}}}); rcon.print('ok');"
    )

    place_cmd = f"/c local res = remote.call('test_ground', 'place_entity', '{entity_name}', {{x={x}, y={y}}}); rcon.print(helpers.table_to_json(res));"
    response = rcon.send_command(place_cmd)
    data = json.loads(response)

    if not data.get("success"):
        print(f"  ✗ Failed to place")
        return

    pos = data["metadata"]["position"]
    px, py = pos["x"], pos["y"]
    print(f"  ✓ Placed at ({px}, {py})")

    # Test entity.type
    cmd = f"/c local e = game.surfaces[1].find_entity('{entity_name}', {{x={px}, y={py}}}); if e then rcon.print(e.type) else rcon.print('NOT_FOUND') end;"
    entity_type = rcon.send_command(cmd)
    print(f"  entity.type: '{entity_type}'")

    # Test belt_shape
    cmd = f"/c local e = game.surfaces[1].find_entity('{entity_name}', {{x={px}, y={py}}}); if e and e.belt_shape then rcon.print(e.belt_shape) else rcon.print('NIL') end;"
    belt_shape = rcon.send_command(cmd)
    print(f"  entity.belt_shape: '{belt_shape}'")

    # Test energy_generated_last_tick
    cmd = f"/c local e = game.surfaces[1].find_entity('{entity_name}', {{x={px}, y={py}}}); if e and e.energy_generated_last_tick then rcon.print(e.energy_generated_last_tick) else rcon.print('NIL') end;"
    energy_gen = rcon.send_command(cmd)
    print(f"  entity.energy_generated_last_tick: '{energy_gen}'")

    # Test power_production
    cmd = f"/c local e = game.surfaces[1].find_entity('{entity_name}', {{x={px}, y={py}}}); if e and e.power_production then rcon.print(e.power_production) else rcon.print('NIL') end;"
    power_prod = rcon.send_command(cmd)
    print(f"  entity.power_production: '{power_prod}'")

    # Test if properties exist but are 0
    cmd = f"/c local e = game.surfaces[1].find_entity('{entity_name}', {{x={px}, y={py}}}); if e then local r = {{}}; r.has_belt_shape = (e.belt_shape ~= nil); r.has_energy_gen = (e.energy_generated_last_tick ~= nil); r.has_power_prod = (e.power_production ~= nil); rcon.print(helpers.table_to_json(r)) else rcon.print('NOT_FOUND') end;"
    props = rcon.send_command(cmd)
    if props and props != "NOT_FOUND":
        props_data = json.loads(props)
        print(f"  Property existence:")
        print(f"    has_belt_shape: {props_data.get('has_belt_shape')}")
        print(f"    has_energy_generated_last_tick: {props_data.get('has_energy_gen')}")
        print(f"    has_power_production: {props_data.get('has_power_prod')}")


def main():
    print("=" * 80)
    print("SIMPLIFIED EVIDENCE GATHERING")
    print("=" * 80)

    # Test failing entities
    test_entity("transport-belt")
    test_entity("underground-belt")
    test_entity("splitter")
    test_entity("solar-panel")
    test_entity("boiler")


if __name__ == "__main__":
    main()
