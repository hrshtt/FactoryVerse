--- factorio_verse/core/action/Action.lua
--- Base class for all actions.

local ParamSpec = require("factorio_verse.core.action.ParamSpec")

--- @class Action
--- @field name string
--- @field params ParamSpec
--- @field validators table
--- @field validate function
--- @field run function
local Action = {}
Action.__index = Action

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

--- Run the action with validated parameters
--- @param params ParamSpec|table Parameter instance or raw params
--- @return any Action result
function Action:run(params)
  local instance
  if type(params) == "table" and params.get_values then
    instance = params
  else
    instance = self.params:from_table(params or {})
  end

  if not instance:is_validated() then
    instance:validate()
  end

  local ok = self:validate(instance)
  if ok == false then
    error("Validation failed for action '" .. tostring(self.name) .. "'")
  end

  self.params = instance
  return instance
end

return Action