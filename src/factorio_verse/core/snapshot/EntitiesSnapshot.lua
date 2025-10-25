local GameState = require "core.game_state.GameState"
local utils = require "utils"

--- Component Schema Definition for EntitiesSnapshot
local ComponentSchema = {
    -- Base entity component
    entity = {
        fields = {
            unit_number = "number",
            -- permanent fields
            name = "string",
            type = "string",
            force = "string",
            -- rarely changing fields
            direction = "number",
            direction_name = "string",
            orientation = "number",
            orientation_name = "string",
            electric_network_id = "number",
            recipe = "string",
            -- spatial fields
            position_x = "number",
            position_y = "number",
            tile_width = "number",
            tile_height = "number",
            bounding_box_min_x = "number",
            bounding_box_min_y = "number",
            bounding_box_max_x = "number",
            bounding_box_max_y = "number",
            chunk_x = "number",
            chunk_y = "number",
        },
        flatten_rules = {
            position = { x = "position_x", y = "position_y" },
            chunk = { x = "chunk_x", y = "chunk_y" },
            bounding_box = {
                bbox_min_x = "bounding_box_min_x",
                bbox_min_y = "bounding_box_min_y",
                bbox_max_x = "bounding_box_max_x",
                bbox_max_y = "bounding_box_max_y"
            }
        }
    },

    -- Inserter component
    inserter = {
        fields = {
            unit_number = "number",
            pickup_target_unit = "number",
            drop_target_unit = "number",
            pickup_position_x = "number",
            pickup_position_y = "number",
            drop_position_x = "number",
            drop_position_y = "number",
            chunk_x = "number",
            chunk_y = "number",
        },
        flatten_rules = {
            chunk = { x = "chunk_x", y = "chunk_y" },
            pickup_position = { x = "pickup_position_x", y = "pickup_position_y" },
            drop_position = { x = "drop_position_x", y = "drop_position_y" }
        }
    },

    -- Belt component
    belt = {
        fields = {
            unit_number = "number",
            name = "string",
            type = "string",
            direction = "number",
            direction_name = "string",
            belt_neighbours_json = "json", -- Complex nested data
            belt_to_ground_type = "string",
            underground_neighbour_unit = "number",
            -- spatial fields
            position_x = "number",
            position_y = "number",
            chunk_x = "number",
            chunk_y = "number"
        },
        flatten_rules = {
            position = { x = "position_x", y = "position_y" },
            chunk = { x = "chunk_x", y = "chunk_y" },
            belt_neighbours = "belt_neighbours_json" -- Map to _json suffixed field
        }
    },

    -- Pipe component
    pipe = {
        fields = {
            unit_number = "number",
            name = "string",
            type = "string",
            direction = "number",
            direction_name = "string",
            pipe_neighbours_json = "json", -- Input/output connections like belts
            position_x = "number",
            position_y = "number",
            chunk_x = "number",
            chunk_y = "number",
        },
        flatten_rules = {
            position = { x = "pos_x", y = "pos_y" },
            chunk = { x = "chunk_x", y = "chunk_y" },
            pipe_neighbours = "pipe_neighbours_json" -- Map to _json suffixed field
        }
    },

    -- Entity status for recurring snapshots
    entity_status = {
        fields = {
            unit_number = "number",
            status = "number",
            status_name = "string",
            health = "number",
            tick = "number"
        },
        flatten_rules = {}
    }
}

--- EntitiesSnapshot: View module for entity data
--- @class EntitiesSnapshot
local EntitiesSnapshot = {}

--- Determine component type for an entity
--- @param entity_type string - entity type from Factorio API
--- @param entity_name string - entity prototype name
--- @return string - component type ("belts", "pipes", "poles", "entities")
function EntitiesSnapshot._determine_component_type(entity_type, entity_name)
    -- Belt types
    if entity_type == "transport-belt" or entity_type == "underground-belt" or 
       entity_type == "splitter" or entity_type == "loader" or 
       entity_type == "loader-1x1" or entity_type == "linked-belt" then
        return "belts"
    end
    
    -- Pipe types
    if entity_type == "pipe" or entity_type == "pipe-to-ground" then
        return "pipes"
    end
    
    -- Electric pole types
    if entity_type == "electric-pole" or entity_type == "power-switch" or 
       entity_type == "substation" then
        return "poles"
    end
    
    -- Default to entities for all other player-placed entities
    return "entities"
end

--- Dump all entities chunk-wise as individual JSON files
--- ⚠️ WARNING: Entities whose bounding box intersects chunk boundaries will be written to MULTIPLE chunk directories.
--- This is expected behavior due to Factorio's find_entities_filtered API - downstream systems must deduplicate by unit_number.
-- ============================================================================
-- VIEW METHODS (called by Snapshot orchestrator)
-- ============================================================================

--- Gather all entities for a specific chunk
--- @param chunk table - {x, y, area}
--- @param options table - {component_filter = nil|"entities"|"belts"|"pipes"|"poles"}
--- @return table - {entities = {...}, belts = {...}, pipes = {...}, poles = {...}}
function EntitiesSnapshot.gather_entities_for_chunk(chunk, options)
    local gs = GameState:new()
    local surface = gs:get_surface()
    if not surface then return { entities = {}, belts = {}, pipes = {}, poles = {} } end

    local force = gs:get_player_force()
    if not force then return { entities = {}, belts = {}, pipes = {}, poles = {} } end

    local filter = { area = chunk.area, force = force, type = EntitiesSnapshot.get_allowed_entity_types() }
    local entities_raw = surface.find_entities_filtered(filter)

    local categorized = { entities = {}, belts = {}, pipes = {}, poles = {} }

    for _, entity in ipairs(entities_raw) do
        if entity and entity.valid then
            -- Filter rocks
            if entity.type == "simple-entity" and (entity.name == "rock-huge" or entity.name == "rock-big" or entity.name == "sand-rock-big") then
                goto continue
            end

            local component_type = EntitiesSnapshot.determine_component_type(entity.type, entity.name)

            -- Apply component filter if specified
            if not options.component_filter or options.component_filter == component_type then
                local serialized = EntitiesSnapshot.serialize_entity(entity, options)
                if serialized then
                    table.insert(categorized[component_type], serialized)
                end
            end
        end
        ::continue::
    end

    return categorized
end

--- Get status view for entities in a chunk
--- Status records now use position instead of unit_number
--- @param chunk table - {x, y, area}
--- @return table - array of {position_x, position_y, entity_name, status, status_name, health, tick}
function EntitiesSnapshot.get_status_view_for_chunk(chunk)
    local gs = GameState:new()
    local surface = gs:get_surface()
    if not surface then return {} end

    local force = gs:get_player_force()
    if not force then return {} end

    local allowed_types = EntitiesSnapshot.get_allowed_entity_types()
    local filter = { area = chunk.area, force = force, type = allowed_types }
    local entities = surface.find_entities_filtered(filter)
    
    local status_records = {}
    for _, entity in ipairs(entities) do
        if entity and entity.valid then
            -- Filter rocks
            if entity.type == "simple-entity" then
                local n = entity.name
                if n == "rock-huge" or n == "rock-big" or n == "sand-rock-big" then
                    goto continue
                end
            end

            table.insert(status_records, {
                position_x = entity.position.x,
                position_y = entity.position.y,
                entity_name = entity.name,
                status = entity.status or 0,
                status_name = utils.status_to_name(entity.status),
                health = entity.health or 0,
                tick = game.tick or 0
            })
        end
        ::continue::
    end

    return status_records
end

--- Get inventory view for a specific entity
--- @param position table - {x, y} entity position
--- @param entity_name string - entity prototype name
--- @return table - {position_x, position_y, entity_name, tick, inventories} or {error, position_x, position_y, entity_name, tick}
function EntitiesSnapshot.get_inventory_view(position, entity_name)
    local entity = game.surfaces[1].find_entity(entity_name, position)
    if not entity or not entity.valid then
        return {
            error = "Entity not found",
            position_x = position.x,
            position_y = position.y,
            entity_name = entity_name,
            tick = game.tick or 0
        }
    end

    local inventories = EntitiesSnapshot._get_entity_inventories(entity)
    return {
        position_x = position.x,
        position_y = position.y,
        entity_name = entity_name,
        tick = game.tick or 0,
        inventories = inventories
    }
end

--- Get inventory views for multiple entities
--- @param positions table - array of {position, entity_name} objects
--- @return table - array of inventory data
function EntitiesSnapshot.get_inventory_views(positions)
    local results = {}
    for _, pos_info in ipairs(positions) do
        local pos = pos_info.position or pos_info
        local entity_name = pos_info.entity_name
        table.insert(results, EntitiesSnapshot.get_inventory_view(pos, entity_name))
    end
    return results
end

--- Get all inventories for a single entity (private helper)
--- @param entity LuaEntity - the entity to get inventories for
--- @return table - inventory contents by inventory type
function EntitiesSnapshot._get_entity_inventories(entity)
    local inventories = {}
    local inventory_types = {
        chest = defines.inventory.chest,
        fuel = defines.inventory.fuel,
        burnt_result = defines.inventory.burnt_result,
        input = defines.inventory.assembling_machine_input,
        output = defines.inventory.assembling_machine_output,
        modules = defines.inventory.assembling_machine_modules,
        ammo = defines.inventory.turret_ammo,
        trunk = defines.inventory.car_trunk,
        cargo = defines.inventory.cargo_wagon,
    }

    for inventory_name, inventory_type in pairs(inventory_types) do
        local success, inventory = pcall(function()
            return entity.get_inventory(inventory_type)
        end)

        if success and inventory and inventory.valid then
            local contents = inventory.get_contents()
            if contents and next(contents) ~= nil then
                inventories[inventory_name] = contents
            end
        end
    end

    return inventories
end

--- Serialize a single entity (public method for orchestrator)
--- @param entity LuaEntity - the entity to serialize
--- @param options table - optional serialization options
--- @return table|nil - serialized entity data or nil if invalid
function EntitiesSnapshot.serialize_entity(entity, options)
    return EntitiesSnapshot._serialize_entity(entity)
end

--- Determine component type for an entity (public method for orchestrator)
--- @param entity_type string - entity type
--- @param entity_name string - entity name
--- @return string - component type ("entities", "belts", "pipes", "poles")
function EntitiesSnapshot.determine_component_type(entity_type, entity_name)
    return EntitiesSnapshot._determine_component_type(entity_type, entity_name)
end

--- Get allowed entity types (public method for orchestrator)
--- @return table - array of allowed entity types
function EntitiesSnapshot.get_allowed_entity_types()
    return {
        "assembling-machine", "furnace", "mining-drill", "inserter", "lab", "roboport", "beacon",
        "electric-pole", "radar", "storage-tank", "offshore-pump", "chemical-plant", "oil-refinery",
        "boiler", "generator", "pump", "pumpjack", "rocket-silo", "container", "logistic-container",
        "arithmetic-combinator", "decider-combinator", "constant-combinator", "lamp", "reactor",
        "heat-pipe", "accumulator", "electric-energy-interface",
        "transport-belt", "underground-belt", "splitter", "loader", "loader-1x1", "linked-belt",
        "pipe", "pipe-to-ground", "power-switch", "substation"
    }
end

-- Internal helpers -----------------------------------------------------------

--- Serialize entity data for JSON storage
--- @param e LuaEntity
--- @return table|nil
function EntitiesSnapshot._serialize_entity(e)
    if not (e and e.valid) then return nil end

    local proto = e.prototype

    local out = {
        unit_number = e.unit_number,
        name = e.name,
        type = e.type,
        force = (e.force and e.force.name) or nil,
        position = e.position,
        direction = e.direction,
        direction_name = utils.direction_to_name(e.direction and tonumber(tostring(e.direction)) or nil),
        orientation = e.orientation,
        orientation_name = utils.orientation_to_name(e.orientation),
    }

    -- Electric network id
    if e.electric_network_id ~= nil then
        out.electric_network_id = e.electric_network_id
    end

    -- Tile dimensions from prototype
    if proto then
        if proto.tile_width ~= nil then out.tile_width = proto.tile_width end
        if proto.tile_height ~= nil then out.tile_height = proto.tile_height end
    end

    -- Crafting / recipe (gate to crafting machines only)
    do
        -- Treat only true crafting machines as crafters
        local is_crafter = (e.type == "assembling-machine" or e.type == "furnace")
        if not is_crafter and proto and proto.crafting_categories then
            is_crafter = true
        end

        if is_crafter then
            -- Per docs, LuaEntity::get_recipe() is the supported way to read the current recipe
            local r = e.get_recipe()
            if r then out.recipe = r.name end
        end
    end

    -- Selection & bounding boxes (runtime first; fall back to prototype)
    do
        local bb = e.bounding_box
        if bb and bb.left_top and bb.right_bottom then
            out.bounding_box = {
                min_x = bb.left_top.x,
                min_y = bb.left_top.y,
                max_x = bb.right_bottom.x,
                max_y = bb.right_bottom.y
            }
        end
    end

    -- Component-specific data for specialized entity types
    local component_type = EntitiesSnapshot._determine_component_type(e.type, e.name)
    
    if component_type == "belts" then
        -- Belt-specific data
        local item_lines = {}
        local max_index = 0
        do
            local name = e.name
            -- Note: cache removed for static method - could be added back if needed
                local v = (e.get_max_transport_line_index and e.get_max_transport_line_index()) or 0
                max_index = (type(v) == "number" and v > 0) and v or 0
        end

        for li = 1, max_index do
            local tl = e.get_transport_line and e.get_transport_line(li) or nil
            if tl then
                local contents = tl.get_contents and tl.get_contents() or nil
                if contents and next(contents) ~= nil then
                    item_lines[#item_lines + 1] = { index = li, items = contents }
                end
            end
        end

        -- Belt neighbours (inputs/outputs) and underground pairing
        local inputs_ids, outputs_ids = {}, {}
        local bn = e.belt_neighbours
        if bn then
            if bn.inputs then
                for _, n in ipairs(bn.inputs) do
                    if n and n.valid and n.unit_number then inputs_ids[#inputs_ids + 1] = n.unit_number end
                end
            end
            if bn.outputs then
                for _, n in ipairs(bn.outputs) do
                    if n and n.valid and n.unit_number then outputs_ids[#outputs_ids + 1] = n.unit_number end
                end
            end
        end
        
        local underground_other = nil
        local belt_to_ground_type = nil
        if e.type == "underground-belt" then
            belt_to_ground_type = e.belt_to_ground_type
            local un = e.neighbours -- for underground belts this is the other end (or nil)
            if un and un.valid and un.unit_number then underground_other = un.unit_number end
        end

        out.belt_data = {
            item_lines = item_lines,
            belt_neighbours = ((#inputs_ids > 0 or #outputs_ids > 0) and { inputs = inputs_ids, outputs = outputs_ids }) or
            nil,
            belt_to_ground_type = belt_to_ground_type,
            underground_neighbour_unit = underground_other
        }
    elseif component_type == "pipes" then
        -- Pipe-specific data
        local inputs_ids, outputs_ids = {}, {}
        local fb = e.fluidbox
        if fb then
            for k = 1, #fb do
                local connections = fb.get_connections and fb.get_connections(k) or {}
                for _, conn in ipairs(connections) do
                    if conn.owner and conn.owner.valid and conn.owner.unit_number then
                        local conn_entity = conn.owner
                        local conn_unit = conn_entity.unit_number
                        
                        -- Categorize connections based on entity type and relative position
                        if conn_entity.type == "pipe" or conn_entity.type == "pipe-to-ground" then
                            if conn_entity.position and e.position then
                                local dx = conn_entity.position.x - e.position.x
                                local dy = conn_entity.position.y - e.position.y
                                if dx > 0 or dy > 0 then
                                    inputs_ids[#inputs_ids + 1] = conn_unit
                                else
                                    outputs_ids[#outputs_ids + 1] = conn_unit
                                end
                            else
                                inputs_ids[#inputs_ids + 1] = conn_unit
                            end
                        else
                            inputs_ids[#inputs_ids + 1] = conn_unit
                        end
                    end
                end
            end
        end

        out.pipe_data = {
            pipe_neighbours = ((#inputs_ids > 0 or #outputs_ids > 0) and { inputs = inputs_ids, outputs = outputs_ids }) or
            nil
        }
    end

    -- Inserter IO (pickup/drop positions and resolved targets) - for entities component
    if e.type == "inserter" then
        local ins = {
            pickup_position = e.pickup_position,
            drop_position   = e.drop_position,
        }
        local pt = e.pickup_target
        if pt and pt.valid and pt.unit_number then ins.pickup_target_unit = pt.unit_number end
        local dt = e.drop_target
        if dt and dt.valid and dt.unit_number then ins.drop_target_unit = dt.unit_number end
        if next(ins) ~= nil then out.inserter = ins end
    end

    return out
end

return EntitiesSnapshot
