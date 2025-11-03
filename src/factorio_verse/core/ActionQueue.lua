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
--- @field seq number Monotonic sequence for deterministic ordering
--- @field idempotency_key string|nil Optional deduplication key
--- @field correlation_id string|nil Optional correlation id for result polling

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
    -- Deterministic sequencing and fairness state
    seq_counter = 0,              -- monotonic sequence for tie-breaking
    key_order = {},               -- array of keys for round-robin fairness
    next_key_index = 1,           -- next index into key_order to schedule
    key_index_by_key = {},        -- map key -> index in key_order (best-effort; may drift before cleanup)
    -- Result tracking and idempotency
    results_by_correlation = {},  -- correlation_id -> {status, result, error_msg, tick, action_name, key}
    enqueued_by_idempotency = {}, -- idempotency_key -> true
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
--- @return any result_or_error When immediate mode executes: result; otherwise nil
--- @return string|nil error_message When immediate mode executes: error message; otherwise nil
function ActionQueue:enqueue(action_name, params, key, priority)
  -- Check queue size limit
  if #self.queue >= self.max_queue_size then
    return false, "Queue is full (max size: " .. self.max_queue_size .. ")"
  end

  -- Support options table in place of priority for extended metadata
  local options = nil
  local effective_priority = 0
  if type(priority) == "table" then
    options = priority
    effective_priority = options.priority or 0
  else
    effective_priority = priority or 0
  end

  local idempotency_key = (options and options.idempotency_key)
    or (type(params) == "table" and params._idempotency_key)
  local correlation_id = (options and options.correlation_id)
    or (type(params) == "table" and params._correlation_id)

  if idempotency_key and self.enqueued_by_idempotency[idempotency_key] then
    -- Deduplicate silently
    return true
  end

  -- Deterministic sequence number
  self.seq_counter = (self.seq_counter or 0) + 1

  local queued_action = {
    action_name = action_name,
    params = params or {},
    key = key,
    timestamp = game and game.tick or 0,
    priority = effective_priority,
    seq = self.seq_counter,
    idempotency_key = idempotency_key,
    correlation_id = correlation_id
  }

  -- Add to main queue
  table.insert(self.queue, queued_action)

  -- Add to key-specific queue if key provided
  if key then
    self.queues_by_key[key] = self.queues_by_key[key] or {}
    table.insert(self.queues_by_key[key], queued_action)

    -- Track key order for fairness if first time seeing this key
    if not self.key_index_by_key[key] then
      table.insert(self.key_order, key)
      self.key_index_by_key[key] = #self.key_order
    end
  end

  -- If in immediate mode, process immediately
  if self.immediate_mode and not key then
    local ok, result, error_msg = self:process_immediate(queued_action)
    self:save_to_global()
    return ok, result, error_msg
  end

  self:save_to_global()
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

  local success, ret_result, ret_error
  if not ok then
    success = false
    ret_result = nil
    ret_error = "Action execution failed: " .. tostring(result)
  else
    success = true
    ret_result = result
    ret_error = error_msg
  end

  -- Record result if correlation id provided
  if queued_action.correlation_id then
    self.results_by_correlation[queued_action.correlation_id] = {
      status = success and "success" or "error",
      result = ret_result,
      error_msg = ret_error,
      tick = game and game.tick or queued_action.timestamp,
      action_name = queued_action.action_name,
      key = queued_action.key
    }
  end

  -- Mark idempotency key as seen
  if queued_action.idempotency_key then
    self.enqueued_by_idempotency[queued_action.idempotency_key] = true
  end

  return success, ret_result, ret_error
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

  self:save_to_global()
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

  self:save_to_global()
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
      -- Remove key from fairness structures
      local idx = self.key_index_by_key[key]
      if idx then
        table.remove(self.key_order, idx)
        self.key_index_by_key[key] = nil
        -- Rebuild index map
        for i, k in ipairs(self.key_order) do
          self.key_index_by_key[k] = i
        end
      end
    end
  else
    -- Clear all
    self.queue = {}
    self.queues_by_key = {}
    self.key_order = {}
    self.key_index_by_key = {}
  end
  self:save_to_global()
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

--- Process up to max_count actions with per-key fairness and deterministic ordering
--- @param max_count number
--- @return number processed_count
function ActionQueue:process_some(max_count)
  local to_process = max_count or 1
  if to_process <= 0 then return 0 end
  if self.processing then return 0 end

  self.processing = true
  local processed = 0

  local function process_from_key_queue(idx)
    local key = self.key_order[idx]
    if not key then return false end
    local key_queue = self.queues_by_key[key]
    if not key_queue or #key_queue == 0 then
      -- Remove empty key and adjust indices
      table.remove(self.key_order, idx)
      self.key_index_by_key[key] = nil
      for i, k in ipairs(self.key_order) do
        self.key_index_by_key[k] = i
      end
      return false
    end
    -- FIFO within key (enqueue order carries seq)
    local qa = table.remove(key_queue, 1)
    -- Remove from main queue
    for j, main_action in ipairs(self.queue) do
      if main_action == qa then
        table.remove(self.queue, j)
        break
      end
    end
    self:process_immediate(qa)
    return true
  end

  while processed < to_process do
    local did_any = false

    -- Round-robin across keys
    if #self.key_order > 0 then
      local start = self.next_key_index or 1
      if start > #self.key_order then start = 1 end

      local attempts = 0
      while attempts < #self.key_order and processed < to_process do
        local idx = ((start + attempts - 1) % math.max(#self.key_order, 1)) + 1
        if process_from_key_queue(idx) then
          processed = processed + 1
          did_any = true
          start = idx + 1
          if start > #self.key_order then start = 1 end
          break
        else
          attempts = attempts + 1
        end
      end
      self.next_key_index = start
    end

    if processed >= to_process then break end

    -- Process any non-keyed actions
    local idx_non_key = nil
    for i, qa in ipairs(self.queue) do
      if not qa.key then
        idx_non_key = i
        break
      end
    end
    if idx_non_key then
      local qa = table.remove(self.queue, idx_non_key)
      self:process_immediate(qa)
      processed = processed + 1
      did_any = true
    end

    if not did_any then
      break
    end
  end

  self.processing = false
  self:save_to_global()
  return processed
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

  interface.get_result = function(correlation_id)
    if not correlation_id then return nil end
    return self.results_by_correlation[correlation_id]
  end

  interface.get_and_clear_result = function(correlation_id)
    if not correlation_id then return nil end
    local res = self.results_by_correlation[correlation_id]
    self.results_by_correlation[correlation_id] = nil
    self:save_to_global()
    return res
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

--- Persist internal state into Factorio's global table
function ActionQueue:save_to_global()
  if not global then return end
  storage.factoryverse_action_queue = {
    queue = self.queue,
    queues_by_key = self.queues_by_key,
    immediate_mode = self.immediate_mode,
    max_queue_size = self.max_queue_size,
    seq_counter = self.seq_counter,
    key_order = self.key_order,
    next_key_index = self.next_key_index,
    results_by_correlation = self.results_by_correlation,
    enqueued_by_idempotency = self.enqueued_by_idempotency,
  }
end

--- Restore internal state from Factorio's global table
function ActionQueue:load_from_global()
  if not storage then return end
  local data = storage.factoryverse_action_queue
  if not data then return end
  self.queue = data.queue or {}
  self.queues_by_key = data.queues_by_key or {}
  self.immediate_mode = (data.immediate_mode ~= nil) and data.immediate_mode or self.immediate_mode
  self.max_queue_size = data.max_queue_size or self.max_queue_size
  self.seq_counter = data.seq_counter or 0
  self.key_order = data.key_order or {}
  self.next_key_index = data.next_key_index or 1
  self.results_by_correlation = data.results_by_correlation or {}
  self.enqueued_by_idempotency = data.enqueued_by_idempotency or {}
  -- Rebuild key index map
  self.key_index_by_key = {}
  for i, k in ipairs(self.key_order) do
    self.key_index_by_key[k] = i
  end
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
