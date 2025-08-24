local Errors = {}

--- Error message
---@param ok boolean
---@param code any
---@param category '"MAP"'|'"AGENT"'|'"ENGINE"'|'"VALIDATION"'
---@param msg string
---@param data table|nil
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
---@param code any
---@param msg string
---@param data table|nil
---@return string
function Errors.map(code, msg, data) return _emit(false, code, "MAP", msg, data) end

---@param code any
---@param msg string
---@param data table|nil
---@return string
function Errors.agent(code, msg, data) return _emit(false, code, "AGENT", msg, data) end

---@param code any
---@param msg string
---@param data table|nil
---@return string
function Errors.engine(code, msg, data) return _emit(false, code, "ENGINE", msg, data) end

---@param code any
---@param msg string
---@param data table|nil
---@return string
function Errors.validation(code, msg, data) return _emit(false, code, "VALIDATION", msg, data) end

return Errors
