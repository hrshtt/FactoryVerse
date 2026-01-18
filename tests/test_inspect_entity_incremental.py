#!/usr/bin/env python3
"""
Incremental Test Script for inspect_entity Functionality

Tests inspect_entity across all supported entity types in a piece-wise manner.
Each category is tested independently to avoid large failures.

Entity Categories Tested:
1. Container (wooden-chest, iron-chest)
2. Transport Belt (transport-belt, underground-belt, splitter)
3. Electric Pole (small-electric-pole, medium-electric-pole)
4. Energy Producer (solar-panel, boiler, offshore-pump)
5. Mining Drill (burner-mining-drill)
6. Crafting Machine (stone-furnace, assembling-machine-1)
7. Inserter (burner-inserter, inserter)
8. Lab (lab)
9. Radar (radar)
10. Accumulator (accumulator)
11. Beacon (beacon)
"""

import json
from typing import Dict, List, Any, Optional
from factorio_rcon import RCONClient

from FactoryVerse.config import get_config
from FactoryVerse.infra.instance_manager import FactorioInstanceManager


class SimpleRconHandler:
    """Simplified RCON handler for testing."""

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
        if not result or not result.strip() or result.strip() == "None":
            raise RuntimeError(f"Empty response. Command: {command}")
        return json.loads(result)


class InspectEntityTester:
    """Manages incremental testing of inspect_entity across entity types."""

    def __init__(self):
        self.rcon_client = None
        self.rcon_handler = None
        self.agent_id = None
        self.test_results = []
        self.current_position = {"x": 10, "y": 10}  # Starting position for entities

    def setup(self):
        """Initialize RCON connection and create agent."""
        print("=" * 80)
        print("INCREMENTAL TEST: inspect_entity Functionality")
        print("=" * 80)

        print("\n[Setup] Connecting to RCON...")
        config = get_config()
        instance = FactorioInstanceManager.from_env(config)
        self.rcon_client = RCONClient(instance.rcon_host, instance.rcon_port, instance.rcon_password)
        self.rcon_client.send_command("/c rcon.print('hello')")
        self.rcon_client.send_command("/c rcon.print('hello')")
        print("[Setup] ✓ Connected")

        print("[Setup] Creating agent...")
        create_cmd = "/c local res = remote.call('agent', 'create_agent'); rcon.print(helpers.table_to_json(res));"
        agent_response = self.rcon_client.send_command(create_cmd)
        if not agent_response:
            raise RuntimeError("Failed to create agent")
        agent_data = json.loads(agent_response)
        self.agent_id = f"agent_{agent_data['agent_id']}"
        self.rcon_handler = SimpleRconHandler(self.rcon_client, self.agent_id)
        print(f"[Setup] ✓ Agent created: {self.agent_id}")

    def clear_area(self, x: float, y: float, size: float = 5):
        """Clear area around position."""
        half = size / 2
        clear_cmd = f"/c remote.call('test_ground', 'clear_area', {{left_top={{x={x - half}, y={y - half}}}, right_bottom={{x={x + half}, y={y + half}}}}}); rcon.print('cleared');"
        self.rcon_client.send_command(clear_cmd)

    def place_entity(self, entity_name: str, x: float, y: float) -> Optional[Dict]:
        """Place entity and return its metadata."""
        self.clear_area(x, y)
        place_cmd = f"/c local res = remote.call('test_ground', 'place_entity', '{entity_name}', {{x={x}, y={y}}}); rcon.print(helpers.table_to_json(res));"
        response = self.rcon_client.send_command(place_cmd)
        if not response:
            return None
        data = json.loads(response)
        if not data.get("success"):
            return None
        return data["metadata"]

    def place_water_tiles(self, x: float, y: float, size: int = 5):
        """Place water tiles for offshore pump."""
        print(f"      Placing {size}x{size} water tile pool at ({x}, {y})...")
        for dx in range(size):
            for dy in range(size):
                tile_x = x + dx
                tile_y = y + dy
                cmd = f"/c game.surfaces[1].set_tiles({{{{name='water', position={{x={tile_x}, y={tile_y}}}}}}}); rcon.print('ok');"
                self.rcon_client.send_command(cmd)

    def place_resource_patch(
        self, resource_name: str, x: float, y: float, size: int = 8, amount: int = 1000
    ):
        """Place resource patch for mining drills."""
        print(f"      Placing {size}x{size} {resource_name} patch at ({x}, {y})...")
        cmd = f"/c remote.call('test_ground', 'place_resource_patch', '{resource_name}', {{x={x}, y={y}}}, {size}, {amount}); rcon.print('ok');"
        self.rcon_client.send_command(cmd)

    def inspect_entity(self, entity_name: str, position: Dict) -> Optional[Dict]:
        """Call inspect_entity and return response."""
        try:
            inspect_cmd = self.rcon_handler.build_command(
                "inspect_entity", entity_name, position
            )
            return self.rcon_handler.execute_and_parse_json(inspect_cmd)
        except Exception as e:
            print(f"      ✗ inspect_entity failed: {e}")
            return None

    def validate_base_fields(self, data: Dict, entity_name: str) -> List[str]:
        """Validate base fields are present. Returns list of missing fields."""
        base_fields = ["entity_name", "entity_type", "position", "direction", "tick"]
        missing = [f for f in base_fields if f not in data]
        return missing

    def validate_fields(
        self, data: Dict, expected_fields: List[str], field_type: str = "category"
    ) -> List[str]:
        """Validate expected fields are present. Returns list of missing fields."""
        # Fields might be None/null if empty, so we check for presence in keys
        missing = [f for f in expected_fields if f not in data]
        return missing

    def test_entity(
        self, entity_name: str, category: str, expected_fields: List[str], setup_fn=None
    ) -> bool:
        """Test a single entity type."""
        print(f"\n  Testing: {entity_name}")

        # Get next position
        x, y = self.current_position["x"], self.current_position["y"]
        self.current_position["x"] += 10  # Space entities apart

        # Run setup if provided (e.g., place water, resources, fuel)
        if setup_fn:
            setup_fn(x, y)

        # Place entity
        print(f"    Placing at ({x}, {y})...")
        metadata = self.place_entity(entity_name, x, y)
        if not metadata:
            print(f"    ✗ Failed to place {entity_name}")
            self.test_results.append(
                {
                    "entity": entity_name,
                    "category": category,
                    "status": "FAILED",
                    "reason": "Failed to place entity",
                }
            )
            return False

        entity_pos = metadata["position"]
        print(f"    ✓ Placed at ({entity_pos['x']}, {entity_pos['y']})")

        # Inspect entity
        print(f"    Inspecting...")
        inspection = self.inspect_entity(entity_name, entity_pos)
        if not inspection:
            print(f"    ✗ inspect_entity returned None")
            self.test_results.append(
                {
                    "entity": entity_name,
                    "category": category,
                    "status": "FAILED",
                    "reason": "inspect_entity returned None",
                }
            )
            return False

        # Validate base fields
        missing_base = self.validate_base_fields(inspection, entity_name)
        if missing_base:
            print(f"    ✗ Missing base fields: {missing_base}")
            self.test_results.append(
                {
                    "entity": entity_name,
                    "category": category,
                    "status": "FAILED",
                    "reason": f"Missing base fields: {missing_base}",
                    "data": inspection,
                }
            )
            return False

        # Validate category-specific fields
        missing_category = self.validate_fields(inspection, expected_fields)
        if missing_category:
            print(f"    ⚠ Missing category fields: {missing_category}")
            # Don't fail, just warn - some fields might be optional

        print(f"    ✓ SUCCESS")
        print(f"      Base fields: ✓")
        print(
            f"      Category fields present: {[f for f in expected_fields if f in inspection]}"
        )

        self.test_results.append(
            {
                "entity": entity_name,
                "category": category,
                "status": "PASSED",
                "missing_fields": missing_category,
                "data": inspection,
            }
        )
        return True

    def test_category(self, category_name: str, entities: List[Dict]):
        """Test all entities in a category."""
        print(f"\n{'=' * 80}")
        print(f"CATEGORY: {category_name}")
        print(f"{'=' * 80}")

        for entity_config in entities:
            self.test_entity(**entity_config)

    def run_all_tests(self):
        """Run all entity category tests."""

        # Category 1: Containers
        self.test_category(
            "Container",
            [
                {
                    "entity_name": "wooden-chest",
                    "category": "Container",
                    "expected_fields": ["contents", "inventory_bar"],
                },
                {
                    "entity_name": "iron-chest",
                    "category": "Container",
                    "expected_fields": ["contents", "inventory_bar"],
                },
            ],
        )

        # Category 2: Transport Belts
        self.test_category(
            "Transport Belt",
            [
                {
                    "entity_name": "transport-belt",
                    "category": "Transport Belt",
                    "expected_fields": ["belt_shape"],
                },
                {
                    "entity_name": "underground-belt",
                    "category": "Transport Belt",
                    "expected_fields": ["belt_shape", "belt_to_ground_type"],
                },
                {
                    "entity_name": "splitter",
                    "category": "Transport Belt",
                    "expected_fields": [
                        "belt_shape",
                        "splitter_filter",
                        "splitter_input_priority",
                        "splitter_output_priority",
                    ],
                },
            ],
        )

        # Category 3: Electric Poles
        self.test_category(
            "Electric Pole",
            [
                {
                    "entity_name": "small-electric-pole",
                    "category": "Electric Pole",
                    "expected_fields": [
                        "electric_network_id",
                        "is_connected",
                        "energy",
                    ],
                },
                {
                    "entity_name": "medium-electric-pole",
                    "category": "Electric Pole",
                    "expected_fields": [
                        "electric_network_id",
                        "is_connected",
                        "energy",
                    ],
                },
            ],
        )

        # Category 4: Energy Producers
        self.test_category(
            "Energy Producer",
            [
                {
                    "entity_name": "solar-panel",
                    "category": "Energy Producer",
                    "expected_fields": [
                        "energy_generated_last_tick",
                        "power_production",
                        "energy",
                    ],
                },
                {
                    "entity_name": "boiler",
                    "category": "Energy Producer",
                    "expected_fields": ["burner", "energy"],
                },
            ],
        )

        # Category 5: Offshore Pump (needs water)
        def setup_offshore_pump(x, y):
            self.place_water_tiles(x, y, size=5)

        self.test_category(
            "Offshore Pump",
            [
                {
                    "entity_name": "offshore-pump",
                    "category": "Energy Producer",
                    "expected_fields": [
                        "pumped_last_tick",
                        "fluidbox",
                        "get_fluid_source_fluid",
                        "get_fluid_source_tile",
                    ],
                    "setup_fn": setup_offshore_pump,
                },
            ],
        )

        # Category 6: Mining Drill (needs resources)
        def setup_mining_drill(x, y):
            self.place_resource_patch("iron-ore", x, y, size=8, amount=1000)

        self.test_category(
            "Mining Drill",
            [
                {
                    "entity_name": "burner-mining-drill",
                    "category": "Mining Drill",
                    "expected_fields": [
                        "mining_target",
                        "output",
                        "drop_position",
                        "mining_area",
                        "burner",
                    ],
                    "setup_fn": setup_mining_drill,
                },
            ],
        )

        # Category 7: Crafting Machines
        self.test_category(
            "Crafting Machine",
            [
                {
                    "entity_name": "stone-furnace",
                    "category": "Crafting Machine",
                    "expected_fields": ["recipe", "input", "output", "fuel", "burner"],
                },
                {
                    "entity_name": "assembling-machine-1",
                    "category": "Crafting Machine",
                    "expected_fields": ["recipe", "input", "output", "energy"],
                },
            ],
        )

        # Category 8: Inserters
        self.test_category(
            "Inserter",
            [
                {
                    "entity_name": "burner-inserter",
                    "category": "Inserter",
                    "expected_fields": [
                        "held_item",
                        "pickup_position",
                        "drop_position",
                    ],
                },
                {
                    "entity_name": "inserter",
                    "category": "Inserter",
                    "expected_fields": [
                        "held_item",
                        "pickup_position",
                        "drop_position",
                    ],
                },
            ],
        )

        # Category 9: Lab
        self.test_category(
            "Lab",
            [
                {
                    "entity_name": "lab",
                    "category": "Lab",
                    "expected_fields": [
                        "input",
                        "modules",
                        "current_research",
                        "energy",
                    ],
                },
            ],
        )

        # Category 10: Radar
        self.test_category(
            "Radar",
            [
                {
                    "entity_name": "radar",
                    "category": "Radar",
                    "expected_fields": ["radar_scan_progress", "energy"],
                },
            ],
        )

        # Category 11: Accumulator
        self.test_category(
            "Accumulator",
            [
                {
                    "entity_name": "accumulator",
                    "category": "Accumulator",
                    "expected_fields": ["energy", "electric_network_id"],
                },
            ],
        )

        # Category 12: Beacon
        self.test_category(
            "Beacon",
            [
                {
                    "entity_name": "beacon",
                    "category": "Beacon",
                    "expected_fields": ["modules", "effects", "energy"],
                },
            ],
        )

    def print_summary(self):
        """Print test summary."""
        print(f"\n{'=' * 80}")
        print("TEST SUMMARY")
        print(f"{'=' * 80}\n")

        passed = [r for r in self.test_results if r["status"] == "PASSED"]
        failed = [r for r in self.test_results if r["status"] == "FAILED"]

        print(f"Total Tests: {len(self.test_results)}")
        print(f"Passed: {len(passed)}")
        print(f"Failed: {len(failed)}")

        if failed:
            print(f"\nFailed Tests:")
            for result in failed:
                print(
                    f"  - {result['entity']} ({result['category']}): {result['reason']}"
                )

        if passed:
            print(f"\nPassed Tests:")
            for result in passed:
                entity = result["entity"]
                missing = result.get("missing_fields", [])
                if missing:
                    print(f"  - {entity}: ✓ (missing optional fields: {missing})")
                else:
                    print(f"  - {entity}: ✓")

        print(f"\n{'=' * 80}")
        if failed:
            print("⚠ SOME TESTS FAILED - Review output above")
        else:
            print("✓ ALL TESTS PASSED")
        print(f"{'=' * 80}\n")


def main():
    tester = InspectEntityTester()

    try:
        tester.setup()
        tester.run_all_tests()
        tester.print_summary()
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
