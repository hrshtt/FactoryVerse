--- UDP notification utilities
--- Subset of snapshot.lua focused on UDP functionality
--- This allows fv_embodied_agent to use UDP without depending on full snapshot module

local M = {}

-- UDP port for agent action notifications (default for agent-specific payloads)
-- Note: Snapshot notifications use a separate port (34400)
M.UDP_PORT = 34202

-- Debug flag for verbose logging
M.DEBUG = false

-- ============================================================================
-- UDP NOTIFICATION HELPERS
-- ============================================================================

--- Send UDP notification with standardized error handling
--- @param payload table - Payload to send as JSON
--- @param port number|nil - UDP port to send to (defaults to M.UDP_PORT)
--- @return boolean - Success status
function M.send_udp_notification(payload, port)
    if not payload then
        return false
    end

    local udp_port = port or M.UDP_PORT

    if M.DEBUG then
        local event_type = payload.event_type or "unknown"
        game.print(string.format("[DEBUG UDP.send_udp_notification] Tick %d: Sending %s (port %d)", 
            game.tick, event_type, udp_port))
    end

    local ok_json, json_str = pcall(helpers.table_to_json, payload)
    if not ok_json or not json_str then
        log("Failed to serialize UDP payload to JSON")
        if M.DEBUG then
            game.print(string.format("[DEBUG UDP.send_udp_notification] Tick %d: JSON serialization failed", game.tick))
        end
        return false
    end

    local ok_udp, err = pcall(function()
        helpers.send_udp(udp_port, json_str)
    end)

    if not ok_udp then
        local error_msg = err or "unknown"
        log(string.format("[UDP] ERROR sending notification: %s", error_msg))
        if game and game.print then
            game.print(string.format("[UDP] ERROR: %s", error_msg))
        end
        if M.DEBUG then
            game.print(string.format("[DEBUG UDP.send_udp_notification] Tick %d: UDP send failed: %s", game.tick, error_msg))
        end
        return false
    end

    if M.DEBUG then
        local event_type = payload.event_type or "unknown"
        game.print(string.format("[DEBUG UDP.send_udp_notification] Tick %d: Sent UDP notification: %s (port %d)", 
            game.tick, event_type, udp_port))
    end

    return true
end

-- ============================================================================
-- ACTION STATUS CONSTANTS
-- ============================================================================

M.ACTION_STATUS = {
    STARTED = "started",
    PROGRESS = "progress",
    COMPLETED = "completed",
    CANCELLED = "cancelled",
    QUEUED = "queued",
}

-- ============================================================================
-- ACTION PAYLOAD CREATION
-- ============================================================================

--- Create action payload with consistent schema
--- @param action_id string Action ID
--- @param agent_id number Agent ID
--- @param action_type string Action type
--- @param status string Status (started, progress, completed, cancelled, queued)
--- @param rcon_tick number|nil RCON tick
--- @param result table|nil Result data
--- @param success boolean|nil Success flag
--- @param cancelled boolean|nil Cancelled flag
--- @param category string|nil Category (walking, mining, crafting, etc.)
--- @return table Payload
function M.create_action_payload(action_id, agent_id, action_type, status, rcon_tick, result, success, cancelled, category)
    local payload = {
        event_type = "action",
        action_id = action_id,
        agent_id = agent_id,
        action_type = action_type,
        status = status,
        rcon_tick = rcon_tick or game.tick,
        tick = game.tick,
    }
    
    if status == M.ACTION_STATUS.COMPLETED then
        payload.completion_tick = game.tick
        payload.success = success ~= false
        if result then
            payload.result = result
        end
    elseif status == M.ACTION_STATUS.CANCELLED then
        payload.cancellation_tick = game.tick
        payload.cancelled = true
        if result then
            payload.result = result
        end
    elseif status == M.ACTION_STATUS.PROGRESS then
        if result then
            payload.progress = result
        end
    elseif status == M.ACTION_STATUS.QUEUED then
        -- No additional fields for queued
    elseif status == M.ACTION_STATUS.STARTED then
        -- No additional fields for started
    end
    
    if cancelled ~= nil then
        payload.cancelled = cancelled
    end
    
    if category then
        payload.category = category
    end
    
    return payload
end

--- Send action completion UDP notification (backward compatibility)
--- @param payload table - Action completion payload
--- @return boolean - Success status
function M.send_action_completion_udp(payload)
    if not payload or not payload.action_id or not payload.agent_id or 
       not payload.action_type then
        log("Invalid action completion payload: missing required fields")
        return false
    end
    -- Ensure success field exists for backward compatibility
    if payload.status == M.ACTION_STATUS.COMPLETED and payload.success == nil then
        payload.success = true
    end
    return M.send_udp_notification(payload)
end

return M

