local ValidatorRegistry = require("core.action.ValidatorRegistry")
local game_state = require("core.game_state.GameState")

local validator_registry = ValidatorRegistry:new()

--- @param params WalkParams
--- @return boolean
local function validate_direction(params)
    local dir = string.lower(tostring(params.direction))
    if not game_state.aliases.direction[dir] then
        error("Direction '" .. tostring(params.direction) .. "' is not allowed")
    end
    return true
end

validator_registry:register("agent.walk", validate_direction)

return validator_registry
