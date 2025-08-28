local ValidatorRegistry = require("core.action.ValidatorRegistry")

local validator_registry = ValidatorRegistry:new()

-- mine_resource specific validators can be added here
-- Currently inherits from actions.validator only

return validator_registry
