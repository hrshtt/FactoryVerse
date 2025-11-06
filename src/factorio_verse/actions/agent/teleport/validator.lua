local GameState = require("GameState")

--- Validate position structure (x and y are numbers)
--- @param params table
--- @return boolean, string|nil
local function validate_position_structure(params)
    if not params.position then
        return true -- Let ParamSpec handle required check
    end
    
    if type(params.position) ~= "table" then
        return false, "Position must be a table"
    end
    
    if type(params.position.x) ~= "number" or type(params.position.y) ~= "number" then
        return false, "Position must have numeric x and y fields"
    end
    
    return true
end

--- Validate that the EXACT position is safe when fallback_to_safe_position is false (default)
--- @param params table
--- @return boolean, string|nil
local function validate_safe_position_when_required(params)
    -- Only validate if fallback_to_safe_position is false (default strict mode)
    if params.fallback_to_safe_position then
        return true
    end

    -- Position format should already be validated, but check anyway
    if not params.position or type(params.position.x) ~= "number" or type(params.position.y) ~= "number" then
        return true -- Let other validator handle this
    end

    local surface = game.surfaces[1]
    if not surface then
        return false, "No surface available"
    end

    -- Need agent to get force for can_place_entity check
    local gs = GameState:new()
    local agent = gs.agent:get_agent(params.agent_id)
    if not agent or not agent.valid then
        return true -- Let agent validator handle this
    end

    local target_position = { x = params.position.x, y = params.position.y }
    
    -- Check if the EXACT target position can place a character (not searching nearby)
    local can_place = surface.can_place_entity{
        name = "character",
        position = target_position,
        force = agent.force
    }
    
    if not can_place then
        return false, "Target position is not safe for teleportation (blocked or invalid)"
    end

    return true
end

return { validate_position_structure, validate_safe_position_when_required }

