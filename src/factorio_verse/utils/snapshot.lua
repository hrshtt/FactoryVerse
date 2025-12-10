--- factorio_verse/utils/snapshot.lua
--- Shared utilities for snapshot file I/O operations
---
--- File Structure (JSONL-based):
---   chunks/{x}/{y}/
---   ├── resources_init.jsonl      # Ore tiles (written once per chunk)
---   ├── water_init.jsonl          # Water tiles (written once per chunk)
---   ├── trees_rocks_init.jsonl    # Trees and rocks (written once per chunk)
---   ├── entities_init.jsonl       # Player-placed entities snapshot
---   └── entities_updates.jsonl    # Append-only operations log
---
--- Operations Log Format (entities_updates.jsonl):
---   {"op": "upsert", "tick": 12345, "entity": {...full entity data...}}
---   {"op": "remove", "tick": 12346, "key": "inserter@5,10", "position": {x: 5, y: 10}, "name": "inserter"}

local utils = require("utils.utils")

local M = {}

-- Base directory for snapshots (relative to script-output)
M.SNAPSHOT_BASE_DIR = "factoryverse/snapshots"

-- UDP port for all notifications (action port as source of truth)
M.UDP_PORT = 34202

-- Debug flag for verbose logging
M.DEBUG = false

-- ============================================================================
-- FILE PATHS
-- ============================================================================

--- Generate chunk directory path
--- @param chunk_x number
--- @param chunk_y number
--- @return string - Path like "factoryverse/snapshots/{chunk_x}/{chunk_y}"
function M.chunk_dir_path(chunk_x, chunk_y)
    return M.SNAPSHOT_BASE_DIR .. "/" .. chunk_x .. "/" .. chunk_y
end

--- Generate path for entities init file (snapshot of all player-placed entities)
--- @param chunk_x number
--- @param chunk_y number
--- @return string
function M.entities_init_path(chunk_x, chunk_y)
    return M.chunk_dir_path(chunk_x, chunk_y) .. "/entities_init.jsonl"
end

--- Generate path for entities updates file (append-only operations log)
--- @param chunk_x number
--- @param chunk_y number
--- @return string
function M.entities_updates_path(chunk_x, chunk_y)
    return M.chunk_dir_path(chunk_x, chunk_y) .. "/entities_updates.jsonl"
end

--- Generate path for resources init file (ore tiles)
--- @param chunk_x number
--- @param chunk_y number
--- @return string
function M.resources_init_path(chunk_x, chunk_y)
    return M.chunk_dir_path(chunk_x, chunk_y) .. "/resources_init.jsonl"
end

--- Generate path for water init file
--- @param chunk_x number
--- @param chunk_y number
--- @return string
function M.water_init_path(chunk_x, chunk_y)
    return M.chunk_dir_path(chunk_x, chunk_y) .. "/water_init.jsonl"
end

--- Generate path for trees and rocks init file
--- @param chunk_x number
--- @param chunk_y number
--- @return string
function M.trees_rocks_init_path(chunk_x, chunk_y)
    return M.chunk_dir_path(chunk_x, chunk_y) .. "/trees_rocks_init.jsonl"
end

--- Generate path for ghosts init file (top-level, not chunk-wise)
--- @return string
function M.ghosts_init_path()
    return M.SNAPSHOT_BASE_DIR .. "/ghosts-init.jsonl"
end

--- Generate path for ghosts updates file (top-level, append-only operations log)
--- @return string
function M.ghosts_updates_path()
    return M.SNAPSHOT_BASE_DIR .. "/ghosts-updates.jsonl"
end

-- ============================================================================
-- JSONL INIT FILE WRITING (for initial snapshots)
-- ============================================================================

--- Write JSONL init file from pre-serialized JSON strings
--- This is the fast path - strings are already serialized, just concat and write
--- @param file_path string - Full path relative to script-output
--- @param json_lines table - Array of JSON strings (already serialized)
--- @return boolean - Success status
function M.write_jsonl_init(file_path, json_lines)
    if not file_path then
        return false
    end
    
    if not json_lines or #json_lines == 0 then
        -- Don't write empty files for init
        return true
    end
    
    local content = table.concat(json_lines, "\n") .. "\n"
    local ok_write = pcall(helpers.write_file, file_path, content, false)
    if not ok_write then
        log("Failed to write JSONL init file: " .. tostring(file_path))
        return false
    end
    
    if M.DEBUG and game and game.print then
        game.print(string.format("[snapshot] Wrote JSONL init: %s (%d entries)", file_path, #json_lines))
    end
    
    return true
end

--- Write JSONL init file from table data (serializes each entry)
--- @param file_path string - Full path relative to script-output
--- @param entries table - Array of table entries to serialize
--- @return boolean - Success status
function M.write_jsonl_init_from_tables(file_path, entries)
    if not file_path then
        return false
    end
    
    if not entries or #entries == 0 then
        return true
    end
    
    local lines = {}
    for _, entry in ipairs(entries) do
        local ok, json_str = pcall(helpers.table_to_json, entry)
        if ok and json_str then
            table.insert(lines, json_str)
        else
            log("Failed to serialize entry for: " .. tostring(file_path))
        end
    end
    
    return M.write_jsonl_init(file_path, lines)
end

-- ============================================================================
-- APPEND-ONLY OPERATIONS LOG (for event-driven updates)
-- ============================================================================

--- Append an operation to the updates log
--- This is the key function for event-driven updates - uses append mode
--- @param chunk_x number
--- @param chunk_y number
--- @param operation table - Operation record with {op, tick, ...}
--- @return boolean - Success status
function M.append_entity_operation(chunk_x, chunk_y, operation)
    if not chunk_x or not chunk_y or not operation then
        return false
    end
    
    local file_path = M.entities_updates_path(chunk_x, chunk_y)
    
    local ok, json_str = pcall(helpers.table_to_json, operation)
    if not ok or not json_str then
        log("Failed to serialize operation for append: " .. tostring(file_path))
        return false
    end
    
    -- CRITICAL: Use append=true for the third parameter
    local ok_write = pcall(helpers.write_file, file_path, json_str .. "\n", true)
    if not ok_write then
        log("Failed to append operation to: " .. tostring(file_path))
        return false
    end
    
    if M.DEBUG and game and game.print then
        game.print(string.format("[snapshot] Appended %s op to chunk (%d, %d)", 
            operation.op or "unknown", chunk_x, chunk_y))
    end
    
    return true
end

--- Create an upsert operation record
--- @param entity_data table - Full serialized entity data
--- @return table - Operation record
function M.make_upsert_operation(entity_data)
    return {
        op = "upsert",
        tick = game.tick,
        entity = entity_data,
    }
end

--- Create a remove operation record
--- @param entity_key string - Entity key (e.g., "inserter@5,10")
--- @param position table - {x, y}
--- @param entity_name string
--- @return table - Operation record
function M.make_remove_operation(entity_key, position, entity_name)
    return {
        op = "remove",
        tick = game.tick,
        key = entity_key,
        position = position,
        name = entity_name,
    }
end

--- Append a ghost operation to the top-level ghosts updates log
--- This is the key function for event-driven ghost updates - uses append mode
--- @param operation table - Operation record with {op, tick, ...}
--- @return boolean - Success status
function M.append_ghost_operation(operation)
    if not operation then
        return false
    end
    
    local file_path = M.ghosts_updates_path()
    
    local ok, json_str = pcall(helpers.table_to_json, operation)
    if not ok or not json_str then
        log("Failed to serialize ghost operation for append: " .. tostring(file_path))
        return false
    end
    
    -- CRITICAL: Use append=true for the third parameter
    local ok_write = pcall(helpers.write_file, file_path, json_str .. "\n", true)
    if not ok_write then
        log("Failed to append ghost operation to: " .. tostring(file_path))
        return false
    end
    
    if M.DEBUG and game and game.print then
        game.print(string.format("[snapshot] Appended ghost %s op", operation.op or "unknown"))
    end
    
    return true
end

--- Create a ghost upsert operation record
--- @param ghost_data table - Full serialized ghost data
--- @return table - Operation record
function M.make_ghost_upsert_operation(ghost_data)
    return {
        op = "upsert",
        tick = game.tick,
        ghost = ghost_data,
    }
end

--- Create a ghost remove operation record
--- @param ghost_key string - Ghost key (e.g., "inserter@5,10")
--- @param position table - {x, y}
--- @param ghost_name string - The entity name this ghost represents
--- @return table - Operation record
function M.make_ghost_remove_operation(ghost_key, position, ghost_name)
    return {
        op = "remove",
        tick = game.tick,
        key = ghost_key,
        position = position,
        ghost_name = ghost_name,
    }
end

-- ============================================================================
-- UDP NOTIFICATION HELPERS
-- ============================================================================

--- Send UDP notification with standardized error handling
--- @param payload table - Payload to send as JSON
--- @return boolean - Success status
function M.send_udp_notification(payload)
    if not payload then
        return false
    end

    local ok_json, json_str = pcall(helpers.table_to_json, payload)
    if not ok_json or not json_str then
        log("Failed to serialize UDP payload to JSON")
        return false
    end

    local ok_udp, err = pcall(function()
        helpers.send_udp(M.UDP_PORT, json_str)
    end)

    if not ok_udp then
        local error_msg = err or "unknown"
        log(string.format("[UDP] ERROR sending notification: %s", error_msg))
        if game and game.print then
            game.print(string.format("[UDP] ERROR: %s", error_msg))
        end
        return false
    end

    if M.DEBUG and game and game.print then
        local event_type = payload.event_type or "unknown"
        game.print(string.format("[snapshot] Sent UDP notification: %s (port %d)", event_type, M.UDP_PORT))
        game.print(string.format("[snapshot] Payload: %s", json_str))
    end

    return true
end

--- Send action completion UDP notification
--- @param payload table - Action completion payload
--- @return boolean - Success status
function M.send_action_completion_udp(payload)
    if not payload or not payload.action_id or not payload.agent_id or 
       not payload.action_type or not payload.success then
        log("Invalid action completion payload: missing required fields")
        return false
    end
    return M.send_udp_notification(payload)
end

--- Send entity operation UDP notification
--- Notifies external systems of entity upsert/remove operations
--- @param op_type string - "upsert" or "remove"
--- @param chunk_x number - Chunk X coordinate
--- @param chunk_y number - Chunk Y coordinate
--- @param entity_key string - Entity key (e.g., "inserter@5,10")
--- @param entity_name string - Entity name
--- @param position table - {x, y}
--- @param entity_data table|nil - Full entity data (for upsert only)
--- @return boolean - Success status
function M.send_entity_operation_udp(op_type, chunk_x, chunk_y, entity_key, entity_name, position, entity_data)
    if not op_type or not chunk_x or not chunk_y or not entity_key then
        log("Invalid entity operation payload: missing required fields")
        return false
    end

    local payload = {
        event_type = "entity_operation",
        op = op_type,
        chunk = { x = chunk_x, y = chunk_y },
        tick = game.tick,
        entity_key = entity_key,
        entity_name = entity_name,
        position = position and { x = utils.floor(position.x), y = utils.floor(position.y) } or nil,
    }
    
    -- Include full entity data for upsert operations
    if op_type == "upsert" and entity_data then
        payload.entity = entity_data
    end

    return M.send_udp_notification(payload)
end

--- Send chunk init complete UDP notification
--- Notifies external systems that a chunk's initial snapshot is complete
--- @param chunk_x number
--- @param chunk_y number
--- @param entity_count number - Number of entities in the chunk
--- @return boolean - Success status
function M.send_chunk_init_complete_udp(chunk_x, chunk_y, entity_count)
    local payload = {
        event_type = "chunk_init_complete",
        chunk = { x = chunk_x, y = chunk_y },
        tick = game.tick,
        entity_count = entity_count or 0,
    }
    return M.send_udp_notification(payload)
end

--- Send file event UDP notification
--- For notifying about init file writes (resources, water, trees_rocks)
--- @param event_type string - "file_created"
--- @param file_type string - "resource", "water", "trees_rocks", "entities_init"
--- @param chunk_x number
--- @param chunk_y number
--- @param file_path string|nil - Full file path (optional)
--- @return boolean - Success status
function M.send_file_event_udp(event_type, file_type, chunk_x, chunk_y, position, entity_name, component_type, file_path)
    if not event_type or not file_type or not chunk_x or not chunk_y then
        log("Invalid file event payload: missing required fields")
        return false
    end

    local payload = {
        event_type = event_type,
        file_type = file_type,
        chunk = { x = chunk_x, y = chunk_y },
        tick = game.tick,
    }

    if file_path then
        payload.file_path = file_path
    end

    return M.send_udp_notification(payload)
end

--- Send status snapshot UDP notification
--- @param status_records table - Map of entity_key -> status record
--- @return boolean - Success status
function M.send_status_snapshot_udp(status_records)
    if not status_records or next(status_records) == nil then
        return false
    end

    local payload = {
        event_type = "status_snapshot",
        tick = game.tick,
        status_records = status_records
    }

    return M.send_udp_notification(payload)
end

return M
