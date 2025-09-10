-- factorio_verse/core/action/ActionQueue.lua
-- Queued action execution system with batch processing capabilities

--- @class ActionQueue
local ActionQueue = {}
ActionQueue.__index = ActionQueue

--- @class QueuedAction
--- @field action_name string
--- @field params table
--- @field key string|nil Optional key for batch execution
--- @field timestamp number When the action was queued
--- @field priority number|nil Optional priority (higher = more important)

--- Create a new action queue instance
--- @param action_registry table|nil Optional ActionRegistry instance
--- @return ActionQueue
function ActionQueue:new(action_registry)
  local instance = {
    queue = {},                    -- array of QueuedAction
    queues_by_key = {},           -- key -> array of QueuedAction
    immediate_mode = true,        -- whether to execute actions immediately
    max_queue_size = 10000,       -- maximum queue size
    processing = false,           -- whether currently processing queue
    action_registry = action_registry or require("core.action.ActionRegistry"),
  }
  setmetatable(instance, self)
  return instance
end

--- Add an action to the queue
--- @param action_name string
--- @param params table
--- @param key string|nil Optional key for batch execution
--- @param priority number|nil Optional priority
--- @return boolean success
--- @return string|nil error_message
function ActionQueue:enqueue(action_name, params, key, priority)
  -- Check queue size limit
  if #self.queue >= self.max_queue_size then
    return false, "Queue is full (max size: " .. self.max_queue_size .. ")"
  end

  local queued_action = {
    action_name = action_name,
    params = params or {},
    key = key,
    timestamp = game and game.tick or 0,
    priority = priority or 0
  }

  -- Add to main queue
  table.insert(self.queue, queued_action)

  -- Add to key-specific queue if key provided
  if key then
    self.queues_by_key[key] = self.queues_by_key[key] or {}
    table.insert(self.queues_by_key[key], queued_action)
  end

  -- If in immediate mode, process immediately
  if self.immediate_mode and not key then
    return self:process_immediate(queued_action)
  end

  return true
end

--- Process a single action immediately (for immediate mode)
--- @param queued_action QueuedAction
--- @return boolean success
--- @return any result
--- @return string|nil error_message
function ActionQueue:process_immediate(queued_action)
  -- Ensure action registry is loaded
  if not self.action_registry then
    self.action_registry = require("core.action.ActionRegistry")
  end
  
  local action = self.action_registry:get(queued_action.action_name)
  
  if not action then
    return false, nil, "Action not found: " .. tostring(queued_action.action_name)
  end

  local ok, result, error_msg = pcall(function()
    return action:run(queued_action.params)
  end)

  if not ok then
    return false, nil, "Action execution failed: " .. tostring(result)
  end

  return true, result, error_msg
end

--- Process all actions in the queue
--- @return table results Array of {success, result, error_msg} for each action
function ActionQueue:process_all()
  if self.processing then
    return {{success = false, error_msg = "Already processing queue"}}
  end

  self.processing = true
  local results = {}

  -- Sort by priority (higher first), then by timestamp
  table.sort(self.queue, function(a, b)
    if a.priority ~= b.priority then
      return a.priority > b.priority
    end
    return a.timestamp < b.timestamp
  end)

  for i, queued_action in ipairs(self.queue) do
    local success, result, error_msg = self:process_immediate(queued_action)
    table.insert(results, {
      success = success,
      result = result,
      error_msg = error_msg,
      action_name = queued_action.action_name,
      key = queued_action.key
    })
  end

  -- Clear the queue after processing
  self.queue = {}
  self.queues_by_key = {}
  self.processing = false

  return results
end

--- Process actions for a specific key
--- @param key string
--- @return table results Array of {success, result, error_msg} for each action
function ActionQueue:process_key(key)
  if not key or not self.queues_by_key[key] then
    return {{success = false, error_msg = "No actions found for key: " .. tostring(key)}}
  end

  if self.processing then
    return {{success = false, error_msg = "Already processing queue"}}
  end

  self.processing = true
  local results = {}
  local key_queue = self.queues_by_key[key]

  -- Sort by priority (higher first), then by timestamp
  table.sort(key_queue, function(a, b)
    if a.priority ~= b.priority then
      return a.priority > b.priority
    end
    return a.timestamp < b.timestamp
  end)

  for i, queued_action in ipairs(key_queue) do
    local success, result, error_msg = self:process_immediate(queued_action)
    table.insert(results, {
      success = success,
      result = result,
      error_msg = error_msg,
      action_name = queued_action.action_name,
      key = queued_action.key
    })

    -- Remove from main queue
    for j, main_action in ipairs(self.queue) do
      if main_action == queued_action then
        table.remove(self.queue, j)
        break
      end
    end
  end

  -- Clear the key-specific queue
  self.queues_by_key[key] = nil
  self.processing = false

  return results
end

--- Get queue status information
--- @return table status
function ActionQueue:get_status()
  local key_counts = {}
  for key, queue in pairs(self.queues_by_key) do
    key_counts[key] = #queue
  end

  return {
    total_queued = #self.queue,
    processing = self.processing,
    immediate_mode = self.immediate_mode,
    key_counts = key_counts,
    max_queue_size = self.max_queue_size
  }
end

--- Clear all queued actions
--- @param key string|nil If provided, only clear actions for this key
function ActionQueue:clear(key)
  if key then
    -- Clear specific key
    if self.queues_by_key[key] then
      local key_queue = self.queues_by_key[key]
      -- Remove from main queue
      for i = #self.queue, 1, -1 do
        local action = self.queue[i]
        for _, key_action in ipairs(key_queue) do
          if action == key_action then
            table.remove(self.queue, i)
            break
          end
        end
      end
      self.queues_by_key[key] = nil
    end
  else
    -- Clear all
    self.queue = {}
    self.queues_by_key = {}
  end
end

--- Set immediate mode (true = execute immediately, false = queue only)
--- @param immediate boolean
function ActionQueue:set_immediate_mode(immediate)
  self.immediate_mode = immediate
end

--- Set maximum queue size
--- @param size number
function ActionQueue:set_max_queue_size(size)
  self.max_queue_size = size
end

--- Get queue-based remote interface for actions
--- @return table<string, function>
function ActionQueue:get_queue_remote_interface()
  local interface = {}
  
  -- Add queue management methods
  interface.enqueue = function(action_name, params, key, priority)
    return self:enqueue(action_name, params, key, priority)
  end
  
  interface.process_all = function()
    return self:process_all()
  end
  
  interface.process_key = function(key)
    return self:process_key(key)
  end
  
  interface.get_status = function()
    return self:get_status()
  end
  
  interface.clear = function(key)
    return self:clear(key)
  end
  
  interface.set_immediate_mode = function(immediate)
    return self:set_immediate_mode(immediate)
  end
  
  interface.set_max_queue_size = function(size)
    return self:set_max_queue_size(size)
  end
  
  -- Add convenience methods for each action type
  if not self.action_registry then
    self.action_registry = require("core.action.ActionRegistry")
  end
  
  local action_registry = self.action_registry
  if action_registry and action_registry.actions then
    for _, action in ipairs(action_registry.actions) do
      local action_name = action.name
      local safe_name = string.gsub(action_name, "%.", "_")
      
      -- Create queue versions of each action
      interface["queue_" .. action_name] = function(params, key, priority)
        return self:enqueue(action_name, params, key, priority)
      end
      
      interface["queue_" .. safe_name] = function(params, key, priority)
        return self:enqueue(action_name, params, key, priority)
      end
    end
  end
  
  return interface
end

--- Register the queue-based remote interface
function ActionQueue:register_queue_remote_interface()
  local interface_name = "action_queue"
  local iface = self:get_queue_remote_interface()
  if remote and remote.add_interface then
    if remote.interfaces[interface_name] then
      log("Removing " .. interface_name .. " interface")
      remote.remove_interface(interface_name)
    end
    log("Adding " .. interface_name .. " interface")
    remote.add_interface(interface_name, iface)
  end
end

return ActionQueue:new()
