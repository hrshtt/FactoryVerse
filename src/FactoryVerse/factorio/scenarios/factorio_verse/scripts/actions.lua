---@type Validator
local validator = require("scripts.validator")
local errors = require("scripts.errors")

---@alias ActionKind '"build"'|'"craft"'|'"mine"'|'"move_to"'|'"set_recipe"'|'"set_research"'|'"transfer"'


---Base action class
---BaseAction is the base class for all actions.
---It is used to create new actions and to validate and execute actions.
---It is also used to create the action data that is passed to the validator.
---It is also used to create the action data that is passed to the validator.
---@class BaseAction
---@field Validator Validator
---@field run function
---@field validate function
---@field action_type ActionKind
---@field params table
---@field get_default_params fun(self: BaseAction): table
---@field merge_params_with_defaults fun(self: BaseAction, parameters: table): table
---@field create_action_data fun(self: BaseAction, agent_index: integer, parameters: table): Action
---@field execute fun(self: BaseAction, agent_index: integer, parameters: table, gamestate: table, meta: Meta): string
---@field get_ordered_params fun(self: BaseAction, parameters: table): table
---@field validate_params fun(self: BaseAction, parameters: table): string[]
local BaseAction = {}

---Constructor for BaseAction
---@param action_type ActionKind The type of action (e.g., "build", "move_to", etc.)
---@param params table Parameter definitions for the action
---@return BaseAction
function BaseAction.new(action_type, params)
    local action = {
        action_type = action_type,
        params = params or {},
        Validator = validator
    }
    
    -- Set up the run method (to be overridden by subclasses)
    ---@param self BaseAction
    ---@param agent_index integer
    ---@param ... any
    ---@return string
    function action:run(agent_index, ...)
        -- Default implementation - subclasses should override this
        return errors.engine({}, "Action run method not implemented", { 
            action_type = self.action_type,
            agent_index = agent_index 
        })
    end
    
    -- Set up the validate method
    ---@param self BaseAction
    ---@param action_data Action
    ---@param gamestate table
    ---@param meta Meta
    ---@return string[]
    function action:validate(action_data, gamestate, meta)
        -- Validate using the validator system
        return self.Validator.validate(action_data, gamestate, meta)
    end
    
    -- Helper method to validate parameters
    ---@param self BaseAction
    ---@param parameters table
    ---@return string[]
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
    ---@param self BaseAction
    ---@return table
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
    ---@param self BaseAction
    ---@param parameters table
    ---@return table
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
    ---@param self BaseAction
    ---@param agent_index integer
    ---@param parameters table
    ---@return Action
    function action:create_action_data(agent_index, parameters)
        return {
            action_type = self.action_type,
            parameters = self:merge_params_with_defaults(parameters),
            agent_index = agent_index,
            tick = game.tick
        }
    end
    
    -- Helper method to execute action with validation
    ---@param self BaseAction
    ---@param agent_index integer
    ---@param parameters table
    ---@param gamestate table
    ---@param meta Meta
    ---@return string
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
        return self:run(agent_index, table.unpack(self:get_ordered_params(action_data.parameters)))
    end
    
    -- Helper method to get parameters in the order they should be passed to run
    ---@param self BaseAction
    ---@param parameters table
    ---@return table
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
