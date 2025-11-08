--- factorio_verse/types/AsyncAction.lua
--- AsyncAction class for actions that complete across multiple ticks.
--- Inherits from Action and provides helpers for async action contracts.

local Action = require("types.Action")

--- @class AsyncAction : Action
--- @field name string
--- @field params ParamSpec
--- @field validators table
--- @field game_state GameState|nil (set during action registration)
--- @field is_async boolean Always true for async actions
--- @field cancel_params ParamSpec|nil Parameter specification for cancel action
--- @field cancel_validators table|nil Validators for cancel action
--- @field cancel_storage_key string|nil Storage key for tracking (e.g., "walk_in_progress")
--- @field cancel_tracking_key_fn function|nil Function to extract tracking key from cancel params
--- @field validate function
--- @field run function
--- @field cancel function
local AsyncAction = {}
AsyncAction.__index = AsyncAction

-- Inheritance: AsyncAction methods fall back to Action methods
setmetatable(AsyncAction, { __index = Action })

AsyncAction.ParamSpec = Action.ParamSpec

--- Default cancel params (just agent_id)
local DefaultCancelParams = Action.ParamSpec:new({
  agent_id = { type = "number", required = true },
})

--- Default function to extract tracking key from cancel params (uses agent_id)
--- @param cancel_params ParamSpec Cancel parameters with agent_id field
--- @return number|string Tracking key
local function default_tracking_key_fn(cancel_params)
  ---@cast cancel_params table
  return cancel_params.agent_id
end

--- Create a new async action
--- @param name string Action name (e.g., "agent.walk_to")
--- @param params ParamSpec Parameter specification
--- @param validators table|nil Optional array of validator functions
--- @param options table|nil Options: cancel_params, cancel_validators, cancel_storage_key, cancel_tracking_key_fn
--- @return AsyncAction
function AsyncAction:new(name, params, validators, options)
  -- Create base Action instance first
  local instance = Action:new(name, params, validators)
  ---@cast instance AsyncAction
  
  -- Mark as async (used for metadata generation)
  instance.is_async = true
  instance.is_sync = false
  
  -- Set up cancel functionality
  local opts = options or {}
  instance.cancel_params = opts.cancel_params or DefaultCancelParams
  instance.cancel_validators = opts.cancel_validators or {}
  instance.cancel_storage_key = opts.cancel_storage_key  -- Must be set by action
  instance.cancel_tracking_key_fn = opts.cancel_tracking_key_fn or default_tracking_key_fn
  
  -- Set metatable to AsyncAction (which inherits from Action via metatable chain)
  setmetatable(instance, AsyncAction)
  
  return instance
end

--- Generate unique action_id for async tracking
--- Format: "{action_name}_{tick}_{agent_id}"
--- Example: "agent_walk_to_1234_0"
--- @param agent_id number Agent ID
--- @return string action_id Unique action identifier
--- @return number rcon_tick Game tick when action was queued
function AsyncAction:generate_action_id(agent_id)
  local rcon_tick = game.tick
  -- Convert action name to safe format (e.g., "agent.walk_to" -> "agent_walk_to")
  local action_name_safe = self.name:gsub("%.", "_")
  local action_id = string.format("%s_%d_%d", action_name_safe, rcon_tick, agent_id)
  return action_id, rcon_tick
end

--- Create standardized async result contract
--- Returns the standard async action response format expected by Python RconHelper
--- @param action_id string Unique action identifier
--- @param rcon_tick number Game tick when action was queued
--- @param extra_data table|nil Additional fields to include in result (e.g., {recipe = "iron-plate", count_queued = 5})
--- @return table Async result with {success=true, queued=true, action_id=..., tick=..., ...}
function AsyncAction:create_async_result(action_id, rcon_tick, extra_data)
  local result = {
    success = true,
    queued = true,
    action_id = action_id,
    tick = rcon_tick
  }
  
  -- Merge in any extra data (action-specific fields)
  if extra_data and type(extra_data) == "table" then
    for k, v in pairs(extra_data) do
      result[k] = v
    end
  end
  
  return result
end

--- Store tracking information for async action completion
--- Helper to standardize storage pattern across async actions
--- @param storage_key string Storage key (e.g., "walk_in_progress", "mine_resource_in_progress")
--- @param tracking_key string|number Key within storage table (e.g., agent_id, resource position)
--- @param action_id string Unique action identifier
--- @param rcon_tick number Game tick when action was queued
--- @param extra_data table|nil Additional tracking data to store
function AsyncAction:store_tracking(storage_key, tracking_key, action_id, rcon_tick, extra_data)
  if not storage[storage_key] then
    storage[storage_key] = {}
  end
  
  local tracking_data = {
    action_id = action_id,
    rcon_tick = rcon_tick
  }
  
  -- Merge in any extra tracking data
  if extra_data and type(extra_data) == "table" then
    for k, v in pairs(extra_data) do
      tracking_data[k] = v
    end
  end
  
  storage[storage_key][tracking_key] = tracking_data
end

--- Get tracking information for an async action
--- @param storage_key string Storage key
--- @param tracking_key string|number Key within storage table
--- @return table|nil Tracking data with {action_id, rcon_tick, ...} or nil if not found
function AsyncAction:get_tracking(storage_key, tracking_key)
  if not storage[storage_key] then
    return nil
  end
  return storage[storage_key][tracking_key]
end

--- Clear tracking information for a completed async action
--- @param storage_key string Storage key
--- @param tracking_key string|number Key within storage table
function AsyncAction:clear_tracking(storage_key, tracking_key)
  if storage[storage_key] and storage[storage_key][tracking_key] then
    storage[storage_key][tracking_key] = nil
  end
end

--- Prepare cancel parameters before running cancel action
--- Similar to Action:_pre_run but for cancel params
--- @param params ParamSpec|table|string Cancel parameter instance, raw params, or JSON string
--- @return ParamSpec Validated cancel ParamSpec instance
function AsyncAction:_pre_cancel(params)
  local instance
  
  -- Handle JSON string (same as Action:_pre_run)
  if type(params) == "string" then
    if helpers and helpers.json_to_table then
      local ok, decoded = pcall(helpers.json_to_table, params)
      if not ok or type(decoded) ~= "table" then
        error("Invalid JSON cancel params")
      end
      params = decoded
    else
      error("JSON decode unavailable in this context")
    end
  end
  
  -- Normalize to ParamSpec instance
  if type(params) == "table" and params.get_values then
    instance = params
  else
    instance = self.cancel_params:from_table(params or {})
  end
  
  -- Ensure validated
  if not instance:is_validated() then
    instance:validate()
  end
  
  -- Run cancel validators
  for i, validator in ipairs(self.cancel_validators) do
    local params_table = instance:get_values()
    local call_results = {pcall(validator, params_table)}
    local ok = call_results[1]
    local result = call_results[2]
    local error_msg = call_results[3]
    
    if not ok then
      error("Cancel validator " .. i .. " threw error: " .. tostring(result))
    elseif result == false then
      error("Cancel validation failed: " .. (error_msg or ("Validator " .. i .. " failed")))
    elseif result ~= true then
      error("Cancel validator " .. i .. " failed")
    end
  end
  
  return instance
end

--- Find active action tracking for cancel
--- @param cancel_params ParamSpec Cancel parameters
--- @return table|nil Tracking data or nil if not found
function AsyncAction:find_active_tracking(cancel_params)
  if not self.cancel_storage_key then
    error("cancel_storage_key not set for action: " .. tostring(self.name))
  end
  
  local tracking_key = self.cancel_tracking_key_fn(cancel_params)
  return self:get_tracking(self.cancel_storage_key, tracking_key)
end

--- Hook for action-specific cancel logic
--- Override this method in your AsyncAction subclass to implement cancel behavior
--- @param cancel_params ParamSpec Validated cancel parameters
--- @param tracking table|nil Active tracking data (if found)
--- @return table Cancel result with {success, cancelled, action_id, result={...}}
function AsyncAction:_do_cancel(cancel_params, tracking)
  -- Default implementation: just return success=false if no tracking found
  if not tracking then
    return {
      success = false,
      cancelled = false,
      error = "No active action found to cancel"
    }
  end
  
  -- Subclasses should override this to implement actual cancel logic
  error("_do_cancel must be overridden by AsyncAction subclass: " .. tostring(self.name))
end

--- Cancel an in-progress async action
--- @param params ParamSpec|table|string Cancel parameter instance, raw params, or JSON string
--- @return table Cancel result with {success, cancelled, action_id, result={...}}
function AsyncAction:cancel(params)
  local cancel_params = self:_pre_cancel(params)
  
  -- Find active tracking
  local tracking = self:find_active_tracking(cancel_params)
  
  -- Call action-specific cancel logic
  local cancel_result = self:_do_cancel(cancel_params, tracking)
  
  -- If cancellation was successful, clean up tracking
  if cancel_result.success and cancel_result.cancelled and tracking then
    local tracking_key = self.cancel_tracking_key_fn(cancel_params)
    self:clear_tracking(self.cancel_storage_key, tracking_key)
  end
  
  -- Standardize cancel result format
  local result = {
    success = cancel_result.success or false,
    cancelled = cancel_result.cancelled or false,
    action_id = (tracking and tracking.action_id) or cancel_result.action_id,
    result = cancel_result.result or {}
  }
  
  -- Merge in any additional fields from cancel_result
  for k, v in pairs(cancel_result) do
    if k ~= "success" and k ~= "cancelled" and k ~= "action_id" and k ~= "result" then
      result[k] = v
    end
  end
  
  return self:_post_run(result, cancel_params)
end

--- Create standardized cancel result
--- @param success boolean Whether cancel succeeded
--- @param cancelled boolean Whether there was something to cancel
--- @param action_id string|nil Action ID that was cancelled
--- @param extra_data table|nil Additional cancel result data
--- @return table Cancel result
function AsyncAction:create_cancel_result(success, cancelled, action_id, extra_data)
  local result = {
    success = success,
    cancelled = cancelled,
    action_id = action_id
  }
  
  if extra_data and type(extra_data) == "table" then
    for k, v in pairs(extra_data) do
      result[k] = v
    end
  end
  
  return result
end

return AsyncAction

