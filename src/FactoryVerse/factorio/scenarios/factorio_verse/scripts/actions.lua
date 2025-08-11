local validator = require("scripts.validator")
local errors = require("scripts.errors")

---Base action class
---@class BaseAction
---@field Validator Validator
---@field run function
---@field validate function
---@field action_type string
---@field params table
local BaseAction = {}

---Constructor for BaseAction
---@param action_type string The type of action (e.g., "build", "move_to", etc.)
---@param params table Parameter definitions for the action
---@return BaseAction
function BaseAction.new(action_type, params)
    local action = {
        action_type = action_type,
        params = params or {},
        Validator = validator
    }
    
    -- Set up the run method (to be overridden by subclasses)
    function action:run(agent_index, ...)
        -- Default implementation - subclasses should override this
        return errors.engine({}, "Action run method not implemented", { 
            action_type = self.action_type,
            agent_index = agent_index 
        })
    end
    
    -- Set up the validate method
    function action:validate(action_data, gamestate, meta)
        -- Create validation context
        local ctx = self.Validator.create_action_context(
            action_data.action_type,
            action_data.parameters,
            action_data.agent_index
        )
        
        -- Validate using the validator system
        return self.Validator.validate(action_data, gamestate, meta)
    end
    
    -- Helper method to validate parameters
    function action:validate_params(parameters)
        local errors_list = {}
        
        for param_name, param_def in pairs(self.params) do
            if param_def.required and not parameters[param_name] then
                table.insert(errors_list, errors.validation("MISSING_PARAM", 
                    "Required parameter missing: " .. param_name, 
                    { param_name = param_name, action_type = self.action_type }))
            end
            
            if parameters[param_name] and param_def.type then
                local param_type = type(parameters[param_name])
                if param_type ~= param_def.type then
                    table.insert(errors_list, errors.validation("INVALID_PARAM_TYPE", 
                        "Parameter type mismatch for " .. param_name .. ": expected " .. param_def.type .. ", got " .. param_type,
                        { param_name = param_name, expected_type = param_def.type, actual_type = param_type }))
                end
            end
        end
        
        return errors_list
    end
    
    -- Helper method to get default parameters
    function action:get_default_params()
        local defaults = {}
        for param_name, param_def in pairs(self.params) do
            if param_def.default then
                defaults[param_name] = param_def.default
            end
        end
        return defaults
    end
    
    -- Helper method to merge parameters with defaults
    function action:merge_params_with_defaults(parameters)
        local defaults = self:get_default_params()
        local merged = {}
        
        -- Copy defaults first
        for k, v in pairs(defaults) do
            merged[k] = v
        end
        
        -- Override with provided parameters
        for k, v in pairs(parameters) do
            merged[k] = v
        end
        
        return merged
    end
    
    -- Helper method to create action data
    function action:create_action_data(agent_index, parameters)
        return {
            action_type = self.action_type,
            parameters = self:merge_params_with_defaults(parameters),
            agent_index = agent_index,
            tick = game.tick
        }
    end
    
    -- Helper method to execute action with validation
    function action:execute(agent_index, parameters, gamestate, meta)
        local action_data = self:create_action_data(agent_index, parameters)
        
        -- Validate parameters
        local param_errors = self:validate_params(action_data.parameters)
        if #param_errors > 0 then
            return param_errors[1] -- Return first error
        end
        
        -- Validate action
        local validation_errors = self:validate(action_data, gamestate, meta)
        if #validation_errors > 0 then
            return validation_errors[1] -- Return first error
        end
        
        -- Execute the action
        return self:run(agent_index, unpack(self:get_ordered_params(action_data.parameters)))
    end
    
    -- Helper method to get parameters in the order they should be passed to run
    function action:get_ordered_params(parameters)
        local ordered = {}
        for param_name, _ in pairs(self.params) do
            if parameters[param_name] then
                table.insert(ordered, parameters[param_name])
            end
        end
        return ordered
    end
    
    return action
end

return BaseAction
