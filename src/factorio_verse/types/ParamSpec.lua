--- ParamSpec class that owns both the spec and the parameter values,
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
    if type(table) ~= "table" then
        error("Invalid table type: " .. type(table))
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
    self = self:_set_values(table)
    self = self:validate()
    return self
end

--- Create a new ParamInstance from JSON parameter values
--- @param spec table Parameter specification
--- @param json_params table JSON parameter values
--- @return ParamSpec
function ParamSpec:from_json(spec, json_params)
    return ParamSpec:new(spec, json_params)
end

--- Normalize varargs from remote calls - supports multiple calling conventions:
--- 1. JSON string: '{"num_agents": 2, "destroy_existing": true}'
--- 2. Object table: {num_agents = 2, destroy_existing = true}
--- 3. Positional args: 2, true, ...
--- Converts to normalized positional arguments based on spec._param_order
--- Validates parameters against spec rules (type, required)
--- @param spec table Specification with _param_order field listing parameter names
--- @param ... any Variable arguments from remote call
--- @return table Positional arguments ready to pass to function
function ParamSpec:normalize_varargs(spec, ...)
    local args = {...}
    
    -- Handle JSON string decoding
    if #args == 1 and type(args[1]) == "string" then
        if helpers and helpers.json_to_table then
            local ok, decoded = pcall(helpers.json_to_table, args[1])
            if ok and type(decoded) == "table" then
                args[1] = decoded
            end
        end
    end
    
    -- Convert object table to positional args using spec
    if spec and spec._param_order and #args == 1 and type(args[1]) == "table" and not args[1][1] then
        local opts = args[1]
        local positional = {}
        
        -- Validate and convert each parameter
        for i, param_name in ipairs(spec._param_order) do
            local value = opts[param_name]
            local rule = spec[param_name]
            
            -- Validate required parameters
            if rule and rule.required and value == nil then
                error(string.format("Missing required parameter: %s", param_name))
            end
            
            -- Type checking (if value is not nil)
            if value ~= nil and rule and rule.type and rule.type ~= "any" then
                local t = type(value)
                if rule.type == "number" and t ~= "number" then
                    error(string.format("Parameter '%s' must be a number, got %s", param_name, t))
                elseif rule.type == "string" and t ~= "string" then
                    error(string.format("Parameter '%s' must be a string, got %s", param_name, t))
                elseif rule.type == "boolean" and t ~= "boolean" then
                    error(string.format("Parameter '%s' must be a boolean, got %s", param_name, t))
                elseif rule.type == "table" and t ~= "table" then
                    error(string.format("Parameter '%s' must be a table, got %s", param_name, t))
                end
            end
            
            table.insert(positional, value)
        end
        return positional
    end
    
    -- Already positional or no conversion needed
    return args
end

return ParamSpec