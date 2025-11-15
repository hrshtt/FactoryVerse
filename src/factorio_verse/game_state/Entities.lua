--- factorio_verse/core/game_state/EntitiesGameState.lua
--- EntitiesGameState sub-module for managing entity-related functionality.
--- Static module - no instantiation required.
--- 
--- Responsibilities:
--- 1. Entity status tracking (for UDP snapshots)
--- 2. Disk snapshot management (file I/O for entity persistence)
--- 3. Admin remote interface facade for EntityInterface

-- Module-level local references for performance optimization
local pairs = pairs
local ipairs = ipairs

local EntityInterface = require("types.EntityInterface")
local serialize = require("utils.serialize")
local utils = require("utils.utils")
local snapshot = require("utils.snapshot")

local M = {}

-- ============================================================================
-- ENTITY STATUS TRACKING (for UDP snapshots)
-- ============================================================================

--- Track entity status change
--- @param entity LuaEntity
--- @return table {is_new_record: boolean, status: string}
function M.track_entity_status(entity)
    storage.entity_status = storage.entity_status or {}
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

--- Track entity status for all entities in a chunk
--- @param chunk_position table {x: number, y: number} Chunk coordinates
--- @return table Status records keyed by unit_number
function M.track_chunk_entity_status(chunk_position)
    local surface = game.surfaces[1]
    if not surface then
        return {}
    end
    
    local chunk_area = {
        left_top = {
            x = chunk_position.x * 32,
            y = chunk_position.y * 32
        },
        right_bottom = {
            x = (chunk_position.x + 1) * 32,
            y = (chunk_position.y + 1) * 32
        }
    }
    
    -- Check count first for early exit
    local entity_count = surface.count_entities_filtered {
        type = "entity",
        area = chunk_area
    }
    if entity_count == 0 then
        return {}
    end
    
    local entities = surface.find_entities_filtered {
        type = "entity",
        area = chunk_area
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

--- Track entity status for all charted chunks
--- @param charted_chunks table List of chunks to process
function M.track_all_charted_chunk_entity_status(charted_chunks)
    if not charted_chunks then
        return
    end
    
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

--- Get on_tick handlers
--- @return table Array of handler functions
function M.get_on_tick_handlers()
    return {}
end

--- Get events (defined events and nth_tick)
--- @return table {defined_events = {event_id -> handler, ...}, nth_tick = {tick_interval -> handler, ...}}
function M.get_events()
    -- Return disk_write_snapshot events
    local events = {}
    local nth_tick = {}
    
    if M.disk_write_snapshot then
        if M.disk_write_snapshot.events then
            for event_id, handler in pairs(M.disk_write_snapshot.events) do
                events[event_id] = handler
            end
        end
        if M.disk_write_snapshot.nth_tick then
            for tick_interval, handler in pairs(M.disk_write_snapshot.nth_tick) do
                nth_tick[tick_interval] = handler
            end
        end
    end
    
    return {
        defined_events = events,
        nth_tick = nth_tick
    }
end

-- ============================================================================
-- DISK WRITE SNAPSHOT FUNCTIONALITY
-- ============================================================================

--- Initialize disk write snapshot events
--- Must be called during on_init/on_load
--- Note: EntityInterface owns the entity_configuration_changed event
function M.init()
    -- Build disk_write_snapshot table after events are initialized
    M.disk_write_snapshot = M._build_disk_write_snapshot()
end

--- Write entity to disk snapshot
--- @param entity LuaEntity
--- @param is_update boolean|nil True if this is an update to existing entity (default: false)
--- @return boolean Success status
function M.write_entity_snapshot(entity, is_update)
    if not (entity and entity.valid) then
        return false
    end

    -- Serialize entity using utils/serialize
    local entity_data = serialize.serialize_entity(entity)
    if not entity_data then
        return false
    end

    -- Get chunk coordinates
    local chunk_coords = utils.to_chunk_coordinates(entity.position)
    if not chunk_coords then
        return false
    end

    -- Determine component type
    local component_type = serialize.get_component_type(entity.type, entity.name)

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
--- @return boolean Success status
function M._delete_entity_snapshot(entity)
    if not entity then
        return false
    end

    -- Get chunk coordinates from entity position (entity may be invalid)
    local position = entity.position
    if not position then
        return false
    end

    local chunk_coords = utils.to_chunk_coordinates(position)
    if not chunk_coords then
        return false
    end

    -- Determine component type (use entity.type and entity.name if available)
    local component_type = "entities"
    if entity.type and entity.name then
        component_type = serialize.get_component_type(entity.type, entity.name)
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
--- @param event table Event data with entity field
local function _on_entity_built(event)
    local entity = event.entity
    if entity and entity.valid then
        M.write_entity_snapshot(entity, false)
    end
end

--- Handle entity destroyed event (on_player_mined_entity, script_raised_destroy)
--- @param event table Event data with entity field
local function _on_entity_destroyed(event)
    local entity = event.entity
    if entity then
        M._delete_entity_snapshot(entity)
    end
end

--- Handle entity settings pasted event
--- @param event table Event data with destination field
local function _on_entity_settings_pasted(event)
    local entity = event.destination
    if entity and entity.valid then
        M.write_entity_snapshot(entity, true)
    end
end

--- Handle entity configuration changed event (from EntityInterface)
--- Listens to EntityInterface's entity_configuration_changed event
--- @param event table Event data with entity and change_type fields
local function _on_entity_configuration_changed(event)
    local entity = event.entity
    if entity and entity.valid then
        -- Write snapshot for any configuration change (recipe, filter, inventory_limit)
        M.write_entity_snapshot(entity, true)
    end
end

--- Build disk write snapshot events table
--- Called after init() to populate events
function M._build_disk_write_snapshot()
    if not EntityInterface.on_entity_configuration_changed then
        return { events = {}, nth_tick = {} }
    end

    return {
        events = {
            [defines.events.on_built_entity] = _on_entity_built,
            [defines.events.script_raised_built] = _on_entity_built,
            [defines.events.on_player_mined_entity] = _on_entity_destroyed,
            [defines.events.script_raised_destroy] = _on_entity_destroyed,
            [defines.events.on_entity_settings_pasted] = _on_entity_settings_pasted,
            [EntityInterface.on_entity_configuration_changed] = _on_entity_configuration_changed,
        },
        nth_tick = {}
    }
end

-- Expose disk_write_snapshot property for GameState aggregation
M.disk_write_snapshot = {}

-- ============================================================================
-- ADMIN REMOTE INTERFACE (Facade over EntityInterface)
-- ============================================================================

--- Register remote interface for EntityInterface admin methods
--- Thin facade that wraps EntityInterface methods for remote interface exposure
--- @return table Remote interface table with EntityInterface methods
function M.register_remote_interface()
    return {
        -- Recipe operations
        set_recipe = function(entity_name, position, recipe_name, overwrite, radius)
            local entity_interface = EntityInterface:new({
                entity_name = entity_name,
                position = position,
                radius = radius,
                strict = false,  -- Admin can handle multiple matches
            })
            overwrite = overwrite ~= false  -- Default true for admin
            return entity_interface:set_recipe(recipe_name, overwrite)
        end,
        
        -- Filter operations
        set_filter = function(entity_name, position, inventory_type, filter_index, filter_item, radius)
            local entity_interface = EntityInterface:new({
                entity_name = entity_name,
                position = position,
                radius = radius,
                strict = false,
            })
            return entity_interface:set_filter(inventory_type, filter_index, filter_item)
        end,
        
        -- Inventory limit operations
        set_inventory_limit = function(entity_name, position, inventory_type, limit, radius)
            local entity_interface = EntityInterface:new({
                entity_name = entity_name,
                position = position,
                radius = radius,
                strict = false,
            })
            return entity_interface:set_inventory_limit(inventory_type, limit)
        end,
        
        -- Inventory item operations
        get_inventory_item = function(entity_name, position, inventory_type, item_name, count, radius)
            local entity_interface = EntityInterface:new({
                entity_name = entity_name,
                position = position,
                radius = radius,
                strict = false,
            })
            return entity_interface:extract_inventory_items(inventory_type, item_name, count)
        end,
        
        set_inventory_item = function(entity_name, position, inventory_type, item_name, count, radius)
            local entity_interface = EntityInterface:new({
                entity_name = entity_name,
                position = position,
                radius = radius,
                strict = false,
            })
            
            -- Resolve inventory type
            local inv_index = inventory_type
            if type(inventory_type) == "string" then
                local inv_map = {
                    chest = defines.inventory.chest,
                    fuel = defines.inventory.fuel,
                    input = defines.inventory.assembling_machine_input,
                    output = defines.inventory.assembling_machine_output,
                }
                inv_index = inv_map[inventory_type]
                if not inv_index then
                    error("Admin EntityInterface: Unknown inventory type name: " .. inventory_type)
                end
            end
            
            -- Insert items
            local inventory = entity_interface.entity.get_inventory(inv_index --[[@as defines.inventory]])
            if not inventory then
                error("Admin EntityInterface: Entity does not have inventory at index " .. tostring(inv_index))
            end
            
            local inserted = inventory.insert({ name = item_name, count = count })
            if inserted < count then
                error("Admin EntityInterface: Failed to insert " .. count .. " items (only " .. inserted .. " inserted)")
            end
            
            return true
        end,
        
        extract_inventory_items = function(entity_name, position, inventory_type, radius)
            local entity_interface = EntityInterface:new({
                entity_name = entity_name,
                position = position,
                radius = radius,
                strict = false,
            })
            return entity_interface:extract_inventory_items(inventory_type)
        end,
        
        -- Entity manipulation
        rotate = function(entity_name, position, direction, radius)
            local entity_interface = EntityInterface:new({
                entity_name = entity_name,
                position = position,
                radius = radius,
                strict = false,
            })
            return entity_interface:rotate(direction)
        end,
        
        -- Entity queries
        get_type = function(entity_name, position, radius)
            local entity_interface = EntityInterface:new({
                entity_name = entity_name,
                position = position,
                radius = radius,
                strict = false,
            })
            return entity_interface:get_type()
        end,
        
        is_valid = function(entity_name, position, radius)
            local ok, entity_interface = pcall(function()
                return EntityInterface:new({
                    entity_name = entity_name,
                    position = position,
                    radius = radius,
                    strict = false,
                })
            end)
            if not ok then
                return false
            end
            return entity_interface:is_valid()
        end,
    }
end

return M
