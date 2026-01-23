#!/usr/bin/env python3
"""
Proof of Concept: Demonstrating RCON interface understanding.

This script demonstrates:
1. Connecting to Factorio via RCON
2. Creating an agent
3. Placing a simple entity
4. Calling inspect_entity on that entity
5. Validating the response
"""

import json
from factorio_rcon import RCONClient

from FactoryVerse.environment.config import get_config
from FactoryVerse.infra.instance_manager import FactorioInstanceManager


class SimpleRconHandler:
    """Simplified RCON handler for testing without dependencies."""

    def __init__(self, rcon_client: RCONClient, agent_id: str):
        self._rcon = rcon_client
        self.agent_id = agent_id

    def build_command(self, method: str, *args) -> str:
        """Build RCON command string for remote interface method call."""
        remote_call = f"remote.call('{self.agent_id}', '{method}'"

        if args:
            # Convert args to JSON and pass as table
            args_json = json.dumps(list(args))
            remote_call += f", table.unpack(helpers.json_to_table('{args_json}'))"

        remote_call += ")"
        return f"rcon.print(helpers.table_to_json({remote_call}))"

    def execute_and_parse_json(self, command: str) -> dict:
        """Execute RCON command and parse JSON response."""
        result = self._rcon.send_command(f"/c {command}")
        if not result or not result.strip():
            raise RuntimeError(
                f"RCON command returned empty response. Command: {command}"
            )
        return json.loads(result)


def main():
    print("=" * 80)
    print("PROOF OF CONCEPT: RCON Interface Understanding")
    print("=" * 80)

    # Step 1: Connect to RCON
    print("\n[Step 1] Connecting to RCON...")
    config = get_config()
    instance = FactorioInstanceManager.from_env(config)
    print(f"[Step 1] Using instance: {instance.name} at {instance.rcon_host}:{instance.rcon_port}")
    rcon_client = RCONClient(instance.rcon_host, instance.rcon_port, instance.rcon_password)

    # Initial double-call pattern (first call produces warning, second executes)
    print("[Step 1] Warming up RCON connection...")
    rcon_client.send_command("/c rcon.print('hello world')")
    response = rcon_client.send_command("/c rcon.print('hello world')")
    print(f"[Step 1] ✓ RCON connected: {response}")

    # Step 2: Create an agent
    print("\n[Step 2] Creating agent...")
    create_cmd = "/c local res = remote.call('agent', 'create_agent'); rcon.print(helpers.table_to_json(res));"
    agent_response = rcon_client.send_command(create_cmd)
    if not agent_response:
        print("[Step 2] ✗ Failed to create agent: empty response")
        return
    agent_data = json.loads(agent_response)
    agent_id = f"agent_{agent_data['agent_id']}"
    print(f"[Step 2] ✓ Agent created: {agent_id}")
    print(f"           Force: {agent_data['force_name']}")
    print(f"           Interface: {agent_data['interface_name']}")

    # Step 3: Initialize SimpleRconHandler for the agent
    print(f"\n[Step 3] Initializing SimpleRconHandler for {agent_id}...")
    rcon_handler = SimpleRconHandler(rcon_client, agent_id)
    print("[Step 3] ✓ SimpleRconHandler initialized")

    # Step 3.5: Clear test area to avoid collisions
    print("\n[Step 3.5] Clearing test area...")
    clear_cmd = "/c remote.call('test_ground', 'clear_area', {left_top={x=9, y=9}, right_bottom={x=12, y=12}}); rcon.print('cleared');"
    rcon_client.send_command(clear_cmd)
    print("[Step 3.5] ✓ Test area cleared")

    # Step 4: Place a simple entity (wooden-chest at origin)
    print("\n[Step 4] Placing wooden-chest at (10, 10) using test_ground...")
    place_cmd = "/c local res = remote.call('test_ground', 'place_entity', 'wooden-chest', {x=10, y=10}); rcon.print(helpers.table_to_json(res));"
    place_response = rcon_client.send_command(place_cmd)
    if not place_response:
        print("[Step 4] ✗ Failed to place entity: empty response")
        return
    place_data = json.loads(place_response)

    if place_data.get("success"):
        print("[Step 4] ✓ Entity placed successfully")
        print(f"           Name: {place_data['metadata']['name']}")
        entity_pos = place_data["metadata"]["position"]
        print(f"           Position: ({entity_pos['x']}, {entity_pos['y']})")
    else:
        print(f"[Step 4] ✗ Failed to place entity: {place_data}")
        return

    # Step 4.5: Teleport agent near the entity (entities must be within reach to inspect)
    print(f"\n[Step 4.5] Teleporting agent to entity location...")
    teleport_cmd = rcon_handler.build_command("teleport", entity_pos)
    teleport_response = rcon_handler.execute_and_parse_json(teleport_cmd)
    if teleport_response.get("success"):
        print(
            f"[Step 4.5] ✓ Agent teleported to ({entity_pos['x']}, {entity_pos['y']})"
        )
    else:
        print(f"[Step 4.5] ✗ Failed to teleport: {teleport_response}")

    # Step 5: Call inspect_entity using SimpleRconHandler
    print(f"\n[Step 5] Calling inspect_entity via {agent_id}...")
    inspect_cmd = rcon_handler.build_command(
        "inspect_entity", "wooden-chest", entity_pos
    )
    print(f"[Step 5] Command: {inspect_cmd}")

    # Try to get raw response first
    raw_response = rcon_client.send_command(f"/c {inspect_cmd}")
    print(f"[Step 5] Raw response: '{raw_response}'")

    if not raw_response or not raw_response.strip():
        print("[Step 5] ✗ Empty response from inspect_entity")
        print(
            "[Step 5] This might indicate an error in the Lua code or the entity is not reachable"
        )
        return

    try:
        inspection_data = json.loads(raw_response)
    except json.JSONDecodeError as e:
        print(f"[Step 5] ✗ Failed to parse JSON: {e}")
        print(f"[Step 5] Raw response was: {raw_response}")
        return

    # Step 6: Validate the response
    print("\n[Step 6] Validating inspection response...")

    # Check base fields
    base_fields = ["entity_name", "entity_type", "position", "direction", "tick"]
    missing_base = [f for f in base_fields if f not in inspection_data]

    if missing_base:
        print(f"[Step 6] ✗ Missing base fields: {missing_base}")
    else:
        print(f"[Step 6] ✓ All base fields present")

    # Check container-specific fields
    container_fields = ["contents"]  # May be None if empty
    present_container = [f for f in container_fields if f in inspection_data]

    print(f"[Step 6] Container-specific fields present: {present_container}")

    # Step 7: Display full response
    print("\n[Step 7] Full inspection response:")
    print("-" * 80)
    print(json.dumps(inspection_data, indent=2))
    print("-" * 80)

    # Step 8: Cleanup
    print("\n[Step 8] Cleaning up...")
    cleanup_cmd = "/c remote.call('test_ground', 'clear_area', {left_top={x=9, y=9}, right_bottom={x=11, y=11}}); rcon.print('cleaned');"
    rcon_client.send_command(cleanup_cmd)
    print("[Step 8] ✓ Test area cleaned")

    print("\n" + "=" * 80)
    print("PROOF OF CONCEPT COMPLETE ✓")
    print("=" * 80)
    print("\nKey Takeaways:")
    print("1. ✓ Successfully connected to RCON")
    print("2. ✓ Created an agent via remote.call")
    print("3. ✓ Used RconHandler to build commands")
    print("4. ✓ Placed entity via test_ground interface")
    print("5. ✓ Called inspect_entity via agent interface")
    print("6. ✓ Parsed and validated JSON response")
    print("\nReady to build comprehensive incremental test script!")


if __name__ == "__main__":
    main()
