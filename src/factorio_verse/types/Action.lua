--- factorio_verse/core/action/Action.lua
--- Base class for all actions.

local ParamSpec = require("types.ParamSpec")

--- @class Action
--- @field name string
--- @field params ParamSpec
--- @field game_state GameState|nil (set during action registration)
--- @field is_sync boolean Whether action completes synchronously (default: true)
--- @field is_async boolean|nil Whether action completes asynchronously (default: nil, derived from is_sync)
--- @field run function
local Action = {}
Action.__index = Action

Action.ParamSpec = ParamSpec

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
function Action:new(name, params)
  return setmetatable({
    name = name,
    params = params,
    is_sync = true,  -- Default: all actions are sync unless explicitly marked async
    is_async = nil,  -- Derived from is_sync
  }, Action)
end

--- Set the game_state instance for this action (called during registration)
--- @param game_state GameState
function Action:set_game_state(game_state)
  self.game_state = game_state
end

--- Prepare parameters before running an action.
--- Subclasses can override to return custom context table instead of ParamSpec.
--- Accepts ParamSpec instance, table, or JSON string. Returns validated ParamSpec by default.
--- @param params ParamSpec|table|string
--- @return ParamSpec|any validated params or context table
function Action:_pre_run(params)
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

  -- Ensure validated (ParamSpec format validation only)
  if not instance:is_validated() then
    instance:validate()
  end
 
  self.params = instance
  
  -- Default: return validated ParamSpec
  -- Subclasses can override to return context table
  return instance
end

--- Post-run hook
--- @param result any
--- @param params ParamSpec
--- @return any
function Action:_post_run(result, params)
  -- Mutation tracking is now handled by GameState modules directly
  return result
end

--- Run the action with validated parameters
--- @param params ParamSpec|table|string Parameter instance, raw params, or JSON string
--- @return any Action result
function Action:run(params, ...) end

return Action