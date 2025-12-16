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

-- EntityInterface is from fv_embodied_agent mod (dependency)
local EntityInterface = require("__fv_embodied_agent__.game_state.EntityInterface")
local serialize = require("__fv_embodied_agent__/utils/serialize")
local utils = require("utils.utils")
local snapshot = require("utils.snapshot")
local udp_payloads = require("utils.udp_payloads")
local Agents = require("__fv_embodied_agent__/game_state/Agents")
local debug_render = require("__fv_embodied_agent__/utils/debug_render")
local Resource = require("game_state.Resource")

-- Local reference to utility function for performance
local entity_key = utils.entity_key

local M = {}

-- Debug flag for status dumps and event handlers
M.DEBUG = false

-- ============================================================================
-- ENTITY STATUS TRACKING (for UDP snapshots)
-- ============================================================================

-- Entity name enum mapping (for status dumps only)
local ENTITY_NAME_ENUM = {
    ["accumulator"] = 0,
    ["assembling-machine-1"] = 1,
    ["assembling-machine-2"] = 2,
    ["assembling-machine-3"] = 3,
    ["beacon"] = 4,
    ["big-electric-pole"] = 5,
    ["blue-chest"] = 6,
    ["boiler"] = 7,
    ["bulk-inserter"] = 8,
    ["burner-generator"] = 9,
    ["burner-inserter"] = 10,
    ["burner-mining-drill"] = 11,
    ["centrifuge"] = 12,
    ["chemical-plant"] = 13,
    ["electric-furnace"] = 14,
    ["electric-mining-drill"] = 15,
    ["express-splitter"] = 16,
    ["express-transport-belt"] = 17,
    ["express-underground-belt"] = 18,
    ["fast-inserter"] = 19,
    ["fast-splitter"] = 20,
    ["fast-transport-belt"] = 21,
    ["fast-underground-belt"] = 22,
    ["gate"] = 23,
    ["heat-exchanger"] = 24,
    ["heat-interface"] = 25,
    ["heat-pipe"] = 26,
    ["inserter"] = 27,
    ["iron-chest"] = 28,
    ["lab"] = 29,
    ["lane-splitter"] = 30,
    ["long-handed-inserter"] = 31,
    ["medium-electric-pole"] = 32,
    ["nuclear-reactor"] = 33,
    ["offshore-pump"] = 34,
    ["oil-refinery"] = 35,
    ["pipe"] = 36,
    ["pipe-to-ground"] = 37,
    ["pump"] = 38,
    ["pumpjack"] = 39,
    ["radar"] = 40,
    ["red-chest"] = 41,
    ["rocket-silo"] = 42,
    ["small-electric-pole"] = 43,
    ["solar-panel"] = 44,
    ["splitter"] = 45,
    ["steam-engine"] = 46,
    ["steam-turbine"] = 47,
    ["steel-chest"] = 48,
    ["steel-furnace"] = 49,
    ["stone-furnace"] = 50,
    ["stone-wall"] = 51,
    ["substation"] = 52,
    ["transport-belt"] = 53,
    ["underground-belt"] = 54,
    ["wooden-chest"] = 55,
}

--- Check if entity name is in the status tracking enum
--- @param entity_name string
--- @return boolean
local function is_trackable_entity(entity_name)
    return ENTITY_NAME_ENUM[entity_name] ~= nil
end

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
    
    -- if M.DEBUG then
    --     game.print(string.format("[DEBUG Entities.track_all_charted_chunk_entity_status] Tick %d: processing %d chunks", 
    --         game.tick, #charted_chunks))
    -- end
    
    local all_status_records = {}
    local processed_chunks = 0

    for _, chunk in ipairs(charted_chunks) do
        local chunk_pos = { x = chunk.x, y = chunk.y }
        local records = M.track_chunk_entity_status(chunk_pos)
        processed_chunks = processed_chunks + 1
        for key, status in pairs(records) do
            all_status_records[key] = status
        end
    end

    -- if M.DEBUG then
    --     local record_count = 0
    --     for _ in pairs(all_status_records) do record_count = record_count + 1 end
    --     game.print(string.format("[DEBUG Entities.track_all_charted_chunk_entity_status] Tick %d: processed %d chunks, %d status records", 
    --         game.tick, processed_chunks, record_count))
    -- end

    if next(all_status_records) ~= nil then
        snapshot.send_status_snapshot_udp(all_status_records)
    end
end

-- ============================================================================
-- STATUS DUMP TO DISK (compressed format)
-- ============================================================================

--- Collect all entity statuses from charted chunks
--- Returns array of [status_enum, entity_enum, pos_x_int, pos_y_int] tuples
--- @param charted_chunks table List of chunks to process
--- @return table Array of status records
function M.collect_all_statuses_for_dump(charted_chunks)
    if not charted_chunks then return {} end
    
    local surface = game.surfaces[1]
    local status_records = {}
    
    for _, chunk in ipairs(charted_chunks) do
        local chunk_area = {
            left_top = {
                x = chunk.x * 32,
                y = chunk.y * 32
            },
            right_bottom = {
                x = (chunk.x + 1) * 32,
                y = (chunk.y + 1) * 32
            }
        }
        
        -- Check count first for early exit
        local entity_count = surface.count_entities_filtered {
            area = chunk_area,
            force = "player",
        }
        if entity_count == 0 then goto continue end
        
        local entities = surface.find_entities_filtered {
            area = chunk_area,
            force = "player",
        }
        
        for _, entity in ipairs(entities) do
            if entity and entity.valid and entity.status then
                -- Only track entities in our enum
                if not is_trackable_entity(entity.name) then
                    goto next_entity
                end
                
                local entity_enum = ENTITY_NAME_ENUM[entity.name]
                local status_enum = entity.status  -- Already a number from defines.entity_status
                local pos_x = entity.position.x
                local pos_y = entity.position.y
                
                -- Convert position to integer (multiply by 2 since x%0.5 == 0 and y%0.5 == 0)
                local pos_x_int = math.floor(pos_x * 2)
                local pos_y_int = math.floor(pos_y * 2)
                
                -- Format: [entity_enum, status_enum, x, y]
                table.insert(status_records, {
                    entity_enum,
                    status_enum,
                    pos_x_int,
                    pos_y_int
                })
            end
            ::next_entity::
        end
        ::continue::
    end
    
    return status_records
end

--- Dump status data to disk as JSONL
--- @param charted_chunks table List of chunks to process
function M.dump_status_to_disk(charted_chunks)
    local status_records = M.collect_all_statuses_for_dump(charted_chunks)
    
    if #status_records == 0 then
        return
    end
    
    -- Build JSONL content: one JSON array per line [entity_enum, status_enum, x, y]
    local jsonl_lines = {}
    for _, record in ipairs(status_records) do
        local ok, json_str = pcall(helpers.table_to_json, record)
        if ok and json_str then
            table.insert(jsonl_lines, json_str)
        end
    end
    
    if #jsonl_lines == 0 then
        return
    end
    
    -- Write JSONL to disk
    local file_path = snapshot.status_dump_path(game.tick)
    local content = table.concat(jsonl_lines, "\n") .. "\n"
    local ok_write = pcall(helpers.write_file, file_path, content, false)
    if not ok_write then
        log("Failed to write status dump file: " .. tostring(file_path))
        return
    end
    
    -- Track file and cleanup old ones
    snapshot.track_status_dump_file(game.tick)
    snapshot.cleanup_old_status_dumps()
    
    -- NO UDP notification for status dumps - disk-only design
    -- External systems are responsible for reading and managing their own memory
    
    if M.DEBUG and game and game.print then
        game.print(string.format("[status_dump] Wrote status dump: %s (%d entities)", file_path, #status_records))
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
    if game and game.print then
        game.print(string.format("[DEBUG Entities.init] Tick %d: Initializing Entities module", game.tick))
    end
    -- Build disk_write_snapshot table after events are initialized
    M.disk_write_snapshot = M._build_disk_write_snapshot()
    if game and game.print then
        game.print(string.format("[DEBUG Entities.init] Tick %d: Finished initializing Entities module", game.tick))
    end
end

--- Append entity created operation to the updates log and send UDP notification
--- @param entity LuaEntity
--- @return boolean Success status
function M.write_entity_snapshot(entity, is_update)
    if not (entity and entity.valid) then
        return false
    end

    if M.DEBUG then
        game.print(string.format("[DEBUG Entities.write_entity_snapshot] Tick %d: serializing entity %s", 
            game.tick, entity.name or "unknown"))
    end

    -- Serialize entity using utils/serialize
    local entity_data = serialize.serialize_entity(entity)
    if not entity_data then
        if M.DEBUG then
            game.print(string.format("[DEBUG Entities.write_entity_snapshot] Tick %d: serialization failed for %s", 
                game.tick, entity.name or "unknown"))
        end
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
    
    if M.DEBUG then
        game.print(string.format("[DEBUG Entities.write_entity_snapshot] Tick %d: wrote entity %s to chunk (%d,%d), success=%s", 
            game.tick, entity.name or "unknown", chunk_coords.x, chunk_coords.y, tostring(success)))
    end
    
    -- Send UDP notification using payload module (best-effort, log is the source of truth)
    if success then
        local chunk = { x = chunk_coords.x, y = chunk_coords.y }
        local payload = udp_payloads.entity_created(chunk, entity_data)
        udp_payloads.send_entity_operation(payload)
    end
    
    return success
end

--- Append entity destroyed operation to the updates log and send UDP notification
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
    
    -- Send UDP notification using payload module (best-effort, log is the source of truth)
    if success then
        local chunk = { x = chunk_coords.x, y = chunk_coords.y }
        local payload = udp_payloads.entity_destroyed(chunk, ent_key, entity.name or "unknown", position)
        udp_payloads.send_entity_operation(payload)
    end
    
    return success
end

--- Handle entity built event (on_built_entity, script_raised_built)
--- @param event table Event data with entity field
local function _on_entity_built(event)
    local entity = event.entity
    if M.DEBUG then
        game.print(string.format("[DEBUG Entities._on_entity_built] Tick %d: entity=%s at (%.1f, %.1f)", 
            game.tick, entity and entity.name or "nil", 
            entity and entity.position.x or 0, entity and entity.position.y or 0))
    end
    if entity and entity.valid then
        M.write_entity_snapshot(entity, false)
    end
end

--- Handle entity destroyed event (on_player_mined_entity, script_raised_destroy)
--- Separates resource entities (trees, rocks) from player-built entities
--- Resource tiles (ore patches) are ignored - handled by on_resource_depleted
--- @param event table Event data with entity field
local function _on_entity_destroyed(event)
    if M.DEBUG then
        game.print(string.format("[DEBUG Entities._on_entity_destroyed] Tick %d: Event received", game.tick))
    end
    
    local entity = event.entity
    if not entity then
        if M.DEBUG then
            game.print(string.format("[DEBUG Entities._on_entity_destroyed] Tick %d: No entity in event", game.tick))
        end
        return
    end
    
    if M.DEBUG then
        game.print(string.format("[DEBUG Entities._on_entity_destroyed] Tick %d: entity=%s, type=%s, name=%s", 
            game.tick, entity and "valid" or "nil", entity.type or "nil", entity.name or "nil"))
    end
    
    -- Ignore resource tiles (ore patches) - these are handled by on_resource_depleted
    -- Resource tiles have type = "resource" and are not tracked as entities
    if entity.type == "resource" then
        if M.DEBUG then
            game.print(string.format("[DEBUG Entities._on_entity_destroyed] Tick %d: Ignoring resource tile %s", 
                game.tick, entity.name or "unknown"))
        end
        return
    end
    
    -- Handle resource entities (trees, rocks) separately - trigger resource file rewrite
    -- Trees: type = "tree"
    -- Rocks: type = "simple-entity" with name matching "rock" or "stone"
    local is_resource_entity = false
    if entity.type == "tree" then
        is_resource_entity = true
    elseif entity.type == "simple-entity" and entity.name then
        if entity.name:match("rock") or entity.name:match("stone") then
            is_resource_entity = true
        end
    end
    
    if is_resource_entity then
        -- Resource entities (trees/rocks) need both:
        -- 1. Resource file rewrite (for trees_rocks_init.jsonl)
        -- 2. Trees/rocks update entry (for trees_rocks-update.jsonl, NOT entities_updates.jsonl)
        local chunk_coords = utils.to_chunk_coordinates(entity.position)
        if chunk_coords then
            if M.DEBUG then
                game.print(string.format("[DEBUG Entities._on_entity_destroyed] Tick %d: Resource entity %s mined, rewriting chunk (%d,%d) resources and creating trees_rocks update entry", 
                    game.tick, entity.name or "unknown", chunk_coords.x, chunk_coords.y))
            end
            -- 1. Rewrite resource files (trees_rocks_init.jsonl)
            if Resource and Resource._rewrite_chunk_resources then
                Resource._rewrite_chunk_resources(chunk_coords.x, chunk_coords.y)
            end
            -- 2. Create trees/rocks update entry (trees_rocks-update.jsonl) - handled by Resource.lua
            if Resource and Resource.create_trees_rocks_update_entry then
                Resource.create_trees_rocks_update_entry(entity, chunk_coords.x, chunk_coords.y)
            end
        end
        return
    end
    
    -- Only player-built entities reach here - delete from entity snapshot
    if M.DEBUG then
        game.print(string.format("[DEBUG Entities._on_entity_destroyed] Tick %d: Player entity %s destroyed", 
            game.tick, entity.name or "unknown"))
    end
    M._delete_entity_snapshot(entity)
end

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
    if not (entity and entity.valid) then
        return
    end
    
    -- Serialize entity to get updated configuration
    local entity_data = serialize.serialize_entity(entity)
    if not entity_data then
        return
    end
    
    -- Get chunk coordinates
    local chunk_coords = utils.to_chunk_coordinates(entity.position)
    if not chunk_coords then
        return
    end
    
    -- Send UDP notification for configuration change (no file write needed, config is tracked via entity operation)
    local chunk = { x = chunk_coords.x, y = chunk_coords.y }
    local payload = udp_payloads.entity_configuration_changed(chunk, entity_data)
    udp_payloads.send_entity_operation(payload)
end

--- Handle entity rotated event (from EntityInterface)
--- Listens to EntityInterface's entity_rotated event
--- @param event table Event data with entity, old_direction, and new_direction fields
local function _on_entity_rotated(event)
    local entity = event.entity
    if not (entity and entity.valid) then
        return
    end
    
    -- Get chunk coordinates
    local chunk_coords = utils.to_chunk_coordinates(entity.position)
    if not chunk_coords then
        return
    end
    
    -- Build entity key
    local ent_key = entity_key(entity.name or "unknown", entity.position.x, entity.position.y)
    
    -- Send UDP notification for rotation (no file write needed, rotation is tracked via entity operation)
    local chunk = { x = chunk_coords.x, y = chunk_coords.y }
    local payload = udp_payloads.entity_rotated(
        chunk,
        ent_key,
        entity.name or "unknown",
        entity.position,
        entity.direction,
        game.tick
    )
    udp_payloads.send_entity_operation(payload)
end

--- Handle agent entity built event (from Agent custom events)
--- Listens to Agent.on_agent_entity_built event
--- @param event table Event data with entity field
local function _on_agent_entity_built(event)
    local entity = event.entity
    if entity and entity.valid then
        M.write_entity_snapshot(entity, false)
    end
end

--- Handle agent entity destroyed event (from Agent custom events)
--- Listens to Agent.on_agent_entity_destroyed event
--- Handles both resource entities (trees/rocks) and player-built entities
--- @param event table Event data with entity, entity_name, entity_type, position fields
local function _on_agent_entity_destroyed(event)
    game.print(string.format("[DEBUG Entities._on_agent_entity_destroyed] Tick %d: Event received! entity_name=%s, entity_type=%s, position=%s", 
        game.tick, event.entity_name or "nil", event.entity_type or "nil",
        event.position and string.format("{%f,%f}", event.position.x, event.position.y) or "nil"))
    
    -- Entity may be nil if already destroyed (common for mining)
    local entity = event.entity
    local entity_name = event.entity_name
    local entity_type = event.entity_type
    local position = event.position
    
    -- If we have entity info but no entity object, create a minimal entity-like object
    game.print(string.format("[DEBUG Entities._on_agent_entity_destroyed] Tick %d: Checking conditions - entity=%s, entity_name=%s, position=%s", 
        game.tick, entity and "valid" or "nil", tostring(entity_name), position and "valid" or "nil"))
    
    if not entity and entity_name and position then
        -- Check if it's a resource entity (tree or rock)
        local is_resource_entity = false
        if entity_type == "tree" then
            is_resource_entity = true
            game.print(string.format("[DEBUG Entities._on_agent_entity_destroyed] Tick %d: Detected tree entity", game.tick))
        elseif entity_type == "simple-entity" and entity_name then
            if entity_name:match("rock") or entity_name:match("stone") then
                is_resource_entity = true
                game.print(string.format("[DEBUG Entities._on_agent_entity_destroyed] Tick %d: Detected rock entity: %s", game.tick, entity_name))
            end
        end
        
        game.print(string.format("[DEBUG Entities._on_agent_entity_destroyed] Tick %d: is_resource_entity=%s", game.tick, tostring(is_resource_entity)))
        
        if is_resource_entity then
            -- Handle resource entities (trees/rocks) - rewrite resource files and create update entry
            local chunk_coords = utils.to_chunk_coordinates(position)
            game.print(string.format("[DEBUG Entities._on_agent_entity_destroyed] Tick %d: chunk_coords=%s", 
                game.tick, chunk_coords and string.format("{%d,%d}", chunk_coords.x, chunk_coords.y) or "nil"))
            
            if chunk_coords then
                game.print(string.format("[DEBUG Entities._on_agent_entity_destroyed] Tick %d: Resource entity %s mined by agent, rewriting chunk (%d,%d) resources", 
                    game.tick, entity_name or "unknown", chunk_coords.x, chunk_coords.y))
                -- 1. Rewrite resource files (trees_rocks_init.jsonl)
                if Resource and Resource._rewrite_chunk_resources then
                    game.print(string.format("[DEBUG Entities._on_agent_entity_destroyed] Tick %d: Calling Resource._rewrite_chunk_resources", game.tick))
                    Resource._rewrite_chunk_resources(chunk_coords.x, chunk_coords.y)
                else
                    game.print(string.format("[DEBUG Entities._on_agent_entity_destroyed] Tick %d: WARNING - Resource or _rewrite_chunk_resources not available", game.tick))
                end
                -- 2. Create trees/rocks update entry (trees_rocks-update.jsonl)
                -- Create a minimal entity-like object for Resource.create_trees_rocks_update_entry
                -- Must match the structure expected: entity.position must be a table with x and y
                local fake_entity = {
                    name = entity_name,
                    type = entity_type,
                    position = position,  -- position is already {x, y} from event
                    valid = false,  -- Mark as invalid since it's destroyed
                }
                if Resource and Resource.create_trees_rocks_update_entry then
                    Resource.create_trees_rocks_update_entry(fake_entity, chunk_coords.x, chunk_coords.y)
                end
            else
                game.print(string.format("[DEBUG Entities._on_agent_entity_destroyed] Tick %d: WARNING - chunk_coords is nil, cannot create update entry", game.tick))
            end
            return
        else
            game.print(string.format("[DEBUG Entities._on_agent_entity_destroyed] Tick %d: NOT a resource entity, skipping resource handling", game.tick))
        end
    else
        game.print(string.format("[DEBUG Entities._on_agent_entity_destroyed] Tick %d: Condition not met - entity=%s, entity_name=%s, position=%s", 
            game.tick, entity and "valid" or "nil", tostring(entity_name), position and "valid" or "nil"))
    end
    
    -- Handle player-built entities (entity should be valid or we have entity info)
    if entity and entity.valid then
        M._delete_entity_snapshot(entity)
    elseif entity_name and position then
        -- Entity is destroyed but we have info - try to delete from snapshot
        -- Create a minimal entity-like object
        local fake_entity = {
            name = entity_name,
            position = position,
            valid = false,
        }
        M._delete_entity_snapshot(fake_entity)
    end
end

--- Handle agent entity rotated event (from Agent custom events)
--- Listens to Agent.on_agent_entity_rotated event
--- @param event table Event data with entity field
local function _on_agent_entity_rotated(event)
    local entity = event.entity
    if not (entity and entity.valid) then
        return
    end
    
    -- Get chunk coordinates
    local chunk_coords = utils.to_chunk_coordinates(entity.position)
    if not chunk_coords then
        return
    end
    
    -- Build entity key
    local ent_key = entity_key(entity.name or "unknown", entity.position.x, entity.position.y)
    
    -- Send UDP notification for rotation
    local chunk = { x = chunk_coords.x, y = chunk_coords.y }
    local payload = udp_payloads.entity_rotated(
        chunk,
        ent_key,
        entity.name or "unknown",
        entity.position,
        entity.direction,
        game.tick
    )
    udp_payloads.send_entity_operation(payload)
end

--- Handle agent entity configuration changed event (from Agent custom events)
--- Listens to Agent.on_agent_entity_configuration_changed event
--- @param event table Event data with entity field
local function _on_agent_entity_configuration_changed(event)
    local entity = event.entity
    if not (entity and entity.valid) then
        return
    end
    
    -- Serialize entity to get updated configuration
    local entity_data = serialize.serialize_entity(entity)
    if not entity_data then
        return
    end
    
    -- Get chunk coordinates
    local chunk_coords = utils.to_chunk_coordinates(entity.position)
    if not chunk_coords then
        return
    end
    
    -- Send UDP notification for configuration change
    local chunk = { x = chunk_coords.x, y = chunk_coords.y }
    local payload = udp_payloads.entity_configuration_changed(chunk, entity_data)
    udp_payloads.send_entity_operation(payload)
end

--- Build disk write snapshot events table
--- Called after init() to populate events
function M._build_disk_write_snapshot()
    -- Get Agent custom events from storage (preferred) or remote call (fallback)
    -- Storage is the source of truth for cross-mod event ID sharing
    local agent_events = nil
    
    game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: Starting to build disk_write_snapshot", game.tick))
    
    -- Try storage first (fastest, no remote call overhead)
    if storage.custom_events then
        agent_events = storage.custom_events
        game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: Found agent_events in storage", game.tick))
    -- Fallback to remote call if storage not available
    elseif remote and remote.interfaces then
        game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: storage.custom_events not found, checking remote interfaces", game.tick))
        if remote.interfaces.agent then
            game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: Found 'agent' remote interface, calling get_custom_events", game.tick))
            local ok, result = pcall(function()
                return remote.call("agent", "get_custom_events")
            end)
            if ok and result then
                agent_events = result
                game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: Got agent_events from remote interface", game.tick))
            else
                game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: Remote call failed - ok=%s", game.tick, tostring(ok)))
            end
        else
            game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: 'agent' remote interface not found", game.tick))
        end
        if not agent_events and remote.interfaces.custom_events then
            game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: Found 'custom_events' remote interface, calling get_custom_events", game.tick))
            local ok, result = pcall(function()
                return remote.call("custom_events", "get_custom_events")
            end)
            if ok and result then
                agent_events = result
                game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: Got agent_events from custom_events remote interface", game.tick))
            else
                game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: Remote call to custom_events failed - ok=%s", game.tick, tostring(ok)))
            end
        end
    -- Last resort: try module require (may not work across mods reliably)
    elseif Agents and Agents.custom_events then
        agent_events = Agents.custom_events
        game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: Got agent_events from Agents module", game.tick))
    else
        game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: No remote interfaces available, Agents.custom_events=%s", 
            game.tick, tostring(Agents and Agents.custom_events)))
    end
    
    local events = {
        -- In-game events
        [defines.events.on_built_entity] = _on_entity_built,
        [defines.events.script_raised_built] = _on_entity_built,
        [defines.events.on_player_mined_entity] = _on_entity_destroyed,  -- Player mines entity (trees, rocks, etc.)
        [defines.events.script_raised_destroy] = _on_entity_destroyed,
        [defines.events.on_entity_settings_pasted] = _on_entity_settings_pasted,
    }
    
    -- Add EntityInterface events (from fv_embodied_agent mod dependency)
    if EntityInterface.on_entity_configuration_changed then
        events[EntityInterface.on_entity_configuration_changed] = _on_entity_configuration_changed
    end
    if EntityInterface.on_entity_rotated then
        events[EntityInterface.on_entity_rotated] = _on_entity_rotated
    end
    
    -- Add Agent custom events if available (for agent-driven entity operations)
    if agent_events then
        game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: agent_events found, checking for custom events", game.tick))
        if agent_events.on_agent_entity_built then
            events[agent_events.on_agent_entity_built] = _on_agent_entity_built
            game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: Registered on_agent_entity_built, event_id=%s", 
                game.tick, tostring(agent_events.on_agent_entity_built)))
        end
        if agent_events.on_agent_entity_destroyed then
            events[agent_events.on_agent_entity_destroyed] = _on_agent_entity_destroyed
            game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: Registered handler for on_agent_entity_destroyed, event_id=%s", 
                game.tick, tostring(agent_events.on_agent_entity_destroyed)))
        else
            game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: WARNING: agent_events.on_agent_entity_destroyed is nil!", game.tick))
        end
        if agent_events.on_agent_entity_rotated then
            events[agent_events.on_agent_entity_rotated] = _on_agent_entity_rotated
            game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: Registered on_agent_entity_rotated, event_id=%s", 
                game.tick, tostring(agent_events.on_agent_entity_rotated)))
        end
        if agent_events.on_agent_entity_configuration_changed then
            events[agent_events.on_agent_entity_configuration_changed] = _on_agent_entity_configuration_changed
            game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: Registered on_agent_entity_configuration_changed, event_id=%s", 
                game.tick, tostring(agent_events.on_agent_entity_configuration_changed)))
        end
    else
        game.print(string.format("[DEBUG Entities._build_disk_write_snapshot] Tick %d: WARNING: agent_events is nil! Event handler will NOT be registered!", game.tick))
    end

    return {
        events = events,
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
