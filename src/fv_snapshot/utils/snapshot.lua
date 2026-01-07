--- factorio_verse/utils/snapshot.lua
--- Shared utilities for snapshot file I/O operations
---
--- File Naming Convention:
---   - {name}-init.jsonl   : Initial snapshot files (written once per chunk)
---   - {name}-updates.jsonl: Append-only operations log
---   - Use underscores within name (e.g., trees_rocks)
---
--- File Structure (JSONL-based):
---   chunks/{x}/{y}/
---   ├── resources-init.jsonl      # Ore tiles (written once per chunk)
---   ├── water-init.jsonl          # Water tiles (written once per chunk)
---   ├── trees_rocks-init.jsonl    # Trees and rocks (written once per chunk)
---   ├── entities-init.jsonl       # Player-placed entities snapshot
---   ├── entities-updates.jsonl    # Append-only operations log
---   ├── ghosts-init.jsonl         # Ghost entities (chunk-wise)
---   └── ghosts-updates.jsonl      # Ghost operations log
---
--- Operations Log Format (entities-updates.jsonl):
---   {"op": "upsert", "tick": 12345, "sequence": 1, "entity": {...full entity data...}}
---   {"op": "remove", "tick": 12346, "sequence": 2, "key": "inserter@5,10", "position": {x: 5, y: 10}, "name": "inserter"}
---
--- Sequence numbers enable deterministic recovery: replay updates in sequence order.

local utils = require("utils.utils")

local M = {}

-- Cache helpers functions for performance (called frequently in UDP notifications)
local table_to_json = helpers.table_to_json
local send_udp = helpers.send_udp

-- Base directory for snapshots (relative to script-output)
M.SNAPSHOT_BASE_DIR = "factoryverse/snapshots"

-- UDP port for snapshot notifications (separate from agent action ports)
-- This will be read from settings at runtime, with a fallback to 34400
M.UDP_PORT = 34400

-- Debug flag for verbose logging
M.DEBUG = false

--- Get the configured snapshot UDP port
--- Reads from mod settings if available, falls back to M.UDP_PORT
--- Can also be overridden via remote interface
--- @return number UDP port for snapshot notifications
function M.get_udp_port()
    -- Check if runtime override is set (via remote interface)
    if storage.snapshot_udp_port then
        return storage.snapshot_udp_port
    end
    
    -- Try to read from mod settings
    if settings and settings.global then
        local setting_value = settings.global["fv-snapshot-udp-port"]
        if setting_value and setting_value.value then
            return setting_value.value
        end
    end
    
    -- Fallback to default
    return M.UDP_PORT
end

--- Set the snapshot UDP port at runtime (via remote interface)
--- @param port number UDP port for snapshot notifications
function M.set_udp_port(port)
    if type(port) ~= "number" or port < 1024 or port > 65535 then
        error("Invalid UDP port: " .. tostring(port) .. ". Must be between 1024 and 65535.")
    end
    storage.snapshot_udp_port = port
    log(string.format("[snapshot] UDP port set to %d", port))
end

-- ============================================================================
-- SEQUENCE COUNTER (for deterministic recovery)
-- ============================================================================

--- Get next global sequence number.
--- Stored in storage for persistence across saves.
--- @return number - Next sequence number
function M.get_next_sequence()
    storage.snapshot_sequence = (storage.snapshot_sequence or 0) + 1
    return storage.snapshot_sequence
end

--- Get current sequence number without incrementing.
--- @return number - Current sequence number
function M.get_current_sequence()
    return storage.snapshot_sequence or 0
end

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
    return M.chunk_dir_path(chunk_x, chunk_y) .. "/entities-init.jsonl"
end

--- Generate path for entities updates file (append-only operations log)
--- @param chunk_x number
--- @param chunk_y number
--- @return string
function M.entities_updates_path(chunk_x, chunk_y)
    return M.chunk_dir_path(chunk_x, chunk_y) .. "/entities-updates.jsonl"
end

--- Generate path for resources init file (ore tiles)
--- @param chunk_x number
--- @param chunk_y number
--- @return string
function M.resources_init_path(chunk_x, chunk_y)
    return M.chunk_dir_path(chunk_x, chunk_y) .. "/resources-init.jsonl"
end

--- Generate path for water init file
--- @param chunk_x number
--- @param chunk_y number
--- @return string
function M.water_init_path(chunk_x, chunk_y)
    return M.chunk_dir_path(chunk_x, chunk_y) .. "/water-init.jsonl"
end

--- Generate path for trees and rocks init file
--- @param chunk_x number
--- @param chunk_y number
--- @return string
function M.trees_rocks_init_path(chunk_x, chunk_y)
    return M.chunk_dir_path(chunk_x, chunk_y) .. "/trees_rocks-init.jsonl"
end

--- Generate path for trees and rocks updates file (append-only operations log)
--- @param chunk_x number
--- @param chunk_y number
--- @return string
function M.trees_rocks_updates_path(chunk_x, chunk_y)
    return M.chunk_dir_path(chunk_x, chunk_y) .. "/trees_rocks-updates.jsonl"
end

--- Generate path for ghosts init file (chunk-wise, like entities)
--- @param chunk_x number
--- @param chunk_y number
--- @return string
function M.ghosts_init_path(chunk_x, chunk_y)
    return M.chunk_dir_path(chunk_x, chunk_y) .. "/ghosts-init.jsonl"
end

--- Generate path for ghosts updates file (chunk-wise, append-only operations log)
--- @param chunk_x number
--- @param chunk_y number
--- @return string
function M.ghosts_updates_path(chunk_x, chunk_y)
    return M.chunk_dir_path(chunk_x, chunk_y) .. "/ghosts-updates.jsonl"
end

--- Generate path for status dump file
--- @param tick number Game tick
--- @return string
function M.status_dump_path(tick)
    return "factoryverse/status/status-" .. tostring(tick) .. ".jsonl"
end

--- Generate path for resource file based on file type
--- Used when rewriting resource files after depletion
--- @param chunk_x number
--- @param chunk_y number
--- @param file_type string - "tiles", "water-tiles", or "entities"
--- @return string
function M.resource_file_path(chunk_x, chunk_y, file_type)
    if file_type == "tiles" then
        return M.resources_init_path(chunk_x, chunk_y)
    elseif file_type == "water-tiles" then
        return M.water_init_path(chunk_x, chunk_y)
    elseif file_type == "entities" then
        return M.trees_rocks_init_path(chunk_x, chunk_y)
    else
        log("Unknown resource file type: " .. tostring(file_type))
        return nil
    end
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
    local ok_write = helpers.write_file(file_path, content, false)
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
        local json_str = helpers.table_to_json(entry)
        if json_str then
            table.insert(lines, json_str)
        else
            log("Failed to serialize entry for: " .. tostring(file_path))
        end
    end
    
    return M.write_jsonl_init(file_path, lines)
end

--- Write resource file (overwrites existing file)
--- Used when rewriting resource files after depletion
--- @param file_path string - Full path relative to script-output
--- @param data table - Array of resource entries to serialize
--- @return boolean - Success status
function M.write_resource_file(file_path, data)
    if not file_path then
        return false
    end
    
    -- Use the existing write function which overwrites the file
    return M.write_jsonl_init_from_tables(file_path, data)
end

-- ============================================================================
-- CHUNK WRITE TRACKING (for handling first writes without append flag)
-- ============================================================================
-- Factorio's helpers.write_file() with append=true fails if the directory
-- doesn't exist. We track first writes per chunk to use append=false for
-- directory creation, then append=true for subsequent writes.

--- Check if this is the first entity update write for a chunk
--- Uses existing ChunkTracker infrastructure from Map.lua
--- @param chunk_x number
--- @param chunk_y number
--- @return boolean - true if this is the first write
local function is_first_entity_update_write(chunk_x, chunk_y)
    -- Access existing chunk tracker from Map module
    if not storage.chunk_tracker or not storage.chunk_tracker.chunk_lookup then
        return true  -- No tracker yet, definitely first write
    end
    
    local chunk_key = chunk_x .. "," .. chunk_y
    local chunk_entry = storage.chunk_tracker.chunk_lookup[chunk_key]
    
    if not chunk_entry then
        return true  -- Chunk not tracked yet, first write
    end
    
    -- Check if entity_updates_written flag exists
    return chunk_entry.entity_updates_written ~= true
end

--- Mark chunk as having had its first entity update write
--- @param chunk_x number
--- @param chunk_y number
local function mark_entity_update_written(chunk_x, chunk_y)
    -- Ensure chunk tracker exists
    if not storage.chunk_tracker then
        storage.chunk_tracker = { chunk_lookup = {} }
    end
    if not storage.chunk_tracker.chunk_lookup then
        storage.chunk_tracker.chunk_lookup = {}
    end
    
    local chunk_key = chunk_x .. "," .. chunk_y
    local chunk_entry = storage.chunk_tracker.chunk_lookup[chunk_key]
    
    if not chunk_entry then
        -- Create minimal chunk entry if it doesn't exist
        chunk_entry = {
            resource = {},
            entities = {},
            water = false,
            snapshot_tick = nil,
            dirty = false,
            has_player_entities = false,
            player_entity_count = 0,
            entity_updates_written = true,  -- NEW FLAG
        }
        storage.chunk_tracker.chunk_lookup[chunk_key] = chunk_entry
    else
        -- Mark existing entry
        chunk_entry.entity_updates_written = true
    end
end

--- Check if this is the first trees/rocks update write for a chunk
--- @param chunk_x number
--- @param chunk_y number
--- @return boolean - true if this is the first write
local function is_first_trees_rocks_update_write(chunk_x, chunk_y)
    if not storage.chunk_tracker or not storage.chunk_tracker.chunk_lookup then
        return true
    end
    
    local chunk_key = chunk_x .. "," .. chunk_y
    local chunk_entry = storage.chunk_tracker.chunk_lookup[chunk_key]
    
    if not chunk_entry then
        return true
    end
    
    return chunk_entry.trees_rocks_updates_written ~= true
end

--- Mark chunk as having had its first trees/rocks update write
--- @param chunk_x number
--- @param chunk_y number
local function mark_trees_rocks_update_written(chunk_x, chunk_y)
    if not storage.chunk_tracker then
        storage.chunk_tracker = { chunk_lookup = {} }
    end
    if not storage.chunk_tracker.chunk_lookup then
        storage.chunk_tracker.chunk_lookup = {}
    end
    
    local chunk_key = chunk_x .. "," .. chunk_y
    local chunk_entry = storage.chunk_tracker.chunk_lookup[chunk_key]
    
    if not chunk_entry then
        chunk_entry = {
            resource = {},
            entities = {},
            water = false,
            snapshot_tick = nil,
            dirty = false,
            has_player_entities = false,
            player_entity_count = 0,
            trees_rocks_updates_written = true,  -- NEW FLAG
        }
        storage.chunk_tracker.chunk_lookup[chunk_key] = chunk_entry
    else
        chunk_entry.trees_rocks_updates_written = true
    end
end

--- Check if this is the first ghost update write for a chunk
--- @param chunk_x number
--- @param chunk_y number
--- @return boolean - true if this is the first write
local function is_first_ghost_update_write(chunk_x, chunk_y)
    if not storage.chunk_tracker or not storage.chunk_tracker.chunk_lookup then
        return true
    end
    
    local chunk_key = chunk_x .. "," .. chunk_y
    local chunk_entry = storage.chunk_tracker.chunk_lookup[chunk_key]
    
    if not chunk_entry then
        return true
    end
    
    return chunk_entry.ghost_updates_written ~= true
end

--- Mark chunk as having had its first ghost update write
--- @param chunk_x number
--- @param chunk_y number
local function mark_ghost_update_written(chunk_x, chunk_y)
    if not storage.chunk_tracker then
        storage.chunk_tracker = { chunk_lookup = {} }
    end
    if not storage.chunk_tracker.chunk_lookup then
        storage.chunk_tracker.chunk_lookup = {}
    end
    
    local chunk_key = chunk_x .. "," .. chunk_y
    local chunk_entry = storage.chunk_tracker.chunk_lookup[chunk_key]
    
    if not chunk_entry then
        -- Create minimal entry for tracking
        storage.chunk_tracker.chunk_lookup[chunk_key] = {
            x = chunk_x,
            y = chunk_y,
            ghost_updates_written = true,
        }
    else
        chunk_entry.ghost_updates_written = true
    end
end

-- ============================================================================
-- APPEND-ONLY OPERATIONS LOG (for event-driven updates)
-- ============================================================================

--- Append an operation to the updates log
--- This is the key function for event-driven updates - uses append mode
--- IMPORTANT: First write uses append=false to create directory structure
--- NOTE: Does NOT send UDP - caller is responsible for UDP notifications
--- @param chunk_x number
--- @param chunk_y number
--- @param operation table - Operation record with {op, tick, ...}
function M.append_entity_operation(chunk_x, chunk_y, operation)
    if not chunk_x or not chunk_y or not operation then
        return
    end
    
    local file_path = M.entities_updates_path(chunk_x, chunk_y)
    
    local json_str = helpers.table_to_json(operation)
    if not json_str then
        log("Failed to serialize operation for append: " .. tostring(file_path))
        return
    end
    
    -- Check if this is the first write - if so, use append=false to create directory
    local is_first_write = is_first_entity_update_write(chunk_x, chunk_y)
    local append_mode = not is_first_write
    
    -- Write to disk (return value ignored for determinism)
    helpers.write_file(file_path, json_str .. "\n", append_mode)
    
    -- Mark chunk as written
    if is_first_write then
        mark_entity_update_written(chunk_x, chunk_y)
    end
    
    if M.DEBUG and game and game.print then
        game.print(string.format("[snapshot] Wrote %s op to chunk (%d, %d) [first_write=%s, append=%s]", 
            operation.op or "unknown", chunk_x, chunk_y, tostring(is_first_write), tostring(append_mode)))
    end
end

--- Create an upsert operation record
--- @param entity_data table - Full serialized entity data
--- @return table - Operation record
function M.make_upsert_operation(entity_data)
    return {
        op = "upsert",
        tick = game.tick,
        sequence = M.get_next_sequence(),
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
        sequence = M.get_next_sequence(),
        key = entity_key,
        position = position,
        name = entity_name,
    }
end

--- Append a trees/rocks operation to the trees_rocks updates log
--- This is the key function for event-driven trees/rocks updates - uses append mode
--- IMPORTANT: First write uses append=false to create directory structure
--- NOTE: Does NOT send UDP - caller is responsible for UDP notifications
--- @param chunk_x number
--- @param chunk_y number
--- @param operation table - Operation record with {op, tick, ...}
function M.append_trees_rocks_operation(chunk_x, chunk_y, operation)
    if not chunk_x or not chunk_y or not operation then
        if M.DEBUG and game and game.print then
            game.print(string.format("[DEBUG snapshot.append_trees_rocks_operation] Tick %d: Missing params", game.tick))
        end
        return
    end
    
    local file_path = M.trees_rocks_updates_path(chunk_x, chunk_y)
    
    if M.DEBUG and game and game.print then
        game.print(string.format("[DEBUG snapshot.append_trees_rocks_operation] Tick %d: file_path=%s, chunk=(%d,%d)", 
            game.tick, file_path, chunk_x, chunk_y))
    end
    
    local json_str = helpers.table_to_json(operation)
    if not json_str then
        if M.DEBUG and game and game.print then
            game.print(string.format("[DEBUG snapshot.append_trees_rocks_operation] Tick %d: Serialization failed", game.tick))
        end
        log("Failed to serialize trees/rocks operation for append: " .. tostring(file_path))
        return
    end
    
    if M.DEBUG and game and game.print then
        game.print(string.format("[DEBUG snapshot.append_trees_rocks_operation] Tick %d: Serialized operation (length=%d): %s", 
            game.tick, string.len(json_str), json_str))
    end
    
    -- Check if this is the first write - if so, use append=false to create directory
    local is_first_write = is_first_trees_rocks_update_write(chunk_x, chunk_y)
    local append_mode = not is_first_write
    
    -- Write to disk (return value ignored for determinism)
    helpers.write_file(file_path, json_str .. "\n", append_mode)
    
    -- Mark chunk as written
    if is_first_write then
        mark_trees_rocks_update_written(chunk_x, chunk_y)
    end
    
    if M.DEBUG and game and game.print then
        game.print(string.format("[DEBUG snapshot.append_trees_rocks_operation] Tick %d: Wrote %s op to trees_rocks-update for chunk (%d, %d) [first_write=%s, append=%s]", 
            game.tick, operation.op or "unknown", chunk_x, chunk_y, tostring(is_first_write), tostring(append_mode)))
    end
end

--- Append a ghost operation to the chunk-wise ghosts updates log
--- This is the key function for event-driven ghost updates - uses append mode
--- IMPORTANT: First write uses append=false to create directory structure
--- NOTE: Does NOT send UDP - caller is responsible for UDP notifications
--- @param chunk_x number - Chunk X coordinate
--- @param chunk_y number - Chunk Y coordinate
--- @param operation table - Operation record with {op, tick, ...}
function M.append_ghost_operation(chunk_x, chunk_y, operation)
    if not operation then
        return
    end
    
    local file_path = M.ghosts_updates_path(chunk_x, chunk_y)
    
    local json_str = helpers.table_to_json(operation)
    if not json_str then
        log("Failed to serialize ghost operation for append: " .. tostring(file_path))
        return
    end
    
    -- Check if this is the first write for this chunk
    local is_first_write = is_first_ghost_update_write(chunk_x, chunk_y)
    local append_mode = not is_first_write
    
    -- Write to disk (return value ignored for determinism)
    helpers.write_file(file_path, json_str .. "\n", append_mode)
    
    -- Mark chunk ghosts as written
    if is_first_write then
        mark_ghost_update_written(chunk_x, chunk_y)
    end
    
    if M.DEBUG and game and game.print then
        game.print(string.format("[snapshot] Wrote ghost %s op to chunk (%d, %d) [first_write=%s, append=%s]", 
            operation.op or "unknown", chunk_x, chunk_y, tostring(is_first_write), tostring(append_mode)))
    end
end

--- Create a ghost upsert operation record
--- @param ghost_data table - Full serialized ghost data
--- @return table - Operation record
function M.make_ghost_upsert_operation(ghost_data)
    return {
        op = "upsert",
        tick = game.tick,
        sequence = M.get_next_sequence(),
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
        sequence = M.get_next_sequence(),
        key = ghost_key,
        position = position,
        ghost_name = ghost_name,
    }
end

--- Create a rotate operation record
--- @param entity_key string - Entity key (e.g., "inserter@5,10")
--- @param position table - {x, y}
--- @param direction number|string - Direction
--- @param entity_name string
--- @return table - Operation record
function M.make_rotate_operation(entity_key, position, direction, entity_name)
    local direction_name = utils.direction_to_name(direction and tonumber(tostring(direction)) or nil)
    return {
        op = "rotated",
        tick = game.tick,
        sequence = M.get_next_sequence(),
        key = entity_key,
        position = position,
        direction = direction,
        direction_name = direction_name,
        name = entity_name,
    }
end

--- Create a ghost rotate operation record
--- @param ghost_key string - Ghost key (e.g., "inserter@5,10")
--- @param position table - {x, y}
--- @param direction number|string - Direction
--- @param ghost_name string - The entity name this ghost represents
--- @return table - Operation record
function M.make_ghost_rotate_operation(ghost_key, position, direction, ghost_name)
    local direction_name = utils.direction_to_name(direction and tonumber(tostring(direction)) or nil)
    return {
        op = "rotated",
        tick = game.tick,
        sequence = M.get_next_sequence(),
        key = ghost_key,
        position = position,
        direction = direction,
        direction_name = direction_name,
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

    local json_str = table_to_json(payload)
    if not json_str then
        log("Failed to serialize UDP payload to JSON")
        return false
    end

    -- UDP is fire-and-forget - send_udp doesn't return success/failure
    -- Note: Requires --enable-lua-udp flag to be set when launching Factorio
    local udp_port = M.get_udp_port()
    send_udp(udp_port, json_str)

    if M.DEBUG and game and game.print then
        local event_type = payload.event_type or "unknown"
        game.print(string.format("[snapshot] Sent UDP notification: %s (port %d)", event_type, udp_port))
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
        sequence = M.get_current_sequence(),  -- Include current sequence for UDP sync
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

-- ============================================================================
-- STATUS DUMP FILE MANAGEMENT
-- ============================================================================

--- Maximum number of status dump files to keep on disk
M.MAX_STATUS_DUMP_FILES = 100

--- Track a status dump file in storage
--- @param tick number Game tick
function M.track_status_dump_file(tick)
    storage.status_dump_files = storage.status_dump_files or {}
    table.insert(storage.status_dump_files, tick)
end

--- Cleanup old status dump files, keeping only the most recent MAX_STATUS_DUMP_FILES
function M.cleanup_old_status_dumps()
    storage.status_dump_files = storage.status_dump_files or {}
    
    -- Sort by tick (ascending)
    table.sort(storage.status_dump_files)
    
    -- Remove oldest files if we exceed the limit
    while #storage.status_dump_files > M.MAX_STATUS_DUMP_FILES do
        local oldest_tick = table.remove(storage.status_dump_files, 1)
        local file_path = M.status_dump_path(oldest_tick)
        
        -- Delete the file (best-effort, ignore errors)
        helpers.remove_path(file_path)
        
        if M.DEBUG and game and game.print then
            game.print(string.format("[status_dump] Deleted old status dump: %s", file_path))
        end
    end
end

-- ============================================================================
-- REMOTE INTERFACE
-- ============================================================================

--- Register remote interface for snapshot utilities
--- Provides methods to configure snapshot behavior at runtime
function M.register_remote_interface()
    return {
        --- Set the UDP port for snapshot notifications
        --- @param port number UDP port (1024-65535)
        set_udp_port = function(port)
            M.set_udp_port(port)
            return {success = true, port = port}
        end,
        
        --- Get the current UDP port for snapshot notifications
        --- @return number Current UDP port
        get_udp_port = function()
            return M.get_udp_port()
        end,
    }
end

return M
