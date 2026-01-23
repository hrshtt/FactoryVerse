#!/usr/bin/env python3
"""
Test: Verify inspect_entity works without reachability constraint.

This script confirms that entities can be inspected from any distance,
without requiring the agent to be near the entity.
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
    print("TEST: Inspect Entity Without Reachability Constraint")
    print("=" * 80)

    # Connect to RCON
    print("\n[1] Connecting to RCON...")
    config = get_config()
    instance = FactorioInstanceManager.from_env(config)
    rcon_client = RCONClient(instance.rcon_host, instance.rcon_port, instance.rcon_password)
    rcon_client.send_command("/c rcon.print('hello')")
    rcon_client.send_command("/c rcon.print('hello')")
    print("[1] ✓ Connected")

    # Create agent
    print("\n[2] Creating agent...")
    create_cmd = "/c local res = remote.call('agent', 'create_agent'); rcon.print(helpers.table_to_json(res));"
    agent_response = rcon_client.send_command(create_cmd)
    if not agent_response:
        print("[2] ✗ Failed to create agent")
        return
    agent_data = json.loads(agent_response)
    agent_id = f"agent_{agent_data['agent_id']}"
    print(f"[2] ✓ Agent created: {agent_id}")

    rcon_handler = SimpleRconHandler(rcon_client, agent_id)

    # Get agent's initial position
    print("\n[3] Getting agent position...")
    pos_cmd = rcon_handler.build_command("get_position")
    agent_pos = rcon_handler.execute_and_parse_json(pos_cmd)
    print(f"[3] ✓ Agent at ({agent_pos['x']}, {agent_pos['y']})")

    # Clear and place entity far from agent
    print("\n[4] Placing entity FAR from agent (at 100, 100)...")
    clear_cmd = "/c remote.call('test_ground', 'clear_area', {left_top={x=99, y=99}, right_bottom={x=102, y=102}}); rcon.print('cleared');"
    rcon_client.send_command(clear_cmd)

    place_cmd = "/c local res = remote.call('test_ground', 'place_entity', 'wooden-chest', {x=100, y=100}); rcon.print(helpers.table_to_json(res));"
    place_response = rcon_client.send_command(place_cmd)
    if not place_response:
        print("[4] ✗ Failed to place entity")
        return
    place_data = json.loads(place_response)

    if not place_data.get("success"):
        print(f"[4] ✗ Failed to place entity: {place_data}")
        return

    entity_pos = place_data["metadata"]["position"]
    print(f"[4] ✓ Entity placed at ({entity_pos['x']}, {entity_pos['y']})")

    # Calculate distance
    distance = (
        (entity_pos["x"] - agent_pos["x"]) ** 2
        + (entity_pos["y"] - agent_pos["y"]) ** 2
    ) ** 0.5
    print(f"[4]   Distance from agent: {distance:.1f} tiles")

    # Try to inspect WITHOUT teleporting
    print("\n[5] Inspecting entity WITHOUT teleporting agent...")
    print(f"[5]   (Testing that reachability constraint is removed)")

    inspect_cmd = rcon_handler.build_command(
        "inspect_entity", "wooden-chest", entity_pos
    )

    try:
        raw_response = rcon_client.send_command(f"/c {inspect_cmd}")

        if not raw_response or raw_response.strip() == "None":
            print("[5] ✗ FAILED: inspect_entity returned None")
            print("[5]   The reachability constraint may still be active!")
            return

        inspection_data = json.loads(raw_response)

        # Validate response
        print("[5] ✓ SUCCESS: inspect_entity worked from distance!")
        print(f"[5]   Entity name: {inspection_data.get('entity_name')}")
        print(f"[5]   Entity type: {inspection_data.get('entity_type')}")
        print(
            f"[5]   Position: ({inspection_data.get('position', {}).get('x')}, {inspection_data.get('position', {}).get('y')})"
        )
        print(f"[5]   Direction: {inspection_data.get('direction')}")
        print(f"[5]   Tick: {inspection_data.get('tick')}")

        # Check for base fields
        base_fields = ["entity_name", "entity_type", "position", "direction", "tick"]
        missing = [f for f in base_fields if f not in inspection_data]

        if missing:
            print(f"\n[6] ⚠ Missing base fields: {missing}")
        else:
            print("\n[6] ✓ All base fields present")

        # Show full response
        print("\n[7] Full inspection response:")
        print("-" * 80)
        print(json.dumps(inspection_data, indent=2))
        print("-" * 80)

        print("\n" + "=" * 80)
        print("✓ CONFIRMED: Reachability constraint has been removed!")
        print("✓ Entities can be inspected from any distance")
        print("=" * 80)

    except Exception as e:
        print(f"[5] ✗ Error: {e}")
        return

    # Cleanup
    print("\n[8] Cleaning up...")
    rcon_client.send_command(clear_cmd)
    print("[8] ✓ Done")


if __name__ == "__main__":
    main()
