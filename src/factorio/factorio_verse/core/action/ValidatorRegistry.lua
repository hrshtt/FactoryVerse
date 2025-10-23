
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
    local validators = {}
    
    -- Collect validators that match the action name
    for pattern, validator_list in pairs(self.validators) do
        if self:matches_pattern(action_name, pattern) then
            for _, validator_func in ipairs(validator_list) do
                table.insert(validators, validator_func)
            end
        end
    end
    
    if #validators == 0 then
        log("No validations found for action: " .. action_name)
    else
        log("Validations found for action!!! " .. action_name .. " (total: " .. #validators .. ")")
    end
    
    return validators
end

--- Helper function to check if action_name matches a pattern
--- @param action_name string
--- @param pattern string
--- @return boolean
function ValidatorRegistry:matches_pattern(action_name, pattern)
    -- Exact match
    if pattern == action_name then
        return true
    end
    
    -- Wildcard match for all actions
    if pattern == "*" then
        return true
    end
    
    -- Prefix wildcard match (e.g., "agent.*" matches "agent.walk")
    if pattern:sub(-2) == ".*" then
        local prefix = pattern:sub(1, -3)
        return action_name:sub(1, #prefix) == prefix and action_name:sub(#prefix + 1, #prefix + 1) == "."
    end
    
    return false
end

--- @param action_name string
function ValidatorRegistry:clear_validations(action_name)
    self.validators[action_name] = nil
end

function ValidatorRegistry:build_registry()
    -- Static list of validator modules - wildcards handle inheritance naturally
    local VALIDATOR_MODULES = {
        -- Top level validator (uses "*" pattern to apply to all actions)
        "actions.validator",
        
        -- Category level validators (use "category.*" patterns)
        "actions.agent.validator",
        "actions.entity.validator", 
        "actions.item.validator",
        
        -- Specific action validators (use exact action names)
        "actions.agent.walk.validator",
        "actions.agent.send_message.validator",
        "actions.entity.place.validator",
        "actions.entity.remove.validator",
        "actions.entity.move.validator",
        "actions.entity.set_recipe.validator",
        "actions.item.craft.validator",
        "actions.item.transfer.validator",

        -- Flat actions
        "actions.start_research.validator",
        "actions.mine_resource.validator"
    }
    
    -- Load each validator module
    for _, module_name in ipairs(VALIDATOR_MODULES) do
        local ok, validator_registry_or_err = pcall(require, module_name)
        if ok then
            if type(validator_registry_or_err) == "table" and validator_registry_or_err.validators then
                -- Merge validators from the loaded module
                for pattern, validator_list in pairs(validator_registry_or_err.validators) do
                    if not self.validators[pattern] then
                        self.validators[pattern] = {}
                    end
                    for _, validator_func in ipairs(validator_list) do
                        table.insert(self.validators[pattern], validator_func)
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