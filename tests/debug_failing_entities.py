#!/usr/bin/env python3
"""
Evidence Gathering Script for Failing Entity Types

Directly accesses entity properties via Lua to debug why certain entities
fail inspection. Does NOT rely on the inspection module.

Failing entities:
- transport-belt, underground-belt, splitter
- solar-panel, boiler
"""

import json
from factorio_rcon import RCONClient


class EntityPropertyDebugger:
    """Debugs entity properties by direct Lua access."""

    def __init__(self):
        self.rcon_client = None
        self.evidence = {}

    def setup(self):
        """Initialize RCON connection."""
        print("=" * 80)
        print("EVIDENCE GATHERING: Failing Entity Types")
        print("=" * 80)

        self.rcon_client = RCONClient("localhost", 27100, "factorio")
        self.rcon_client.send_command("/c rcon.print('hello')")
        self.rcon_client.send_command("/c rcon.print('hello')")
        print("\n[Setup] ✓ Connected to RCON\n")

    def place_and_find_entity(
        self, entity_name: str, x: float = 10, y: float = 10
    ) -> bool:
        """Place entity and verify it can be found."""
        print(f"\n{'=' * 80}")
        print(f"ENTITY: {entity_name}")
        print(f"{'=' * 80}")

        # Clear area
        clear_cmd = f"/c remote.call('test_ground', 'clear_area', {{left_top={{x={x - 3}, y={y - 3}}}, right_bottom={{x={x + 3}, y={y + 3}}}}}); rcon.print('ok');"
        self.rcon_client.send_command(clear_cmd)

        # Place entity
        place_cmd = f"/c local res = remote.call('test_ground', 'place_entity', '{entity_name}', {{x={x}, y={y}}}); rcon.print(helpers.table_to_json(res));"
        response = self.rcon_client.send_command(place_cmd)
        if not response:
            print(f"  ✗ Failed to place {entity_name}")
            return False

        data = json.loads(response)
        if not data.get("success"):
            print(f"  ✗ Failed to place: {data}")
            return False

        pos = data["metadata"]["position"]
        print(f"  ✓ Placed at ({pos['x']}, {pos['y']})")

        # Store position for later use
        self.evidence[entity_name] = {"position": pos}
        return True

    def gather_base_properties(self, entity_name: str):
        """Gather base entity properties."""
        print(f"\n[1] Base Properties")
        pos = self.evidence[entity_name]["position"]

        # Find entity and get base properties
        lua_code = f"""
        local e = game.surfaces[1].find_entity('{entity_name}', {{x={pos["x"]}, y={pos["y"]}}})
        if not e then
            rcon.print('ENTITY_NOT_FOUND')
        else
            local result = {{}}
            result.valid = e.valid
            result.name = e.name
            result.type = e.type
            result.position = {{x = e.position.x, y = e.position.y}}
            result.direction = e.direction
            result.health = e.health
            result.max_health = e.max_health
            rcon.print(helpers.table_to_json(result))
        end
        """

        response = self.rcon_client.send_command(f"/c {lua_code}")
        if response == "ENTITY_NOT_FOUND":
            print("  ✗ Entity not found!")
            return

        data = json.loads(response)
        print(f"  valid: {data.get('valid')}")
        print(f"  name: {data.get('name')}")
        print(f"  type: '{data.get('type')}'")
        print(
            f"  position: ({data.get('position', {}).get('x')}, {data.get('position', {}).get('y')})"
        )
        print(f"  direction: {data.get('direction')}")
        print(f"  health: {data.get('health')}/{data.get('max_health')}")

        self.evidence[entity_name]["base"] = data

    def gather_transport_belt_properties(self, entity_name: str):
        """Gather transport belt specific properties."""
        print(f"\n[2] Transport Belt Properties")
        pos = self.evidence[entity_name]["position"]

        lua_code = f"""
        local e = game.surfaces[1].find_entity('{entity_name}', {{x={pos["x"]}, y={pos["y"]}}})
        if not e then
            rcon.print('NOT_FOUND')
        else
            local result = {{}}
            
            -- Check property existence
            result.has_belt_shape = (e.belt_shape ~= nil)
            result.belt_shape = e.belt_shape
            
            result.has_belt_neighbours = (e.belt_neighbours ~= nil)
            if e.belt_neighbours then
                result.belt_neighbours_type = type(e.belt_neighbours)
            end
            
            result.has_linked_belt_neighbour = (e.linked_belt_neighbour ~= nil)
            result.has_linked_belt_type = (e.linked_belt_type ~= nil)
            
            result.has_belt_to_ground_type = (e.belt_to_ground_type ~= nil)
            result.belt_to_ground_type = e.belt_to_ground_type
            
            result.has_splitter_filter = (e.splitter_filter ~= nil)
            result.has_splitter_input_priority = (e.splitter_input_priority ~= nil)
            result.has_splitter_output_priority = (e.splitter_output_priority ~= nil)
            
            result.has_get_max_transport_line_index = (e.get_max_transport_line_index ~= nil)
            
            rcon.print(helpers.table_to_json(result))
        end
        """

        response = self.rcon_client.send_command(f"/c {lua_code}")
        if not response or response == "NOT_FOUND":
            print("  ✗ Entity not found or Lua error!")
            print(f"  Response: '{response}'")
            return

        data = json.loads(response)
        print(
            f"  belt_shape: {data.get('belt_shape')} (exists: {data.get('has_belt_shape')})"
        )
        print(
            f"  belt_neighbours: exists={data.get('has_belt_neighbours')}, type={data.get('belt_neighbours_type')}"
        )
        print(
            f"  linked_belt_neighbour: exists={data.get('has_linked_belt_neighbour')}"
        )
        print(
            f"  belt_to_ground_type: {data.get('belt_to_ground_type')} (exists: {data.get('has_belt_to_ground_type')})"
        )
        print(f"  splitter_filter: exists={data.get('has_splitter_filter')}")
        print(
            f"  get_max_transport_line_index: exists={data.get('has_get_max_transport_line_index')}"
        )

        self.evidence[entity_name]["transport_belt"] = data

    def gather_energy_producer_properties(self, entity_name: str):
        """Gather energy producer specific properties."""
        print(f"\n[2] Energy Producer Properties")
        pos = self.evidence[entity_name]["position"]

        lua_code = f"""
        local e = game.surfaces[1].find_entity('{entity_name}', {{x={pos["x"]}, y={pos["y"]}}})
        if not e then
            rcon.print('NOT_FOUND')
        else
            local result = {{}}
            
            -- Check property existence
            result.has_energy_generated_last_tick = (e.energy_generated_last_tick ~= nil)
            result.energy_generated_last_tick = e.energy_generated_last_tick
            
            result.has_power_production = (e.power_production ~= nil)
            result.power_production = e.power_production
            
            result.has_burner = (e.burner ~= nil)
            if e.burner then
                result.burner_valid = e.burner.valid
            end
            
            result.has_temperature = (e.temperature ~= nil)
            result.temperature = e.temperature
            
            result.has_heat_neighbours = (e.heat_neighbours ~= nil)
            result.has_neighbour_bonus = (e.neighbour_bonus ~= nil)
            
            result.has_energy = (e.energy ~= nil)
            result.energy = e.energy
            
            result.has_electric_buffer_size = (e.electric_buffer_size ~= nil)
            result.electric_buffer_size = e.electric_buffer_size
            
            rcon.print(helpers.table_to_json(result))
        end
        """

        response = self.rcon_client.send_command(f"/c {lua_code}")
        if response == "NOT_FOUND":
            print("  ✗ Entity not found!")
            return

        data = json.loads(response)
        print(
            f"  energy_generated_last_tick: {data.get('energy_generated_last_tick')} (exists: {data.get('has_energy_generated_last_tick')})"
        )
        print(
            f"  power_production: {data.get('power_production')} (exists: {data.get('has_power_production')})"
        )
        print(
            f"  burner: exists={data.get('has_burner')}, valid={data.get('burner_valid')}"
        )
        print(
            f"  temperature: {data.get('temperature')} (exists: {data.get('has_temperature')})"
        )
        print(f"  energy: {data.get('energy')} (exists: {data.get('has_energy')})")
        print(
            f"  electric_buffer_size: {data.get('electric_buffer_size')} (exists: {data.get('has_electric_buffer_size')})"
        )

        self.evidence[entity_name]["energy_producer"] = data

    def test_category_inspector_logic(self, entity_name: str, category: str):
        """Test the category inspector logic inline."""
        print(f"\n[3] Testing Category Inspector Logic ({category})")
        pos = self.evidence[entity_name]["position"]
        px = pos["x"]
        py = pos["y"]

        if category == "transport_belt":
            lua_code = (
                """
            local e = game.surfaces[1].find_entity('"""
                + entity_name
                + """', {x="""
                + str(px)
                + """, y="""
                + str(py)
                + """})
            if not e then
                rcon.print('NOT_FOUND')
            else
                -- Replicate inspect_transport_belt logic
                local data = {}
                
                if e.belt_shape then
                    data.belt_shape = e.belt_shape
                end
                
                if e.belt_neighbours then
                    local neighbours = {}
                    for _, neighbour in pairs(e.belt_neighbours) do
                        if neighbour and neighbour.valid then
                            table.insert(neighbours, {name = neighbour.name, position = {x = neighbour.position.x, y = neighbour.position.y}})
                        end
                    end
                    if next(neighbours) ~= nil then
                        data.belt_neighbours = neighbours
                    end
                end
                
                if e.belt_to_ground_type then
                    data.belt_to_ground_type = e.belt_to_ground_type
                end
                
                if e.splitter_filter then
                    data.splitter_filter = e.splitter_filter
                end
                
                local result = {
                    data_empty = (next(data) == nil),
                    data_keys = {},
                    data = data
                }
                
                for k, _ in pairs(data) do
                    table.insert(result.data_keys, k)
                end
                
                rcon.print(helpers.table_to_json(result))
            end
            """
            )
        elif category == "energy_producer":
            lua_code = (
                """
            local e = game.surfaces[1].find_entity('"""
                + entity_name
                + """', {x="""
                + str(px)
                + """, y="""
                + str(py)
                + """})
            if not e then
                rcon.print('NOT_FOUND')
            else
                -- Replicate inspect_energy_producer logic
                local data = {}
                
                if e.energy_generated_last_tick then
                    data.energy_generated_last_tick = e.energy_generated_last_tick
                end
                
                if e.power_production then
                    data.power_production = e.power_production
                end
                
                if e.burner and e.burner.valid then
                    data.burner = {valid = true}
                end
                
                if e.temperature then
                    data.temperature = e.temperature
                end
                
                if e.energy then
                    data.energy = {
                        current = e.energy,
                        capacity = e.electric_buffer_size or 0
                    }
                end
                
                local result = {
                    data_empty = (next(data) == nil),
                    data_keys = {},
                    data = data
                }
                
                for k, _ in pairs(data) do
                    table.insert(result.data_keys, k)
                end
                
                rcon.print(helpers.table_to_json(result))
            end
            """
            )
        else:
            print(f"  Unknown category: {category}")
            return

        response = self.rcon_client.send_command(f"/c {lua_code}")
        if response == "NOT_FOUND":
            print("  ✗ Entity not found!")
            return

        data = json.loads(response)
        print(f"  data_empty: {data.get('data_empty')}")
        print(f"  data_keys: {data.get('data_keys')}")
        print(f"  data: {json.dumps(data.get('data'), indent=4)}")

        self.evidence[entity_name]["inspector_test"] = data

    def debug_entity(self, entity_name: str, category: str):
        """Full debug workflow for one entity."""
        if not self.place_and_find_entity(entity_name):
            return

        self.gather_base_properties(entity_name)

        if category == "transport_belt":
            self.gather_transport_belt_properties(entity_name)
        elif category == "energy_producer":
            self.gather_energy_producer_properties(entity_name)

        self.test_category_inspector_logic(entity_name, category)

    def print_summary(self):
        """Print summary of findings."""
        print(f"\n{'=' * 80}")
        print("SUMMARY OF FINDINGS")
        print(f"{'=' * 80}\n")

        for entity_name, data in self.evidence.items():
            print(f"\n{entity_name}:")

            if "base" in data:
                print(f"  Entity type: '{data['base'].get('type')}'")
                print(f"  Valid: {data['base'].get('valid')}")

            if "inspector_test" in data:
                is_empty = data["inspector_test"].get("data_empty")
                keys = data["inspector_test"].get("data_keys", [])
                print(f"  Inspector returns empty: {is_empty}")
                if not is_empty:
                    print(f"  Inspector data keys: {keys}")
                else:
                    print(f"  ⚠ Inspector returns empty data - this causes None!")


def main():
    debugger = EntityPropertyDebugger()
    debugger.setup()

    # Debug transport belt entities
    print("\nTRANSPORT BELT CATEGORY")
    print("=" * 80)
    debugger.debug_entity("transport-belt", "transport_belt")
    debugger.debug_entity("underground-belt", "transport_belt")
    debugger.debug_entity("splitter", "transport_belt")

    # Debug energy producer entities
    print("\n\nENERGY PRODUCER CATEGORY")
    print("=" * 80)
    debugger.debug_entity("solar-panel", "energy_producer")
    debugger.debug_entity("boiler", "energy_producer")

    # Print summary
    debugger.print_summary()


if __name__ == "__main__":
    main()
