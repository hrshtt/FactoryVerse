"""
Runtime Entity Inspector for Factorio 2.0
=========================================
Inspects ALL placeable entities at runtime to understand their state,
inventories, and capabilities. Output is per-entity (not per-type).

Key features:
1. Inspects EVERY placeable entity (not just one per type)
2. Uses find_non_colliding_position for smart placement
3. Handles special entities: miners need ore, pumpjacks need oil, offshore pumps need water
4. Powers each entity individually with substation + electric-energy-interface
5. Immediate cleanup after inspection (no persistent test area)
"""

from factorio_rcon import RCONClient
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

# Connect to RCON
rcon_client = RCONClient("localhost", 27100, "factorio")


def send_lua(script: str, verbose: bool = True) -> Optional[Any]:
    """Send a Lua script with xpcall error handling."""
    wrapped = f"""
local success, result = xpcall(function()
{script}
end, debug.traceback)

if success then
    if result ~= nil then
        rcon.print(helpers.table_to_json({{success = true, result = result}}))
    else
        rcon.print(helpers.table_to_json({{success = true, result = "ok"}}))
    end
else
    rcon.print(helpers.table_to_json({{success = false, error = result}}))
end
"""
    result = rcon_client.send_command(f"/c {wrapped}")

    if not result:
        if verbose:
            print("  ⚠️  No response from RCON")
        return None

    try:
        data = json.loads(result)
        if data.get("success"):
            return data.get("result")
        else:
            error = data.get("error", "Unknown error")
            if verbose:
                print(f"  ❌ Lua error:\n{error}")
            return None
    except json.JSONDecodeError:
        if verbose:
            print(f"  ⚠️  Non-JSON response: {result[:200]}")
        return result


# ============================================================================
# GET ALL PLACEABLE ENTITY NAMES
# ============================================================================

GET_ENTITY_LIST_SCRIPT = """
local entities = {}

for name, proto in pairs(prototypes.entity) do
    if proto.items_to_place_this then
        table.insert(entities, {
            name = name,
            type = proto.type,
            supports_direction = proto.supports_direction,
        })
    end
end

-- Sort by type then name for deterministic order
table.sort(entities, function(a, b)
    if a.type == b.type then
        return a.name < b.name
    end
    return a.type < b.type
end)

return {
    count = #entities,
    entities = entities
}
"""

# ============================================================================
# GET DEFINES MAPPINGS
# ============================================================================

GET_DEFINES_SCRIPT = """
local inv_mapping = {}
for name, id in pairs(defines.inventory) do
    inv_mapping[id] = name
end

local status_mapping = {}
for name, id in pairs(defines.entity_status) do
    status_mapping[id] = name
end

local direction_mapping = {}
for name, id in pairs(defines.direction) do
    direction_mapping[id] = name
end

return {
    inventory = inv_mapping,
    entity_status = status_mapping,
    direction = direction_mapping
}
"""

# ============================================================================
# INSPECT A BATCH OF ENTITIES (by name list)
# ============================================================================


def create_batch_inspect_script(entity_names: List[str]) -> str:
    """
    Generate script to inspect a specific list of entities.
    Each entity is placed, powered, inspected, and immediately cleaned up.
    """
    # Convert entity names to Lua table
    names_lua = "{" + ",".join(f'"{n}"' for n in entity_names) + "}"

    return f"""
-- Status/direction mappings
local status_map = {{}}
for name, id in pairs(defines.entity_status) do
    status_map[id] = name
end

local dir_map = {{}}
for name, id in pairs(defines.direction) do
    dir_map[id] = name
end

-- Helper: Safe inventory inspection
local function inspect_inventory(inv, inv_name)
    if not inv or not inv.valid then return nil end
    
    local contents = {{}}
    for i = 1, #inv do
        local stack = inv[i]
        if stack and stack.valid and stack.valid_for_read then
            table.insert(contents, {{
                slot = i,
                name = stack.name,
                count = stack.count,
                quality = stack.quality and stack.quality.name or nil
            }})
        end
    end
    
    return {{
        name = inv_name,
        size = #inv,
        is_empty = inv.is_empty(),
        contents = contents
    }}
end

-- Helper: Safe property access
local function safe_get(entity, property)
    local ok, val = pcall(function() return entity[property] end)
    return ok and val or nil
end

-- Helper: Get inventories
local function get_inventories(entity)
    local invs = {{}}
    
    -- Standard helper methods
    local fuel = entity.get_fuel_inventory()
    if fuel then invs.fuel = inspect_inventory(fuel, "fuel") end
    
    local output = entity.get_output_inventory()
    if output then invs.output = inspect_inventory(output, "output") end
    
    local modules = entity.get_module_inventory()
    if modules then invs.modules = inspect_inventory(modules, "modules") end
    
    local burnt = entity.get_burnt_result_inventory()
    if burnt then invs.burnt_result = inspect_inventory(burnt, "burnt_result") end
    
    -- Entity-type specific inventories
    local etype = entity.type
    local type_invs = {{
        ["container"] = {{"chest"}},
        ["logistic-container"] = {{"chest", "logistic_container_trash"}},
        ["infinity-container"] = {{"chest"}},
        ["linked-container"] = {{"linked_container_main"}},
        ["furnace"] = {{"crafter_input", "crafter_output", "crafter_modules", "crafter_trash"}},
        ["assembling-machine"] = {{"crafter_input", "crafter_output", "crafter_modules", "crafter_trash"}},
        ["rocket-silo"] = {{"crafter_input", "crafter_output", "crafter_modules", "rocket_silo_rocket"}},
        ["lab"] = {{"lab_input", "lab_modules"}},
        ["mining-drill"] = {{"mining_drill_modules"}},
        ["car"] = {{"car_trunk", "car_ammo"}},
        ["spider-vehicle"] = {{"spider_trunk", "spider_ammo"}},
        ["cargo-wagon"] = {{"cargo_wagon"}},
        ["roboport"] = {{"roboport_robot", "roboport_material"}},
        ["logistic-robot"] = {{"robot_cargo"}},
        ["construction-robot"] = {{"robot_cargo", "robot_repair"}},
        ["beacon"] = {{"beacon_modules"}},
        ["ammo-turret"] = {{"turret_ammo"}},
        ["artillery-turret"] = {{"artillery_turret_ammo"}},
        ["cargo-landing-pad"] = {{"cargo_landing_pad_main"}},
        ["agricultural-tower"] = {{"agricultural_tower_input", "agricultural_tower_output"}},
    }}
    
    local inv_list = type_invs[etype]
    if inv_list then
        for _, inv_name in ipairs(inv_list) do
            local inv_enum = defines.inventory[inv_name]
            if inv_enum then
                local inv = entity.get_inventory(inv_enum)
                if inv and inv.valid then
                    invs[inv_name] = inspect_inventory(inv, inv_name)
                end
            end
        end
    end
    
    return (next(invs) and invs) or nil
end

-- Main inspector function
local function inspect_entity(entity)
    local proto = entity.prototype
    
    local state = {{
        name = entity.name,
        type = entity.type,
        valid = entity.valid,
        unit_number = entity.unit_number,
        position = {{x = entity.position.x, y = entity.position.y}},
        direction = dir_map[entity.direction] or entity.direction,
        status = entity.status and (status_map[entity.status] or entity.status) or nil,
        -- Prototype properties for mixin detection
        supports_direction = proto.supports_direction,
    }}
    
    -- Vector to place result (for mining drills and crafting machines)
    -- This defines where the entity outputs items to
    local ok_vec, vec = pcall(function() return proto.vector_to_place_result end)
    if ok_vec and vec then
        state.vector_to_place_result = {{x = vec.x, y = vec.y}}
    end
    
    -- Inventories
    local invs = get_inventories(entity)
    if invs then state.inventories = invs end
    
    -- Fluidboxes
    local fb = entity.fluidbox
    if fb and #fb > 0 then
        local fluids = {{}}
        for i = 1, #fb do
            local f = fb[i]
            if f then
                table.insert(fluids, {{
                    index = i,
                    name = f.name,
                    amount = f.amount,
                    temperature = f.temperature,
                    capacity = fb.get_capacity(i)
                }})
            else
                table.insert(fluids, {{index = i, empty = true, capacity = fb.get_capacity(i)}})
            end
        end
        state.fluidboxes = fluids
    end
    
    -- Burner
    if entity.burner then
        local b = entity.burner
        state.burner = {{
            heat = b.heat,
            heat_capacity = b.heat_capacity,
            remaining_fuel = b.remaining_burning_fuel,
            currently_burning = b.currently_burning and b.currently_burning.name or nil,
        }}
        if b.inventory and b.inventory.valid then
            state.burner.fuel_inventory = inspect_inventory(b.inventory, "burner_fuel")
        end
    end
    
    -- Electric energy
    local energy = safe_get(entity, "energy")
    if energy and energy > 0 then state.energy = energy end
    
    local buffer = safe_get(entity, "electric_buffer_size")
    if buffer and buffer > 0 then state.electric_buffer_size = buffer end
    
    -- Crafting
    local craft_prog = safe_get(entity, "crafting_progress")
    if craft_prog then state.crafting_progress = craft_prog end
    
    local craft_speed = safe_get(entity, "crafting_speed")
    if craft_speed then state.crafting_speed = craft_speed end
    
    local ok, recipe = pcall(function() return entity.get_recipe() end)
    if ok and recipe then state.current_recipe = recipe.name end
    
    -- Mining
    local mine_prog = safe_get(entity, "mining_progress")
    if mine_prog then state.mining_progress = mine_prog end
    
    local mine_target = safe_get(entity, "mining_target")
    if mine_target and mine_target.valid then state.mining_target = mine_target.name end
    
    -- Inserter-specific properties (only for type == "inserter")
    if entity.type == "inserter" then
        local pickup = safe_get(entity, "pickup_position")
        if pickup then state.pickup_position = {{x = pickup.x, y = pickup.y}} end
        
        local drop = safe_get(entity, "drop_position")
        if drop then state.drop_position = {{x = drop.x, y = drop.y}} end
        
        local held = safe_get(entity, "held_stack")
        if held and held.valid and held.valid_for_read then
            state.held_stack = {{name = held.name, count = held.count}}
        end
    end
    
    -- Output position for mining drills (where they drop items)
    if entity.type == "mining-drill" then
        local drop = safe_get(entity, "drop_position")
        if drop then state.output_position = {{x = drop.x, y = drop.y}} end
    end
    
    -- Rocket silo
    local rocket_parts = safe_get(entity, "rocket_parts")
    if rocket_parts then state.rocket_parts = rocket_parts end
    
    -- Logistic mode
    local log_mode = safe_get(entity, "logistic_mode")
    if log_mode then state.logistic_mode = log_mode end
    
    return state
end

-- Prime entity with items for testing
local function prime_entity(entity)
    if entity.burner then
        pcall(function() entity.insert({{name="coal", count=10}}) end)
    end
    
    if entity.fluidbox and #entity.fluidbox > 0 then
        pcall(function() entity.fluidbox[1] = {{name="water", amount=100}} end)
    end
    
    local etype = entity.type
    if etype == "furnace" then
        pcall(function() entity.insert({{name="iron-ore", count=10}}) end)
    elseif etype == "assembling-machine" then
        pcall(function()
            entity.set_recipe("iron-gear-wheel")
            entity.insert({{name="iron-plate", count=10}})
        end)
    elseif etype == "lab" then
        pcall(function() entity.insert({{name="automation-science-pack", count=10}}) end)
    elseif etype == "container" or etype == "logistic-container" then
        pcall(function()
            entity.insert({{name="iron-plate", count=50}})
            entity.insert({{name="copper-plate", count=25}})
        end)
    elseif etype == "ammo-turret" then
        pcall(function() entity.insert({{name="firearm-magazine", count=10}}) end)
    end
end

-- Create entity with environment (ore for miners, oil for pumpjacks, water for offshore pumps)
local function create_with_environment(surface, name, proto, base_pos)
    local etype = proto.type
    local created_entities = {{}}  -- Track all entities we create for cleanup
    
    -- Find a valid position
    local pos = surface.find_non_colliding_position(name, base_pos, 50, 1)
    if not pos then return nil, created_entities end
    
    -- Special handling for entities that need specific environments
    if etype == "mining-drill" then
        -- Spawn ore first
        local ore = surface.create_entity{{
            name = "iron-ore",
            position = pos,
            amount = 10000
        }}
        if ore then table.insert(created_entities, ore) end
        
    elseif name == "pumpjack" then
        -- Spawn crude oil
        local oil = surface.create_entity{{
            name = "crude-oil",
            position = pos,
            amount = 100000
        }}
        if oil then table.insert(created_entities, oil) end
        
    elseif etype == "offshore-pump" then
        -- Create water tile to the south
        local water_pos = {{x = pos.x, y = pos.y + 1}}
        surface.set_tiles({{{{name = "water", position = water_pos}}}})
        -- Offshore pump must face the water
        return surface.create_entity{{
            name = name,
            position = pos,
            force = game.forces.player,
            direction = defines.direction.south
        }}, created_entities
    end
    
    -- Create the main entity
    local ent = surface.create_entity{{
        name = name,
        position = pos,
        force = game.forces.player,
        direction = defines.direction.north
    }}
    
    return ent, created_entities
end

-- Provide power to an entity
local function power_entity(surface, pos)
    local power_entities = {{}}
    local power_pos = {{x = pos.x + 3, y = pos.y + 3}}
    
    -- Create Substation for area coverage
    local pole = surface.create_entity{{
        name = "substation",
        position = power_pos,
        force = game.forces.player
    }}
    if pole then table.insert(power_entities, pole) end
    
    -- Create infinite power interface
    local power = surface.create_entity{{
        name = "electric-energy-interface",
        position = power_pos,
        force = game.forces.player
    }}
    if power then
        power.power_production = 1000000000  -- 1 GW
        power.electric_buffer_size = 1000000000
        table.insert(power_entities, power)
    end
    
    return power_entities
end

-- Main execution
local surface = game.surfaces[1]
local entity_names = {names_lua}
local results = {{}}
local errors = {{}}
local search_center = {{x = 0, y = 0}}

for i, name in ipairs(entity_names) do
    local proto = prototypes.entity[name]
    if not proto then
        table.insert(errors, {{name = name, error = "Prototype not found"}})
    else
        -- Move search center to avoid collisions with previous entities
        search_center.x = search_center.x + 20
        if search_center.x > 500 then
            search_center.x = 0
            search_center.y = search_center.y + 20
        end
        
        local ent, env_entities = create_with_environment(surface, name, proto, search_center)
        
        if ent and ent.valid then
            -- Power the entity
            local power_entities = power_entity(surface, ent.position)
            
            -- Prime and inspect
            prime_entity(ent)
            local data = inspect_entity(ent)
            table.insert(results, data)
            
            -- Immediate cleanup
            ent.destroy()
            for _, e in pairs(env_entities) do
                if e and e.valid then e.destroy() end
            end
            for _, e in pairs(power_entities) do
                if e and e.valid then e.destroy() end
            end
        else
            table.insert(errors, {{name = name, error = "Failed to create entity"}})
        end
    end
end

return {{
    results = results,
    errors = errors,
    count = #results
}}
"""


def run_inspection():
    """Run the full inspection workflow."""

    output_dir = Path(__file__).parent.parent / ".fv-output" / "inspection"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("FACTORIO RUNTIME ENTITY INSPECTOR")
    print("=" * 70)

    # Step 1: Get defines
    print("\n📋 Step 1: Getting defines mappings...")
    defines_data = send_lua(GET_DEFINES_SCRIPT)
    if defines_data:
        with open(output_dir / "defines.json", "w") as f:
            json.dump(defines_data, f, indent=2)
        print(f"   ✅ Saved {len(defines_data.get('entity_status', {}))} statuses")

    # Step 2: Get list of all placeable entities
    print("\n📋 Step 2: Getting list of all placeable entities...")
    entity_list = send_lua(GET_ENTITY_LIST_SCRIPT)
    if not entity_list:
        print("   ❌ Failed to get entity list")
        return []

    all_entities = entity_list.get("entities", [])
    # Handle Lua array as dict with numeric keys
    if isinstance(all_entities, dict):
        all_entities = list(all_entities.values())

    print(f"   ✅ Found {len(all_entities)} placeable entities")

    # Save entity list
    with open(output_dir / "entity_list.json", "w") as f:
        json.dump(all_entities, f, indent=2)

    # Step 3: Inspect entities in batches
    print("\n📋 Step 3: Inspecting entities...")

    all_results = []
    all_errors = []
    batch_size = 15  # Smaller batches to avoid timeout

    entity_names = [e["name"] if isinstance(e, dict) else e for e in all_entities]
    total_batches = (len(entity_names) + batch_size - 1) // batch_size

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, len(entity_names))
        batch_names = entity_names[start:end]

        print(
            f"\n   Batch {batch_idx + 1}/{total_batches}: {batch_names[0]} ... {batch_names[-1]}"
        )

        script = create_batch_inspect_script(batch_names)
        result = send_lua(script, verbose=True)

        if result and isinstance(result, dict):
            batch_results = result.get("results", [])
            batch_errors = result.get("errors", [])

            # Handle Lua array as dict
            if isinstance(batch_results, dict):
                batch_results = list(batch_results.values())
            if isinstance(batch_errors, dict):
                batch_errors = list(batch_errors.values())

            all_results.extend(batch_results)
            all_errors.extend(batch_errors)

            print(
                f"      ✅ Inspected {len(batch_results)} entities, {len(batch_errors)} errors"
            )
        else:
            print(f"      ❌ Batch failed")

    # Step 4: Save results
    print("\n📋 Step 4: Saving results...")

    # Save as JSONL
    jsonl_path = output_dir / "runtime_inspection.jsonl"
    with open(jsonl_path, "w") as f:
        for entity_data in all_results:
            f.write(json.dumps(entity_data) + "\n")
    print(f"   ✅ Saved {len(all_results)} entities to {jsonl_path.name}")

    # Save as pretty JSON
    json_path = output_dir / "runtime_inspection.json"
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"   ✅ Saved pretty JSON to {json_path.name}")

    # Save errors
    if all_errors:
        errors_path = output_dir / "inspection_errors.json"
        with open(errors_path, "w") as f:
            json.dump(all_errors, f, indent=2)
        print(f"   ⚠️  Saved {len(all_errors)} errors to {errors_path.name}")

    # Step 5: Generate capability summary (per-entity)
    print("\n📋 Step 5: Generating capability summary...")

    capability_summary = []
    for entity in all_results:
        etype = entity.get("type")
        caps = {
            "name": entity.get("name"),
            "type": etype,
            "supports_direction": entity.get("supports_direction", False),
            "has_burner": "burner" in entity,
            "has_electric_buffer": "electric_buffer_size" in entity,
            "has_energy": "energy" in entity,
            "has_crafting": "crafting_progress" in entity or "crafting_speed" in entity,
            "has_mining": "mining_progress" in entity,
            "has_fluidbox": "fluidboxes" in entity,
            # INSERTER: Only for actual inserter type (has pickup + drop)
            "is_inserter": etype == "inserter" and "pickup_position" in entity,
            # OUTPUT_VECTOR: For drills/crafters that have an output position
            "has_output_vector": "vector_to_place_result" in entity
            or "output_position" in entity,
            "has_rocket_parts": "rocket_parts" in entity,
            "inventories": sorted(entity.get("inventories", {}).keys())
            if entity.get("inventories")
            else [],
        }

        # Derive mixins
        mixins = []
        if caps["supports_direction"]:
            mixins.append("ROTATABLE")
        if caps["has_burner"]:
            mixins.append("BURNER")
        if caps["has_electric_buffer"] or caps["has_energy"]:
            mixins.append("ELECTRIC")
        if caps["has_crafting"]:
            mixins.append("CRAFTER")
        if caps["has_mining"]:
            mixins.append("MINER")
        if caps["has_fluidbox"]:
            mixins.append("FLUID")
        if caps["is_inserter"]:
            mixins.append("INSERTER")
        if caps["has_output_vector"]:
            mixins.append("OUTPUT_VECTOR")
        if caps["has_rocket_parts"]:
            mixins.append("ROCKET")

        caps["mixins"] = mixins
        capability_summary.append(caps)

    # Sort by type then name
    capability_summary.sort(key=lambda x: (x["type"], x["name"]))

    summary_path = output_dir / "capability_summary.json"
    with open(summary_path, "w") as f:
        json.dump(capability_summary, f, indent=2)
    print(f"   ✅ Saved capability summary to {summary_path.name}")

    # Print summary
    print("\n" + "=" * 70)
    print(f"INSPECTION COMPLETE: {len(all_results)} entities inspected")
    print("=" * 70)

    # Group by type for summary
    type_counts: Dict[str, int] = {}
    for e in all_results:
        t = e.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    print("\nEntities per type:")
    for t in sorted(type_counts.keys()):
        print(f"  {t}: {type_counts[t]}")

    return all_results


if __name__ == "__main__":
    results = run_inspection()
