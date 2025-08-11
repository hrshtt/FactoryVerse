local Errors = {}

--- Error message
---@param ok boolean
---@param code string
---@param category string
---@param msg string
---@param data table
---@return string
local function _emit(ok, code, category, msg, data)
  return helpers.table_to_json {
    ok = ok,
    code = code,
    category = category,
    message = msg,
    data = data or {},
    trace_id = data and data.trace_id,
    tick = game.tick,
    agent_id = data and data.agent_id,
  }
end

-- sugar for action authors
function Errors.map(code, msg, data) return _emit(false, code, "MAP", msg, data) end

function Errors.agent(code, msg, data) return _emit(false, code, "AGENT", msg, data) end

function Errors.engine(code, msg, data) return _emit(false, code, "ENGINE", msg, data) end

function Errors.validation(code, msg, data) return _emit(false, code, "VALIDATION", msg, data) end

return Errors
