--- factorio_verse/core/action/Action.lua
--- Base class for all actions.

--- @class Action
--- @field name string
--- @field params ParamSpec
--- @field validators table
--- @field validate function
--- @field run function
local Action = {}
Action.__index = Action

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
    local Snapshot = require("core.snapshot.Snapshot")
    local snapshot = Snapshot:get_instance()
    
    -- Update affected entities
    if result.affected_unit_numbers then
      for _, unit_number in ipairs(result.affected_unit_numbers) do
        snapshot:update_entity_from_action(unit_number, nil)
      end
    end
    
    -- Remove deleted entities
    if result.removed_unit_numbers then
      -- Extract last position from result if available
      local last_position = nil
      if result.removed_entity and result.removed_entity.position then
        last_position = result.removed_entity.position
      end
      
      for _, unit_number in ipairs(result.removed_unit_numbers) do
        snapshot:remove_entity_from_action(unit_number, last_position)
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