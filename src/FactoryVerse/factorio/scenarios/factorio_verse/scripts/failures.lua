local Failures = {}

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
function Failures.logical(code, msg, data) return _emit(false, code, "LOGICAL", msg, data) end

function Failures.resource(code, msg, data) return _emit(false, code, "RESOURCE", msg, data) end

function Failures.capacity(code, msg, data) return _emit(false, code, "CAPACITY", msg, data) end

return Failures
