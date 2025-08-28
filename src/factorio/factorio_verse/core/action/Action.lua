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

--- Validate parameters using external validators
--- @param params ParamSpec|table Parameter instance or raw params (for backward compatibility)
--- @return boolean
function Action:validate(params)
  local params_table
  if type(params) == "table" and params.get_values then
    -- It's a ParamInstance
    params_table = params:get_values()
  else
    -- It's raw params table (backward compatibility)
    params_table = params
  end
  
  for _, validator in ipairs(self.validators) do
    local result = validator(params_table)
    if not result then
      return false
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
  local ok = self:validate(instance)
  if ok == false then
    error("Validation failed for action '" .. tostring(self.name) .. "'")
  end

  self.params = instance

  -- Run external validators
  for _, validator in ipairs(self.validators) do
    local result = validator(game_state, instance)
    if not result then
      error("Validation failed for action '" .. tostring(self.name) .. "'")
    end
  end
  return instance
end

--- Post-run hook. Placeholder for future use.
--- @param result any
--- @param params ParamSpec
--- @return any
function Action:_post_run(result, params)
  return result
end

--- Run the action with validated parameters
--- @param params ParamSpec|table|string Parameter instance, raw params, or JSON string
--- @return any Action result
function Action:run(params)
  return self:_pre_run(params)
end

return Action