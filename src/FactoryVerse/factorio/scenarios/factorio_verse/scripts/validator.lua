local errors = require("scripts.errors")


---@class Meta
---@field map_settings table
---@field server_settings table
---@field prototype_defs table

---@class ValidationContext
---@field action BaseAction
---@field gamestate table
---@field meta Meta
local ValidationContext = {}
ValidationContext.__index = ValidationContext

---@param action BaseAction
---@param gamestate table  -- current gamestate snapshot
---@param meta Meta
function ValidationContext.new(action, gamestate, meta)
    return setmetatable({
        action    = action,
        gamestate = gamestate,
        meta      = meta,
    }, ValidationContext)
end

---@param action_type string
---@param parameters table
---@param agent_index integer|nil
---@return Action
function ValidationContext.create_action_context(action_type, parameters, agent_index)
    return {
        action_type = action_type,
        parameters = parameters,
        agent_index = agent_index,
    }
end

---@class Validator
---@field _registry table
local Validator = {
    _registry = {}, -- [ action_type ] = { fn1, fn2, … }
}

---@param action_type ActionKind
---@param fn fun(ctx: ValidationContext): (string|string[]|nil)
function Validator.register(action_type, fn)
    Validator._registry[action_type] = Validator._registry[action_type] or {}
    table.insert(Validator._registry[action_type], fn)
end

---@param action BaseAction
---@param gamestate table  -- current gamestate snapshot
---@param meta Meta
---@return string[] errs  -- list of error JSON strings
function Validator.validate(action, gamestate, meta)
    local ctx  = ValidationContext.new(action, gamestate, meta)
    local errs = {}
    local fns  = Validator._registry[action.action_type] or {}

    for _, fn in ipairs(fns) do
        local res = fn(ctx)
        if res then
            if type(res) == "table" and res[1] then
                for _, e in ipairs(res) do table.insert(errs, e) end
            else
                table.insert(errs, res)
            end
        end
    end

    return errs
end

return Validator
