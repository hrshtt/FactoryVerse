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

--- @param params ParamSpec
--- @return boolean
function Action:validate(params)
  for _, validator in ipairs(self.validators) do
    local result = validator(params)
    if not result then
      return false
    end
  end
  return true
end

--- @param params ParamSpec
--- @return boolean
function Action:run(params)
  return true
end

return Action