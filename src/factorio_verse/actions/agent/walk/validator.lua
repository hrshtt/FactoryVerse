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

return { validate_direction }
