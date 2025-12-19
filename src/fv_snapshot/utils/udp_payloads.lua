--- UDP payload creation module
--- Centralized payload creation with consistent API schema for external DB sync
--- All payloads follow a consistent structure for Python GameDataSyncService

local snapshot = require("utils/snapshot")

local M = {}

-- ============================================================================
-- PAYLOAD SCHEMA CONSTANTS
-- ============================================================================

-- Action status values
M.ACTION_STATUS = {
    STARTED = "started",
    PROGRESS = "progress",
    COMPLETED = "completed",
    CANCELLED = "cancelled",
    QUEUED = "queued",
}

-- Snapshot state values
M.SNAPSHOT_STATE = {
    IDLE = "IDLE",
    FIND_ENTITIES = "FIND_ENTITIES",
    SERIALIZE = "SERIALIZE",
    WRITE = "WRITE",
    COMPLETE = "COMPLETE",
}

-- Entity operation types
M.ENTITY_OP = {
    CREATED = "created",
    DESTROYED = "destroyed",
    ROTATED = "rotated",
    CONFIGURATION_CHANGED = "configuration_changed",
}

-- File IO operation types
M.FILE_OP = {
    WRITTEN = "written",      -- Overwrite operation
    APPENDED = "appended",    -- Append-only operation
}

-- ============================================================================
-- ACTION PAYLOADS
-- ============================================================================

--- Create action start payload
--- @param action_id string Action ID
--- @param agent_id number Agent ID
--- @param action_type string Action type (e.g., "walk_to", "mine_resource")
--- @param rcon_tick number|nil RCON tick (default: game.tick)
--- @return table Payload
function M.action_start(action_id, agent_id, action_type, rcon_tick)
    local current_tick = game.tick
    return {
        event_type = "action",
        action_id = action_id,
        agent_id = agent_id,
        action_type = action_type,
        status = M.ACTION_STATUS.STARTED,
        rcon_tick = rcon_tick or current_tick,
        tick = current_tick,
    }
end

--- Create action progress payload
--- @param action_id string Action ID
--- @param agent_id number Agent ID
--- @param action_type string Action type
--- @param progress_data table Progress data
--- @param rcon_tick number|nil RCON tick
--- @return table Payload
function M.action_progress(action_id, agent_id, action_type, progress_data, rcon_tick)
    local current_tick = game.tick
    return {
        event_type = "action",
        action_id = action_id,
        agent_id = agent_id,
        action_type = action_type,
        status = M.ACTION_STATUS.PROGRESS,
        rcon_tick = rcon_tick or current_tick,
        tick = current_tick,
        progress = progress_data or {},
    }
end

--- Create action completed payload
--- @param action_id string Action ID
--- @param agent_id number Agent ID
--- @param action_type string Action type
--- @param result table Result data
--- @param rcon_tick number|nil RCON tick
--- @param success boolean|nil Success flag (default: true)
--- @return table Payload
function M.action_completed(action_id, agent_id, action_type, result, rcon_tick, success)
    local current_tick = game.tick
    return {
        event_type = "action",
        action_id = action_id,
        agent_id = agent_id,
        action_type = action_type,
        status = M.ACTION_STATUS.COMPLETED,
        rcon_tick = rcon_tick or current_tick,
        completion_tick = current_tick,
        success = success ~= false,
        result = result or {},
    }
end

--- Create action cancelled payload
--- @param action_id string Action ID
--- @param agent_id number Agent ID
--- @param action_type string Action type
--- @param reason string|nil Cancellation reason
--- @param rcon_tick number|nil RCON tick
--- @return table Payload
function M.action_cancelled(action_id, agent_id, action_type, reason, rcon_tick)
    return {
        event_type = "action",
        action_id = action_id,
        agent_id = agent_id,
        action_type = action_type,
        status = M.ACTION_STATUS.CANCELLED,
        rcon_tick = rcon_tick or game.tick,
        cancellation_tick = game.tick,
        cancelled = true,
        reason = reason,
    }
end

--- Create action queued payload (for backward compatibility)
--- @param action_id string Action ID
--- @param agent_id number Agent ID
--- @param action_type string Action type
--- @param rcon_tick number|nil RCON tick
--- @return table Payload
function M.action_queued(action_id, agent_id, action_type, rcon_tick)
    return {
        event_type = "action",
        action_id = action_id,
        agent_id = agent_id,
        action_type = action_type,
        status = M.ACTION_STATUS.QUEUED,
        rcon_tick = rcon_tick or game.tick,
        tick = game.tick,
    }
end

-- ============================================================================
-- SNAPSHOT STATE PAYLOADS
-- ============================================================================

--- Create snapshot state payload
--- @param state string Snapshot state (IDLE, FIND_ENTITIES, SERIALIZE, WRITE, COMPLETE)
--- @param chunk table|nil Chunk coordinates {x, y} (nil for IDLE)
--- @param tick number|nil Game tick (default: game.tick)
--- @param progress table|nil Progress metrics {entities_processed, files_written, ...}
--- @return table Payload
function M.snapshot_state(state, chunk, tick, progress)
    local payload = {
        event_type = "snapshot_state",
        state = state,
        tick = tick or game.tick,
    }
    
    if chunk then
        payload.chunk = { x = chunk.x, y = chunk.y }
    end
    
    if progress then
        payload.progress = progress
    end
    
    return payload
end

-- ============================================================================
-- ENTITY OPERATION PAYLOADS
-- ============================================================================

--- Create entity created payload
--- @param chunk table Chunk coordinates {x, y}
--- @param entity_data table Full entity data
--- @param tick number|nil Game tick (default: game.tick)
--- @return table Payload
function M.entity_created(chunk, entity_data, tick)
    return {
        event_type = "entity_operation",
        op = M.ENTITY_OP.CREATED,
        chunk = { x = chunk.x, y = chunk.y },
        tick = tick or game.tick,
        entity_key = entity_data.key,
        entity_name = entity_data.name or "unknown",
        position = entity_data.position and { x = entity_data.position.x, y = entity_data.position.y } or nil,
        entity = entity_data,
    }
end

--- Create entity destroyed payload
--- @param chunk table Chunk coordinates {x, y}
--- @param entity_key string Entity key
--- @param entity_name string Entity name
--- @param position table Position {x, y}
--- @param tick number|nil Game tick (default: game.tick)
--- @return table Payload
function M.entity_destroyed(chunk, entity_key, entity_name, position, tick)
    return {
        event_type = "entity_operation",
        op = M.ENTITY_OP.DESTROYED,
        chunk = { x = chunk.x, y = chunk.y },
        tick = tick or game.tick,
        entity_key = entity_key,
        entity_name = entity_name,
        position = position and { x = position.x, y = position.y } or nil,
    }
end

--- Create entity rotated payload
--- @param chunk table Chunk coordinates {x, y}
--- @param entity_key string Entity key
--- @param entity_name string Entity name
--- @param position table Position {x, y}
--- @param direction number|string Direction
--- @param tick number|nil Game tick (default: game.tick)
--- @return table Payload
function M.entity_rotated(chunk, entity_key, entity_name, position, direction, tick)
    return {
        event_type = "entity_operation",
        op = M.ENTITY_OP.ROTATED,
        chunk = { x = chunk.x, y = chunk.y },
        tick = tick or game.tick,
        entity_key = entity_key,
        entity_name = entity_name,
        position = position and { x = position.x, y = position.y } or nil,
        direction = direction,
    }
end

--- Create entity configuration changed payload
--- @param chunk table Chunk coordinates {x, y}
--- @param entity_data table Full entity data (with updated configuration)
--- @param tick number|nil Game tick (default: game.tick)
--- @return table Payload
function M.entity_configuration_changed(chunk, entity_data, tick)
    return {
        event_type = "entity_operation",
        op = M.ENTITY_OP.CONFIGURATION_CHANGED,
        chunk = { x = chunk.x, y = chunk.y },
        tick = tick or game.tick,
        entity_key = entity_data.key,
        entity_name = entity_data.name or "unknown",
        position = entity_data.position and { x = entity_data.position.x, y = entity_data.position.y } or nil,
        entity = entity_data,
    }
end

-- ============================================================================
-- FILE IO PAYLOADS
-- ============================================================================

--- Create file written payload (overwrite operation)
--- @param file_type string File type (e.g., "resource", "water", "entities_init")
--- @param chunk table|nil Chunk coordinates {x, y} (nil for top-level files)
--- @param file_path string File path
--- @param tick number|nil Game tick (default: game.tick)
--- @param entry_count number|nil Number of entries written
--- @return table Payload
function M.file_written(file_type, chunk, file_path, tick, entry_count)
    local payload = {
        event_type = "file_io",
        operation = M.FILE_OP.WRITTEN,
        file_type = file_type,
        file_path = file_path,
        tick = tick or game.tick,
    }
    
    if chunk then
        payload.chunk = { x = chunk.x, y = chunk.y }
    end
    
    if entry_count then
        payload.entry_count = entry_count
    end
    
    return payload
end

--- Create file appended payload (append-only operation)
--- @param file_type string File type (e.g., "entities_updates", "status", "power_stats")
--- @param chunk table|nil Chunk coordinates {x, y} (nil for top-level files)
--- @param file_path string File path
--- @param tick number|nil Game tick (default: game.tick)
--- @param entry_count number|nil Number of entries appended
--- @return table Payload
function M.file_appended(file_type, chunk, file_path, tick, entry_count)
    local payload = {
        event_type = "file_io",
        operation = M.FILE_OP.APPENDED,
        file_type = file_type,
        file_path = file_path,
        tick = tick or game.tick,
    }
    
    if chunk then
        payload.chunk = { x = chunk.x, y = chunk.y }
    end
    
    if entry_count then
        payload.entry_count = entry_count
    end
    
    return payload
end

-- ============================================================================
-- EVENT PAYLOADS
-- ============================================================================

--- Create system phase changed payload
--- @param phase string New phase ("INITIAL_SNAPSHOTTING" or "MAINTENANCE")
--- @param stats table|nil System statistics {chunks_snapshotted, chunks_pending, ...}
--- @param tick number|nil Game tick (default: game.tick)
--- @return table Payload
function M.system_phase_changed(phase, stats, tick)
    local payload = {
        event_type = "system_phase_changed",
        phase = phase,
        tick = tick or game.tick,
    }
    
    if stats then
        payload.stats = stats
    end
    
    return payload
end

--- Create chunk charted payload
--- @param chunk table Chunk coordinates {x, y}
--- @param tick number|nil Game tick (default: game.tick)
--- @param charted_by string|nil "player" or "agent" (default: "player")
--- @param snapshot_queued boolean|nil Whether snapshot is queued (default: true)
--- @return table Payload
function M.chunk_charted(chunk, tick, charted_by, snapshot_queued)
    return {
        event_type = "chunk_charted",
        chunk = { x = chunk.x, y = chunk.y },
        tick = tick or game.tick,
        charted_by = charted_by or "player",
        snapshot_queued = snapshot_queued ~= false,
    }
end

--- Create chunk init complete payload
--- @param chunk table Chunk coordinates {x, y}
--- @param entity_count number|nil Number of entities in chunk
--- @param tick number|nil Game tick (default: game.tick)
--- @return table Payload
function M.chunk_init_complete(chunk, entity_count, tick)
    return {
        event_type = "chunk_init_complete",
        chunk = { x = chunk.x, y = chunk.y },
        tick = tick or game.tick,
        entity_count = entity_count or 0,
    }
end

-- ============================================================================
-- SEND HELPERS
-- ============================================================================

-- ============================================================================
-- SEQUENCE COUNTER (for reliable UDP delivery tracking)
-- ============================================================================

--- Get and increment global sequence counter
--- @return number Current sequence number
local function get_next_sequence()
    storage.udp_sequence = storage.udp_sequence or 0
    local seq = storage.udp_sequence
    storage.udp_sequence = storage.udp_sequence + 1
    return seq
end

--- Add sequence number to payload before sending
--- @param payload table Payload to add sequence to
--- @return table Payload with sequence number added
local function add_sequence(payload)
    payload.sequence = get_next_sequence()
    return payload
end

-- ============================================================================
-- SEND HELPERS (with sequence tracking)
-- ============================================================================

--- Send action payload
--- @param payload table Action payload
--- @return boolean Success status
function M.send_action(payload)
    return snapshot.send_udp_notification(add_sequence(payload))
end

--- Send snapshot state payload
--- @param payload table Snapshot state payload
--- @return boolean Success status
function M.send_snapshot_state(payload)
    return snapshot.send_udp_notification(add_sequence(payload))
end

--- Send entity operation payload
--- @param payload table Entity operation payload
--- @return boolean Success status
function M.send_entity_operation(payload)
    return snapshot.send_udp_notification(add_sequence(payload))
end

--- Send file IO payload
--- @param payload table File IO payload
--- @return boolean Success status
function M.send_file_io(payload)
    return snapshot.send_udp_notification(add_sequence(payload))
end

--- Send event payload
--- @param payload table Event payload
--- @return boolean Success status
function M.send_event(payload)
    return snapshot.send_udp_notification(add_sequence(payload))
end

return M

