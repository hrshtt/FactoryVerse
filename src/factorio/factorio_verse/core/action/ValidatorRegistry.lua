
local ValidatorRegistry = {}
ValidatorRegistry.__index = ValidatorRegistry

--- @class ValidatorRegistry
--- @field validators table<string, table<function>>
--- @field register function
--- @field get_validations function
--- @field clear_validations function
--- @field build_registry function
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
    if not self.validators[action_name] then
        log("No validations found for action: " .. action_name)
        return {}
    end
    log("Validations found for action!!! " .. action_name)
    return self.validators[action_name] or {}
end

--- @param action_name string
function ValidatorRegistry:clear_validations(action_name)
    self.validators[action_name] = nil
end

function ValidatorRegistry:build_registry()
    -- Static list of validator modules (similar to ACTION_MODULES in ActionRegistry)
    -- Each corresponds to a validator.lua file that registers validators
    local VALIDATOR_MODULES = {
        -- agent validators
        "actions.validator",
        "actions.agent.walk.validator",
        
        -- entity validators  
        "actions.entity.place.validator",
        
        -- research validators
        "actions.start_research.validator",
        
        -- Add more as needed...
    }
    
    -- Load each validator module, which will register validators with this registry
    for _, module_name in ipairs(VALIDATOR_MODULES) do
        local ok, validator_registry_or_err = pcall(require, module_name)
        if ok then
            -- The validator module returns a ValidatorRegistry with registered validators
            -- We need to merge those validators into this registry
            if type(validator_registry_or_err) == "table" and validator_registry_or_err.validators then
                for action_name, validator_list in pairs(validator_registry_or_err.validators) do
                    if not self.validators[action_name] then
                        self.validators[action_name] = {}
                    end
                    -- Merge validators from the loaded module
                    for _, validator_func in ipairs(validator_list) do
                        table.insert(self.validators[action_name], validator_func)
                    end
                end
            end
        else
            log("Error loading validator module: " .. module_name)
            log(validator_registry_or_err)
        end
    end
    
    return true
end

return ValidatorRegistry