local game_state = require("core.game_state.GameState")

--- @param params WalkParams
--- @return boolean
local function validate_direction(params)
    -- local dir = string.lower(tostring(params.direction))
    -- print("dir: " .. dir)
    if not game_state.aliases.direction[params.direction] then
        error("Direction '" .. tostring(params.direction) .. "' is not allowed")
    end
    return true
end

return { validate_direction }
