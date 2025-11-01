--- factorio_verse/core/action/Action.lua
--- Base class for all actions.

local Snapshot = require("core.snapshot.Snapshot")

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

--- @class Action
--- @field name string
--- @field params ParamSpec
--- @field validators table
--- @field validate function
--- @field run function
local Action = {}
Action.__index = Action

Action.ParamSpec = ParamSpec

-- Naive JSON helpers (string check and decode via Factorio API when available)
local function _trim(s)
  return (s and s:gsub("^%s+", ""):gsub("%s+$", "")) or s
end

local function _looks_like_json(s)
  if type(s) ~= "string" then return false end
  local t = _trim(s)
  if not t or #t == 0 then return false end
  local first = t:sub(1, 1)
  local last = t:sub(-1)
  return (first == "{" and last == "}") or (first == "[" and last == "]")
end

--- @param name string
--- @param params ParamSpec
--- @return Action
function Action:new(name, params, validators)
  return setmetatable({
    name = name,
    params = params,
    validators = validators or {},
  }, Action)
end

--- Attach validators to the action
--- @param validators table<function>
function Action:attach_validators(validators)
  self.validators = validators
end

--- Validate parameters using external validators
--- @param params ParamSpec|table Parameter instance or raw params (for backward compatibility)
--- @return boolean success
--- @return string|nil error_message
function Action:validate(params)
  local params_table
  if type(params) == "table" and params.get_values then
    -- It's a ParamInstance
    params_table = params:get_values()
  else
    -- It's raw params table (backward compatibility)
    params_table = params
  end
  
  for i, validator in ipairs(self.validators) do
    local ok, result, error_msg = pcall(validator, params_table)
    if not ok then
      return false, "Validator " .. i .. " threw error: " .. tostring(result)
    elseif result == false then
      return false, error_msg or ("Validator " .. i .. " failed")
    elseif result ~= true then
      -- Handle case where validator returns just false without error message
      return false, "Validator " .. i .. " failed"
    end
  end
  return true
end

--- Prepare parameters before running an action.
--- Accepts ParamSpec instance, raw table, or JSON string. Returns validated ParamSpec.
--- @param game_state GameState
--- @param params ParamSpec|table|string
--- @return ParamSpec|any
function Action:_pre_run(game_state, params)
  local instance

  -- Decode JSON string if provided
  if type(params) == "string" then
    if _looks_like_json(params) then
      if helpers and helpers.json_to_table then
        local ok, decoded = pcall(helpers.json_to_table, params)
        if not ok or type(decoded) ~= "table" then
          error("Invalid JSON params")
        end
        params = decoded
      else
        error("JSON decode unavailable in this context")
      end
    else
      error("Invalid string type: Params can only be a table or a JSON string")
    end
  end

  -- Normalize to ParamSpec instance
  if type(params) == "table" and params.get_values then
    instance = params
  else
    instance = self.params:from_table(params or {})
  end

  -- Ensure validated and run external validators
  if not instance:is_validated() then
    instance:validate()
  end
  local ok, error_msg = self:validate(instance)
  if ok == false then
    error("Validation failed for action '" .. tostring(self.name) .. "': " .. (error_msg or "unknown error"))
  end
 
  self.params = instance
  return instance
end

--- Post-run hook with mutation tracking
--- @param result any
--- @param params ParamSpec
--- @return any
function Action:_post_run(result, params)
  -- Handle entity mutations if present in result
  if result and type(result) == "table" then
    local snapshot = Snapshot:get_instance()
    
    -- Update affected entities (now using positions instead of unit_numbers)
    if result.affected_positions then
      for _, position_info in ipairs(result.affected_positions) do
        local position = position_info.position or position_info
        local entity_name = position_info.entity_name
        local entity_type = position_info.entity_type
        snapshot:update_entity_from_action(position, entity_name, entity_type)
      end
    end
    
    -- Remove deleted entities (now using positions instead of unit_numbers)
    if result.removed_positions then
      for _, position_info in ipairs(result.removed_positions) do
        local position = position_info.position or position_info
        local entity_name = position_info.entity_name
        snapshot:remove_entity_from_action(position, entity_name)
      end
    end
    
    -- Legacy support: if affected_unit_numbers is provided, convert to positions
    if result.affected_unit_numbers then
      log("WARNING: affected_unit_numbers is deprecated, use affected_positions instead")
      -- Note: Cannot convert unit_numbers to positions without entity lookup, so we skip these
    end
    
    -- Legacy support: if removed_unit_numbers is provided, convert to positions
    if result.removed_unit_numbers then
      log("WARNING: removed_unit_numbers is deprecated, use removed_positions instead")
      -- Extract position from result if available
      if result.removed_entity and result.removed_entity.position then
        snapshot:remove_entity_from_action(result.removed_entity.position, result.removed_entity.name)
      end
    end
  end

  return result
end

--- Run the action with validated parameters
--- @param params ParamSpec|table|string Parameter instance, raw params, or JSON string
--- @return any Action result
function Action:run(params, ...) end

return Action