local ValidatorRegistry = require("core.action.ValidatorRegistry")

local validator_registry = ValidatorRegistry:new()

-- Entity category validators can be added here using "entity.*" pattern
-- Example:
-- local function validate_entity_exists(params)
--     -- Common entity validation logic
--     return true
-- end
-- validator_registry:register("entity.*", validate_entity_exists)

return validator_registry
