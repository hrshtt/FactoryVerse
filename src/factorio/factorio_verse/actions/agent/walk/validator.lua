local ValidatorRegistry = require("factorio_verse.core.action.ValidatorRegistry")

local validator_registry = ValidatorRegistry:new()

local function validate_direction(params)
    if params.direction == nil then return false end
    return true
end

validator_registry:register("agent.walk", function(params)
    return validate_direction(params)
end)

return validator_registry
