local errors = require("scripts.errors")
local ValidationContext = {}
ValidationContext.__index = ValidationContext

--- @param action   table { action_type=string, parameters=table, tick=int?, agent_index=int? }
--- @param gamestate table your existing gamestate snapshot
--- @param meta     table { map_settings=…, server_settings=…, prototype_defs=… }
function ValidationContext.new(action, gamestate, meta)
    return setmetatable({
        action    = action,
        gamestate = gamestate,
        meta      = meta,
    }, ValidationContext)
end

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

function Validator.register(action_type, fn)
    Validator._registry[action_type] = Validator._registry[action_type] or {}
    table.insert(Validator._registry[action_type], fn)
end


--- @param action    table
--- @param gamestate table
--- @param meta      table
--- @return table[] list of error objects
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
