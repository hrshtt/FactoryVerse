--- factorio_verse/utils/snapshot.lua
--- Shared utilities for snapshot file I/O operations
--- Handles path generation, file writing, and file deletion for entity and resource snapshots

local utils = require("utils.utils")

local M = {}

-- Base directory for snapshots (relative to script-output)
M.SNAPSHOT_BASE_DIR = "factoryverse/snapshots"

-- UDP port for all notifications (action port as source of truth)
M.UDP_PORT = 34202

-- Debug flag for verbose logging
M.DEBUG = true

--- Generate chunk directory path
--- @param chunk_x number
--- @param chunk_y number
--- @return string - Path like "factoryverse/snapshots/{chunk_x}/{chunk_y}"
function M.chunk_dir_path(chunk_x, chunk_y)
    return M.SNAPSHOT_BASE_DIR .. "/" .. chunk_x .. "/" .. chunk_y
end

--- Generate entity file path
--- Format: {chunk_x}/{chunk_y}/{component_type}/{pos_x}_{pos_y}_{entity_name}.json
--- @param chunk_x number
--- @param chunk_y number
--- @param component_type string - "entity", "belt", "pipe", or "pole"
--- @param position table - {x: number, y: number}
--- @param entity_name string
--- @return string - Full file path
function M.entity_file_path(chunk_x, chunk_y, component_type, position, entity_name)
    local pos_x = utils.floor(position.x)
    local pos_y = utils.floor(position.y)
    local filename = pos_x .. "_" .. pos_y .. "_" .. entity_name .. ".json"
    return M.chunk_dir_path(chunk_x, chunk_y) .. "/" .. component_type .. "/" .. filename
end

--- Generate resource file path
--- Format: {chunk_x}/{chunk_y}/resources/{filename}.jsonl
--- @param chunk_x number
--- @param chunk_y number
--- @param filename string - "resources", "water", or "trees"
--- @return string - Full file path
function M.resource_file_path(chunk_x, chunk_y, filename)
    return M.chunk_dir_path(chunk_x, chunk_y) .. "/resources/" .. filename .. ".jsonl"
end

--- Write entity data to disk as JSON
--- @param file_path string - Full path relative to script-output
--- @param entity_data table - Serialized entity data
--- @return boolean - Success status
function M.write_entity_file(file_path, entity_data)
    if not file_path or not entity_data then
        return false
    end

    local ok, json_str = pcall(helpers.table_to_json, entity_data)
    if not ok or not json_str then
        log("Failed to serialize entity data to JSON: " .. tostring(file_path))
        return false
    end

    local ok_write = pcall(helpers.write_file, file_path, json_str, false)
    if not ok_write then
        log("Failed to write entity file: " .. tostring(file_path))
        return false
    end

    if M.DEBUG and game and game.print then
        game.print(string.format("[snapshot] Wrote entity file: %s", file_path))
    end

    return true
end

--- Delete entity file from disk
--- @param file_path string - Full path relative to script-output
--- @return boolean - Success status
function M.delete_entity_file(file_path)
    if not file_path then
        return false
    end

    local ok = pcall(helpers.remove_path, file_path)
    if not ok then
        log("Failed to delete entity file: " .. tostring(file_path))
        return false
    end

    if M.DEBUG and game and game.print then
        game.print(string.format("[snapshot] Deleted entity file: %s", file_path))
    end

    return true
end

--- Write resource data to disk as JSONL (JSON Lines)
--- Each entry is written as a single line of JSON
--- @param file_path string - Full path relative to script-output
--- @param resources table - Array of resource entries
--- @return boolean - Success status
function M.write_resource_file(file_path, resources)
    if not file_path or not resources then
        return false
    end

    local lines = {}
    for _, resource in ipairs(resources) do
        local ok, json_str = pcall(helpers.table_to_json, resource)
        if ok and json_str then
            table.insert(lines, json_str)
        else
            log("Failed to serialize resource entry for: " .. tostring(file_path))
        end
    end

    if #lines == 0 then
        -- Write empty file if no resources
        local ok_write = pcall(helpers.write_file, file_path, "", false)
        if M.DEBUG and game and game.print then
            game.print(string.format("[snapshot] Wrote empty resource file: %s", file_path))
        end
        return ok_write
    end

    local content = table.concat(lines, "\n") .. "\n"
    local ok_write = pcall(helpers.write_file, file_path, content, false)
    if not ok_write then
        log("Failed to write resource file: " .. tostring(file_path))
        return false
    end

    if M.DEBUG and game and game.print then
        game.print(string.format("[snapshot] Wrote resource file: %s (%d entries)", file_path, #lines))
    end

    return true
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
    end

    return true
end

--- Send action completion UDP notification
--- Standardized format for async action completions
--- @param payload table - Action completion payload with required fields:
---   - action_id (string)
---   - agent_id (number|string)
---   - action_type (string)
---   - rcon_tick (number)
---   - completion_tick (number)
---   - success (boolean)
---   - result (table)
---   - cancelled (boolean, optional)
--- @return boolean - Success status
function M.send_action_completion_udp(payload)
    -- Validate required fields
    if not payload or not payload.action_id or not payload.agent_id or 
       not payload.action_type or not payload.success then
        log("Invalid action completion payload: missing required fields")
        return false
    end

    return M.send_udp_notification(payload)
end

--- Send file event UDP notification
--- Notifies external systems of file create/update/delete events
--- @param event_type string - "file_created", "file_updated", or "file_deleted"
--- @param file_type string - "entity", "resource", "water", or "trees"
--- @param chunk_x number - Chunk X coordinate
--- @param chunk_y number - Chunk Y coordinate
--- @param position table|nil - Entity position {x, y} (for entities)
--- @param entity_name string|nil - Entity name (for entities)
--- @param component_type string|nil - Component type like "belts", "pipes" (for entities)
--- @param file_path string|nil - Full file path (optional, for debugging)
--- @return boolean - Success status
function M.send_file_event_udp(event_type, file_type, chunk_x, chunk_y, position, entity_name, component_type, file_path)
    if not event_type or not file_type or not chunk_x or not chunk_y then
        log("Invalid file event payload: missing required fields")
        if M.DEBUG and game and game.print then
            game.print(string.format("[snapshot] ERROR: Invalid file event payload - event_type=%s, file_type=%s, chunk_x=%s, chunk_y=%s", 
                tostring(event_type), tostring(file_type), tostring(chunk_x), tostring(chunk_y)))
        end
        return false
    end

    local payload = {
        event_type = event_type,
        file_type = file_type,
        chunk = { x = chunk_x, y = chunk_y },
        tick = game.tick
    }

    -- Add entity-specific fields if provided
    if position then
        payload.position = { x = utils.floor(position.x), y = utils.floor(position.y) }
    end
    if entity_name then
        payload.entity_name = entity_name
    end
    if component_type then
        payload.component_type = component_type
    end
    if file_path then
        payload.file_path = file_path
    end

    return M.send_udp_notification(payload)
end

--- Send status snapshot UDP notification
--- Standardized format for entity status snapshots
--- @param status_records table - Map of unit_number -> status record
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

