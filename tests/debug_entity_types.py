#!/usr/bin/env python3
"""
Debug script to check entity types for failing entities.
"""

import json
from factorio_rcon import RCONClient


def main():
    print("Debugging entity types for failing entities...")

    rcon_client = RCONClient("localhost", 27100, "factorio")
    rcon_client.send_command("/c rcon.print('hello')")
    rcon_client.send_command("/c rcon.print('hello')")

    failing_entities = [
        "transport-belt",
        "underground-belt",
        "splitter",
        "solar-panel",
        "boiler",
    ]

    for entity_name in failing_entities:
        print(f"\n{entity_name}:")

        # Clear and place
        clear_cmd = f"/c remote.call('test_ground', 'clear_area', {{left_top={{x=0, y=0}}, right_bottom={{x=5, y=5}}}}); rcon.print('ok');"
        rcon_client.send_command(clear_cmd)

        place_cmd = f"/c local res = remote.call('test_ground', 'place_entity', '{entity_name}', {{x=2, y=2}}); rcon.print(helpers.table_to_json(res));"
        response = rcon_client.send_command(place_cmd)
        if not response:
            print(f"  Failed to place")
            continue

        data = json.loads(response)
        if not data.get("success"):
            print(f"  Failed to place: {data}")
            continue

        pos = data["metadata"]["position"]
        print(f"  Placed at ({pos['x']}, {pos['y']})")

        # Get entity type directly
        check_cmd = f"/c local e = game.surfaces[1].find_entity('{entity_name}', {{x={pos['x']}, y={pos['y']}}}); if e then rcon.print(e.type) else rcon.print('NOT_FOUND') end;"
        entity_type = rcon_client.send_command(check_cmd)
        print(f"  Entity type: '{entity_type}'")

        # Try to inspect
        inspect_cmd = f"/c local e = game.surfaces[1].find_entity('{entity_name}', {{x={pos['x']}, y={pos['y']}}}); if e then local res = inspection.inspect_entity(e); rcon.print(helpers.table_to_json(res)) else rcon.print('NOT_FOUND') end;"
        inspect_response = rcon_client.send_command(inspect_cmd)
        print(
            f"  Inspect response: '{inspect_response[:100] if inspect_response else 'None'}'..."
        )


if __name__ == "__main__":
    main()
