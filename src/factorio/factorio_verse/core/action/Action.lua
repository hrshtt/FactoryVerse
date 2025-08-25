--- factorio_verse/core/action/Action.lua
--- Base class for all actions.


--- @class Action
--- @field name string
--- @field params table
--- @field validators table
--- @field validate function
--- @field run function
local Action = {}
Action.__index = Action

function Action.new(name, params)
  return setmetatable({
    name = name,
    params = params,
    validators = {},
  }, Action)
end

function Action:validate(params, gs, ctx)
  for _, validator in ipairs(self.validators) do
    local result = validator(params, gs, ctx)
    if not result then
      return false
    end
  end
  return true
end

function Action:run(params, gs, ctx)
  return true
end

return Action