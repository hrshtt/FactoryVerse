--- UDP notification utilities
--- Subset of snapshot.lua focused on UDP functionality
--- This allows fv_embodied_agent to use UDP without depending on full snapshot module

local M = {}

-- UDP port for all notifications (action port as source of truth)
M.UDP_PORT = 34202

-- Debug flag for verbose logging
M.DEBUG = false

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
        game.print(string.format("[udp] Sent UDP notification: %s (port %d)", event_type, M.UDP_PORT))
        game.print(string.format("[udp] Payload: %s", json_str))
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

return M

