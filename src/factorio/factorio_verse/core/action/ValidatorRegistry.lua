
local ValidatorRegistry = {}
ValidatorRegistry.__index = ValidatorRegistry

--- @class ValidatorRegistry
--- @field validators table<string, table<function>>
--- @field register function
--- @field get_validations function
--- @field clear_validations function
--- @field new function
function ValidatorRegistry:new()
    local instance = {
        validators = {} -- action_name -> list of validation functions
    }
    setmetatable(instance, self)
    return instance
end

--- @param action_name string
--- @param validator_func function
function ValidatorRegistry:register(action_name, validator_func)
    if type(action_name) ~= "string" then
        error("Action name must be a string")
    end
    
    if type(validator_func) ~= "function" then
        error("Validator must be a function")
    end
    
    if not self.validators[action_name] then
        self.validators[action_name] = {}
    end
    
    table.insert(self.validators[action_name], validator_func)
end

--- @param action_name string
--- @return table<function>
function ValidatorRegistry:get_validations(action_name)
    return self.validators[action_name] or {}
end

--- @param action_name string
function ValidatorRegistry:clear_validations(action_name)
    self.validators[action_name] = nil
end
