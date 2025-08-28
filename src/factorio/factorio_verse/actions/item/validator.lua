local ValidatorRegistry = require("core.action.ValidatorRegistry")

local validator_registry = ValidatorRegistry:new()

-- Item category validators can be added here using "item.*" pattern
-- Example:
-- local function validate_item_available(params)
--     -- Common item validation logic
--     return true
-- end
-- validator_registry:register("item.*", validate_item_available)

return validator_registry
