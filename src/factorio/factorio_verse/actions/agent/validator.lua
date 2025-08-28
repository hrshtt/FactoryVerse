local ValidatorRegistry = require("core.action.ValidatorRegistry")

local validator_registry = ValidatorRegistry:new()

-- Agent category validators can be added here using "agent.*" pattern
-- Example:
-- local function validate_agent_exists(params)
--     -- Common agent validation logic
--     return true
-- end
-- validator_registry:register("agent.*", validate_agent_exists)

return validator_registry
