local game_state = require("GameState")

--- @param params WalkParams|WalkToParams
--- @return boolean
local function validate_direction(params)
    -- Only validate direction if it's present (agent.walk has it, agent.walk_to doesn't)
    if params.direction == nil then
        return true
    end
    -- local dir = string.lower(tostring(params.direction))
    -- print("dir: " .. dir)
    if not game_state.aliases.direction[params.direction] then
        error("Direction '" .. tostring(params.direction) .. "' is not allowed")
    end
    return true
end

--- Validate that the agent is not already walking (for walk_to action only)
--- @param params WalkToParams
--- @return boolean, string|nil
local function validate_no_concurrent_walking(params)
    -- Only applies to walk_to action (has position parameter)
    if params.position == nil then
        return true -- skip for walk action (which has direction instead)
    end
    
    -- Skip if agent_id not provided
    if not params.agent_id then
        return true
    end
    
    -- Check if this agent is already walking
    storage.walk_in_progress = storage.walk_in_progress or {}
    local action_id = storage.walk_in_progress[params.agent_id]
    
    if action_id then
        return false, string.format("Agent %d is already walking (action_id: %s). Wait for current walk to complete.", 
                                   params.agent_id, action_id)
    end
    
    return true
end

return { validate_direction, validate_no_concurrent_walking }
