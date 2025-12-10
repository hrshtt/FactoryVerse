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

local EntityInterface = require("EntityInterface")
local serialize = require("utils.serialize")
local utils = require("utils.utils")
local snapshot = require("utils.snapshot")

-- Local reference to utility function for performance
local entity_key = utils.entity_key

local M = {}

-- ============================================================================
-- ENTITY STATUS TRACKING (for UDP snapshots)
-- ============================================================================

--- Track entity status change
--- @param entity LuaEntity
--- @return table {is_new_record: boolean, status: string, key: string}
function M.track_entity_status(entity)
    storage.entity_status = storage.entity_status or {}
    local key = entity_key(entity.name, entity.position.x, entity.position.y)
    local last_record = storage.entity_status[key] or nil
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
    storage.entity_status[key] = last_record
    return { is_new_record = is_new_record, status = last_record.status, key = key }
end

--- Track entity status for all entities in a chunk
--- @param chunk_position table {x: number, y: number} Chunk coordinates
--- @return table Status records keyed by entity.name .. position.x .. position.y
function M.track_chunk_entity_status(chunk_position)
    local surface = game.surfaces[1]
    
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
        area = chunk_area,
        force = "player",
    }
    if entity_count == 0 then return {} end
    
    local entities = surface.find_entities_filtered {
        area = chunk_area,
        force = "player",
    }
    local status_records = {}
    for _, entity in ipairs(entities) do
        if entity and entity.valid then
            local result = M.track_entity_status(entity)
            if result.is_new_record then
                status_records[result.key] = {
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
    if not charted_chunks then return end
    
    local all_status_records = {}

    for _, chunk in ipairs(charted_chunks) do
        local chunk_pos = { x = chunk.x, y = chunk.y }
        local records = M.track_chunk_entity_status(chunk_pos)
        for key, status in pairs(records) do
            all_status_records[key] = status
        end
    end

    if next(all_status_records) ~= nil then
        snapshot.send_status_snapshot_udp(all_status_records)
    end
end

--- Get on_tick handlers
--- @return table Array of handler functions
function M.get_on_tick_handlers() return {} end

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

--- Append entity upsert operation to the updates log
--- This is the new approach: append to JSONL log instead of individual files
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

    -- Create upsert operation and append to log
    local operation = snapshot.make_upsert_operation(entity_data)
    local success = snapshot.append_entity_operation(chunk_coords.x, chunk_coords.y, operation)
    
    -- Send UDP notification (best-effort, log is the source of truth)
    if success then
        snapshot.send_entity_operation_udp(
            "upsert",
            chunk_coords.x,
            chunk_coords.y,
            entity_data.key,
            entity.name,
            entity.position,
            entity_data
        )
    end
    
    return success
end

--- Append entity remove operation to the updates log
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

    -- Build entity key
    local ent_key = entity_key(entity.name or "unknown", position.x, position.y)
    
    -- Create remove operation and append to log
    local operation = snapshot.make_remove_operation(ent_key, position, entity.name or "unknown")
    local success = snapshot.append_entity_operation(chunk_coords.x, chunk_coords.y, operation)
    
    -- Send UDP notification (best-effort, log is the source of truth)
    if success then
        snapshot.send_entity_operation_udp(
            "remove",
            chunk_coords.x,
            chunk_coords.y,
            ent_key,
            entity.name or "unknown",
            position,
            nil
        )
    end
    
    return success
end

-- ============================================================================
-- AGENT REACHABILITY INTEGRATION
-- ============================================================================

--- Mark all agents' reachability cache as dirty
--- Called when entities are built or destroyed anywhere on the map
local function _mark_all_agents_reachable_dirty()
    if storage.agents then
        for _, agent in pairs(storage.agents) do
            if agent and agent.reachable then
                agent.reachable.dirty = true
            end
        end
    end
end

--- Handle entity built event (on_built_entity, script_raised_built)
--- @param event table Event data with entity field
local function _on_entity_built(event)
    local entity = event.entity
    if entity and entity.valid then
        M.write_entity_snapshot(entity, false)
        
        -- Mark all agents' reachability as dirty
        _mark_all_agents_reachable_dirty()
    end
end

--- Handle entity destroyed event (on_player_mined_entity, script_raised_destroy)
--- @param event table Event data with entity field
local function _on_entity_destroyed(event)
    local entity = event.entity
    if entity then
        M._delete_entity_snapshot(entity)
        
        -- Mark all agents' reachability as dirty
        _mark_all_agents_reachable_dirty()
    end
end

local debug_render = require("utils.debug_render")

local function _on_player_mined_item(event)

    game.print("i am in event on_player_mined_item !")
    -- local entity = event.entity
    local item_stack = event.item_stack
    local player = game.players[event.player_index]
    if player then
        debug_render.render_player_floating_text(event.item_stack.name, { x = player.position.x, y = player.position.y })    
    end
    -- if entity then
    --     M.write_entity_snapshot(entity, true)
    -- end
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
            -- [defines.events.on_player_mined_entity] = _on_entity_destroyed,sa
            -- [defines.events.on_player_mined_item] = _on_player_mined_item,
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
            local entity_interface = EntityInterface:new(entity_name, position, radius, false)  -- Admin can handle multiple matches
            overwrite = overwrite ~= false  -- Default true for admin
            return entity_interface:set_recipe(recipe_name, overwrite)
        end,
        
        -- Filter operations
        set_filter = function(entity_name, position, inventory_type, filter_index, filter_item, radius)
            local entity_interface = EntityInterface:new(entity_name, position, radius, false)
            return entity_interface:set_filter(inventory_type, filter_index, filter_item)
        end,
        
        -- Inventory limit operations
        set_inventory_limit = function(entity_name, position, inventory_type, limit, radius)
            local entity_interface = EntityInterface:new(entity_name, position, radius, false)
            return entity_interface:set_inventory_limit(inventory_type, limit)
        end,
        
        -- Inventory item operations
        remove_inventory_item = function(entity_name, position, inventory_type, item_name, count, radius)
            local entity_interface = EntityInterface:new(entity_name, position, radius, false)
            return entity_interface:extract_inventory_items(inventory_type, item_name, count)
        end,
        
        set_inventory_item = function(entity_name, position, inventory_type, item_name, count, radius)
            local entity_interface = EntityInterface:new(entity_name, position, radius, false)
            
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
        
        extract_inventory_items = function(entity_name, position, radius)
            local entity_interface = EntityInterface:new(entity_name, position, radius, false)
            return entity_interface:extract_inventory_items()
        end,
        
        -- Entity manipulation
        rotate = function(entity_name, position, direction, radius)
            local entity_interface = EntityInterface:new(entity_name, position, radius, false)
            return entity_interface:rotate(direction)
        end,
        
    }
end

return M
