
local ValidatorRegistry = {}
ValidatorRegistry.__index = ValidatorRegistry

function ValidatorRegistry:new()
    local instance = {
        validators = {} -- action_name -> list of validation functions
    }
    setmetatable(instance, self)
    return instance
end

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

function ValidatorRegistry:get_validations(action_name)
    return self.validators[action_name] or {}
end

function ValidatorRegistry:clear_validations(action_name)
    self.validators[action_name] = nil
end
