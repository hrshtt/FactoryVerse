local ValidatorRegistry = require("core.action.ValidatorRegistry")

local validator_registry = ValidatorRegistry:new()

local function validate_params(params)
    if type(params) ~= "table" then return false, "params must be a table" end
    if type(params.agent_id) ~= "number" then return false, "agent_id must be number" end
    if type(params.recipe) ~= "string" or params.recipe == "" then return false, "recipe must be non-empty string" end
    if params.count ~= nil and (type(params.count) ~= "number" or params.count <= 0) then
        return false, "count must be positive number if provided"
    end
    return true
end

validator_registry:register("item.craft", validate_params)

return validator_registry


