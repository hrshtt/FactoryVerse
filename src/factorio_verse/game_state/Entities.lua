--- factorio_verse/core/game_state/EntitiesGameState.lua
--- EntitiesGameState sub-module for managing entity-related functionality.
--- Static module - no instantiation required.

-- Module-level local references for global lookups (performance optimization)
local pairs = pairs
local ipairs = ipairs

local GameStateError = require("types.Error")
local utils = require("utils.utils")
local Map = require("game_state.Map")
local snapshot = require("utils.snapshot")

local M = {}

-- Custom event IDs (initialized in init())
M.custom_events = {}

--- @param area table
--- @param filter string
--- @return table
function M.get_entities_in_area(area, filter)
    local surface = game.surfaces[1]  -- Uses module-level local 'game'
    if not surface then
        return {}
    end

    local entities = surface.find_entities_filtered {
        area = area,
        type = filter
    }
    return entities
end

function M.find_entity(entity_name, position)
    local surface = game.surfaces[1]
    local entity = surface.find_entity(entity_name, position)
    if not entity or not entity.valid then
        return GameStateError:new("No entity found at position")
    end
    return entity
end

--- Get a single entity, input can be a JSON string or a table.
--- @param input string|table - JSON string or argument table ({name=..., position={x=..., y=...}})
--- @return LuaEntity|GameStateError
function M.get_entity(input)
    local params = input

    -- If input is a string, try to parse as JSON
    if type(input) == "string" then
        local status, result = pcall(function()
            helpers.json_to_table(input)
        end)
        if not status or type(result) ~= "table" then
            return GameStateError:new("Failed to parse JSON input")
        end
        params = result
    end

    -- Table check
    if type(params) ~= "table" then
        return GameStateError:new("Input must be a table or valid JSON string")
    end

    if type(params.name) ~= "string" or not params.position then
        return GameStateError:new("Missing required fields: 'name' (string) and 'position' (table)")
    end

    local pos = params.position
    if type(pos) ~= "table" or type(pos.x) ~= "number" or type(pos.y) ~= "number" then
        return GameStateError:new("Position must be a table containing numeric 'x' and 'y'")
    end

    return M.find_entity(params.name, { x = pos.x, y = pos.y })
end

function M.can_place_entity(entity_name, position)
    local surface = game.surfaces[1]
    if not surface then
        return GameStateError:new("No surface available")
    end

    return surface.can_place_entity {
        name = entity_name,
        position = position
    }
end

--- Determine component type for an entity
--- @param entity_type string - entity type from Factorio API
--- @param entity_name string - entity prototype name
--- @return string - component type ("belts", "pipes", "poles", "entities")
function M._determine_component_type(entity_type, entity_name)
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

--- Serialize base properties common to all entities
--- @param entity LuaEntity
--- @param out table - output table to populate
--- @return table
function M._serialize_base_properties(entity, out)
    local proto = entity.prototype

    -- Base identity and spatial properties
    out.unit_number = entity.unit_number
    out.name = entity.name
    out.type = entity.type
    out.force = (entity.force and entity.force.name) or nil
    out.position = entity.position
    out.direction = entity.direction
    out.direction_name = utils.direction_to_name(entity.direction and tonumber(tostring(entity.direction)) or nil)
    out.orientation = entity.orientation
    out.orientation_name = utils.orientation_to_name(entity.orientation)

    -- Electric network id
    if entity.electric_network_id ~= nil then
        out.electric_network_id = entity.electric_network_id
    end

    -- Tile dimensions from prototype
    if proto then
        if proto.tile_width ~= nil then out.tile_width = proto.tile_width end
        if proto.tile_height ~= nil then out.tile_height = proto.tile_height end
    end

    -- Crafting / recipe (gate to crafting machines only)
    local is_crafter = (entity.type == "assembling-machine" or entity.type == "furnace")
    if not is_crafter and proto and proto.crafting_categories then
        is_crafter = true
    end

    if is_crafter then
        -- Per docs, LuaEntity::get_recipe() is the supported way to read the current recipe
        local r = entity.get_recipe()
        if r then out.recipe = r.name end
    end

    -- Bounding box
    local bb = entity.bounding_box
    if bb and bb.left_top and bb.right_bottom then
        out.bounding_box = {
            min_x = bb.left_top.x,
            min_y = bb.left_top.y,
            max_x = bb.right_bottom.x,
            max_y = bb.right_bottom.y
        }
    end
end

--- Serialize belt-specific data
--- @param entity LuaEntity
--- @param out table - output table to populate
--- @return table
function M._serialize_belt_data(entity, out)
    -- Belt item lines
    local item_lines = {}
    local max_index = 0
    local v = (entity.get_max_transport_line_index and entity.get_max_transport_line_index()) or 0
    max_index = (type(v) == "number" and v > 0) and v or 0

    for li = 1, max_index do
        local tl = entity.get_transport_line and entity.get_transport_line(li) or nil
        if tl then
            local contents = tl.get_contents and tl.get_contents() or nil
            if contents and next(contents) ~= nil then
                item_lines[#item_lines + 1] = { index = li, items = contents }
            end
        end
    end

    -- Belt neighbours (inputs/outputs)
    local inputs_ids, outputs_ids = {}, {}
    local bn = entity.belt_neighbours
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

    -- Underground belt pairing
    local underground_other = nil
    local belt_to_ground_type = nil
    if entity.type == "underground-belt" then
        belt_to_ground_type = entity.belt_to_ground_type
        local un = entity.neighbours -- for underground belts this is the other end (or nil)
        if un and un.valid and un.unit_number then underground_other = un.unit_number end
    end

    out.belt_data = {
        item_lines = item_lines,
        belt_neighbours = ((#inputs_ids > 0 or #outputs_ids > 0) and { inputs = inputs_ids, outputs = outputs_ids }) or
        nil,
        belt_to_ground_type = belt_to_ground_type,
        underground_neighbour_unit = underground_other
    }
end

--- Serialize pipe-specific data
--- @param entity LuaEntity
--- @param out table - output table to populate
--- @return table
function M._serialize_pipe_data(entity, out)
    local inputs_ids, outputs_ids = {}, {}
    local fb = entity.fluidbox
    if fb then
        for k = 1, #fb do
            local connections = fb.get_connections and fb.get_connections(k) or {}
            for _, conn in ipairs(connections) do
                if conn.owner and conn.owner.valid and conn.owner.unit_number then
                    local conn_entity = conn.owner
                    local conn_unit = conn_entity.unit_number

                    -- Categorize connections based on entity type and relative position
                    if conn_entity.type == "pipe" or conn_entity.type == "pipe-to-ground" then
                        if conn_entity.position and entity.position then
                            local dx = conn_entity.position.x - entity.position.x
                            local dy = conn_entity.position.y - entity.position.y
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

--- Serialize inserter-specific data
--- @param entity LuaEntity
--- @param out table - output table to populate
--- @return table
function M._serialize_inserter_data(entity, out)
    local ins = {
        pickup_position = entity.pickup_position,
        drop_position = entity.drop_position,
    }
    local pt = entity.pickup_target
    if pt and pt.valid and pt.unit_number then ins.pickup_target_unit = pt.unit_number end
    local dt = entity.drop_target
    if dt and dt.valid and dt.unit_number then ins.drop_target_unit = dt.unit_number end
    if next(ins) ~= nil then out.inserter = ins end
end

--- Serialize entity data for JSON storage
--- @param entity LuaEntity
--- @return table|nil - serialized entity data or nil if invalid
function M.serialize_entity(entity)
    if not (entity and entity.valid) then return nil end

    local out = {}

    -- Serialize base properties
    M._serialize_base_properties(entity, out)

    -- Determine component type and serialize component-specific data
    local component_type = M._determine_component_type(entity.type, entity.name)

    if component_type == "belts" then
        M._serialize_belt_data(entity, out)
    elseif component_type == "pipes" then
        M._serialize_pipe_data(entity, out)
    end

    -- Inserter IO (pickup/drop positions and resolved targets)
    if entity.type == "inserter" then
        M._serialize_inserter_data(entity, out)
    end

    return out
end

function M.track_entity_status(entity)
    local last_record = storage.entity_status[entity.unit_number] or nil
    local is_new_record = false
    if last_record and (last_record.status == entity.status) then
        last_record.tick = game.tick
    else
        last_record = {
            status = entity.status,
            tick = game.tick
        }
        is_new_record = true
    end
    storage.entity_status[entity.unit_number] = last_record
    return { is_new_record = is_new_record, status = last_record.status }
end

function M.track_chunk_entity_status(chunk_position)
    local surface = game.surfaces[1]
    if not surface then
        return {}
    end
    local entities = surface.find_entities_filtered {
        type = "entity",
        area = {
            left_top = {
                x = chunk_position.x * 32,
                y = chunk_position.y * 32
            },
            right_bottom = {
                x = (chunk_position.x + 1) * 32,
                y = (chunk_position.y + 1) * 32
            }
        }
    }
    local status_records = {}
    for _, entity in ipairs(entities) do
        if entity and entity.valid then
            local result = M.track_entity_status(entity)
            if result.is_new_record then
                status_records[entity.unit_number] = {
                    position = { entity.position.x, entity.position.y },
                    status = result.status,
                    tick = game.tick
                }
            end
        end
    end
    return status_records
end

--- Run track_chunk_entity_status on all charted chunks
function M.track_all_charted_chunk_entity_status()
    local charted_chunks = Map.get_charted_chunks()
    local all_status_records = {}

    for _, chunk in ipairs(charted_chunks) do
        local chunk_pos = { x = chunk.x, y = chunk.y }
        local records = M.track_chunk_entity_status(chunk_pos)
        for unit_number, status in pairs(records) do
            all_status_records[unit_number] = status
        end
    end

    if next(all_status_records) ~= nil then
        snapshot.send_status_snapshot_udp(all_status_records)
    end
end

function M.get_event_based_snapshot_events()
    return {
        nth_tick = {
            [10] = function()
                M.track_all_charted_chunk_entity_status()
            end
        }
    }
end

-- ============================================================================
-- DISK WRITE SNAPSHOT FUNCTIONALITY
-- ============================================================================

--- Initialize custom events for entity snapshotting
--- Must be called during on_init/on_load
function M.init()
    -- Generate custom event ID for recipe changes
    M.custom_events.entity_recipe_changed = script.generate_event_name()
    log("Entities: Generated custom event 'entity_recipe_changed': " .. tostring(M.custom_events.entity_recipe_changed))
    
    -- Build disk_write_snapshot table after events are initialized
    M.disk_write_snapshot = M._build_disk_write_snapshot()
end

--- Write entity to disk snapshot
--- Public function for use by Map deferred scanning
--- @param entity LuaEntity
--- @param is_update boolean|nil - True if this is an update to existing entity (default: false, treated as create)
--- @return boolean - Success status
function M.write_entity_snapshot(entity, is_update)
    if not (entity and entity.valid) then
        return false
    end

    -- Serialize entity
    local entity_data = M.serialize_entity(entity)
    if not entity_data then
        return false
    end

    -- Get chunk coordinates
    local chunk_coords = Map.to_chunk_coordinates(entity.position)
    if not chunk_coords then
        return false
    end

    -- Determine component type
    local component_type = M._determine_component_type(entity.type, entity.name)

    -- Generate file path
    local file_path = snapshot.entity_file_path(
        chunk_coords.x,
        chunk_coords.y,
        component_type,
        entity.position,
        entity.name
    )

    -- Write file
    local success = snapshot.write_entity_file(file_path, entity_data)
    
    -- Send UDP notification
    if success then
        local event_type = (is_update == true) and "file_updated" or "file_created"
        snapshot.send_file_event_udp(
            event_type,
            "entity",
            chunk_coords.x,
            chunk_coords.y,
            entity.position,
            entity.name,
            component_type,
            file_path
        )
    end
    
    return success
end

--- Delete entity from disk snapshot
--- @param entity LuaEntity
--- @return boolean - Success status
function M._delete_entity_snapshot(entity)
    if not entity then
        return false
    end

    -- Get chunk coordinates from entity position (entity may be invalid)
    local position = entity.position
    if not position then
        return false
    end

    local chunk_coords = Map.to_chunk_coordinates(position)
    if not chunk_coords then
        return false
    end

    -- Determine component type (use entity.type and entity.name if available)
    local component_type = "entities"
    if entity.type and entity.name then
        component_type = M._determine_component_type(entity.type, entity.name)
    end

    -- Generate file path
    local file_path = snapshot.entity_file_path(
        chunk_coords.x,
        chunk_coords.y,
        component_type,
        position,
        entity.name or "unknown"
    )

    -- Delete file
    local success = snapshot.delete_entity_file(file_path)
    
    -- Send UDP notification
    if success then
        snapshot.send_file_event_udp(
            "file_deleted",
            "entity",
            chunk_coords.x,
            chunk_coords.y,
            position,
            entity.name or "unknown",
            component_type,
            file_path
        )
    end
    
    return success
end

--- Handle entity built event (on_built_entity, script_raised_built)
--- @param event table - Event data with entity field
function M._on_entity_built(event)
    local entity = event.entity
    if entity and entity.valid then
        -- New entity, so this is a create (not update)
        M.write_entity_snapshot(entity, false)
    end
end

--- Handle entity destroyed event (on_player_mined_entity, script_raised_destroy)
--- @param event table - Event data with entity field
function M._on_entity_destroyed(event)
    local entity = event.entity
    if entity then
        M._delete_entity_snapshot(entity)
    end
end

--- Handle entity settings pasted event
--- @param event table - Event data with destination field
function M._on_entity_settings_pasted(event)
    local entity = event.destination
    if entity and entity.valid then
        -- Settings pasted means entity was updated
        M.write_entity_snapshot(entity, true)
    end
end

--- Handle custom recipe changed event
--- @param event table - Event data with entity field
function M._on_recipe_changed(event)
    local entity = event.entity
    if entity and entity.valid then
        -- Recipe change means entity was updated
        M.write_entity_snapshot(entity, true)
    end
end

--- Build disk write snapshot events table
--- Called after init() to populate events
function M._build_disk_write_snapshot()
    if not M.custom_events.entity_recipe_changed then
        -- Events not initialized yet, return empty
        return { events = {}, nth_tick = {} }
    end

    return {
        events = {
            [defines.events.on_built_entity] = M._on_entity_built,
            [defines.events.script_raised_built] = M._on_entity_built,
            [defines.events.on_player_mined_entity] = M._on_entity_destroyed,
            [defines.events.script_raised_destroy] = M._on_entity_destroyed,
            [defines.events.on_entity_settings_pasted] = M._on_entity_settings_pasted,
            [M.custom_events.entity_recipe_changed] = M._on_recipe_changed,
        },
        nth_tick = {}
    }
end

-- Expose disk_write_snapshot property for GameState aggregation
-- This will be populated after init() is called
M.disk_write_snapshot = {}

return M
