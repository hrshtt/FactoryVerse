--- factorio_verse/core/action/ParamInstance.lua
--- ParamInstance class that owns both the spec and the parameter values,
--- enabling self-validation without external parameter passing.

--- @class ParamSpec
--- @field _spec table The parameter specification (validation rules)
--- @field _validated boolean Whether validation has been performed
local ParamSpec = {}

--- Create a new ParamInstance with direct property access via metatables
--- @param spec table Parameter specification with validation rules
--- @param values table|nil Initial parameter values (optional)
--- @return ParamSpec
function ParamSpec:new(spec, values)
    local instance = {
        _spec = spec or {},
        _validated = false
    }
    
    -- Copy initial values directly to the instance
    if values then
        for k, v in pairs(values) do
            instance[k] = v
        end
    end
    
    -- Set up metatable for validation and method access
    setmetatable(instance, {
        __index = function(t, k)
            -- First check if it's a method
            if ParamSpec[k] then
                return ParamSpec[k]
            end
            -- Otherwise return the parameter value directly
            return rawget(t, k)
        end,
        
        __newindex = function(t, k, v)
            -- Mark as needing re-validation when params change
            if k ~= "_spec" and k ~= "_validated" then
                rawset(t, "_validated", false)
            end
            rawset(t, k, v)
        end
    })
    
    return instance
end

--- Set values from a table
--- @param table table Parameter values
--- @return ParamSpec self for chaining
function ParamSpec:_set_values(table)
    if not table then
        return self
    end
    for k, v in pairs(table) do
        if k ~= "_spec" and k ~= "_validated" then
            rawset(self, k, v)
        end
    end
    self._validated = false
    return self
end

--- Get all parameter values (excluding internal fields)
--- @return table All parameter values
function ParamSpec:get_values()
    local values = {}
    for k, v in pairs(self) do
        if k ~= "_spec" and k ~= "_validated" and type(v) ~= "function" then
            values[k] = v
        end
    end
    return values
end

--- Validate the current parameter values against the spec
--- This is self-contained - no external parameters needed
--- @return ParamSpec self for chaining
--- @throws error if validation fails
function ParamSpec:validate()
    for key, rule in pairs(self._spec) do
        local value = self[key]

        -- Handle required parameters
        if rule.required and value == nil then
            error(string.format("Missing required parameter: %s", key))
        end

        -- Handle default values for optional parameters
        if value == nil and rule.default ~= nil then
            self[key] = rule.default
            value = rule.default
        end

        -- Type checking (if value is not nil)
        if value ~= nil and rule.type and rule.type ~= "any" then
            local t = type(value)
            if rule.type == "number" and t ~= "number" then
                error(string.format("Parameter '%s' must be a number, got %s", key, t))
            elseif rule.type == "string" and t ~= "string" then
                error(string.format("Parameter '%s' must be a string, got %s", key, t))
            elseif rule.type == "boolean" and t ~= "boolean" then
                error(string.format("Parameter '%s' must be a boolean, got %s", key, t))
            elseif rule.type == "table" and t ~= "table" then
                error(string.format("Parameter '%s' must be a table, got %s", key, t))
            end
        end
    end

    self._validated = true
    return self
end

--- Check if the instance has been validated
--- @return boolean
function ParamSpec:is_validated()
    return self._validated
end

--- Convert parameter values to a serializable table (excludes spec)
--- @return table Parameter values only
function ParamSpec:to_json()
    return self:get_values()
end

--- Create a new ParamSpec from a table
--- @param table table Parameter values
--- @return ParamSpec
function ParamSpec:from_table(table)
    self:_set_values(table)
    self:validate()
    return self
end

--- Create a new ParamInstance from JSON parameter values
--- @param spec table Parameter specification
--- @param json_params table JSON parameter values
--- @return ParamSpec
function ParamSpec:from_json(spec, json_params)
    return ParamSpec:new(spec, json_params)
end

return ParamSpec
