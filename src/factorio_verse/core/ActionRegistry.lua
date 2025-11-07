-- factorio_verse/core/ActionRegistry.lua
-- Action orchestration: loading, validation, interface creation, and event aggregation

-- ============================================================================
-- TOP-LEVEL REQUIRES (must be at module scope)
-- ============================================================================

local Action = require("types.Action")

-- ============================================================================
-- ACTION MODULE LIST
-- ============================================================================

local ACTION_MODULES = {
  -- agent
  "actions.agent.walk.action",
  "actions.agent.teleport.action",
  "actions.agent.place_entity.action",

  -- agent crafting
  "actions.agent.crafting.enqueue.action",
  "actions.agent.crafting.cancel.action",

  -- entity
  "actions.entity.place_line.action",
  "actions.entity.rotate.action",
  "actions.entity.pickup.action",
  "actions.entity.set_recipe.action",

  -- entity inventory
  "actions.entity.inventory.set_item.action",
  "actions.entity.inventory.get_item.action",
  "actions.entity.inventory.set_limit.action",

  -- resources
  "actions.mining.action",

  -- research
  "actions.research.enqueue_research.action",
  "actions.research.dequeue_research.action",
}

-- ============================================================================
-- VALIDATOR PRE-LOADING (hierarchical loading based on action name nesting)
-- ============================================================================

--- Extract action name from action module path
--- "actions.entity.inventory.set_item.action" -> "entity.inventory.set_item"
--- @param module_path string Action module path
--- @return string Action name
local function extract_action_name(module_path)
  -- Remove "actions." prefix and ".action" suffix
  local name = string.gsub(module_path, "^actions%.", "")
  name = string.gsub(name, "%.action$", "")
  return name
end

--- Generate hierarchical validator paths for an action name
--- For "entity.inventory.set_item", returns:
---   {"actions.validator", "actions.entity.validator", 
---    "actions.entity.inventory.validator", "actions.entity.inventory.set_item.validator"}
--- @param action_name string Action name like "entity.place"
--- @return table<string> Array of validator module paths
local function get_validator_paths(action_name)
  local paths = {}
  table.insert(paths, "actions.validator") -- Root validator always included
  
  -- Split action name by dots and build progressively longer paths
  local parts = {}
  for part in string.gmatch(action_name, "[^.]+") do
    table.insert(parts, part)
  end
  
  local current_path = "actions"
  for i = 1, #parts do
    current_path = current_path .. "." .. parts[i]
    table.insert(paths, current_path .. ".validator")
  end
  
  return paths
end

--- Pre-load all validator modules at top level
--- Maps validator_path -> validator_module (table of functions)
local VALIDATORS_BY_PATH = {}

do
  -- Collect all unique validator paths from all actions
  local validator_paths_set = {}
  
  -- Always include root validator
  validator_paths_set["actions.validator"] = true
  
  -- Generate paths for each action module
  for _, module_path in ipairs(ACTION_MODULES) do
    local action_name = extract_action_name(module_path)
    local paths = get_validator_paths(action_name)
    for _, path in ipairs(paths) do
      validator_paths_set[path] = true
    end
  end
  
  -- Require all validator modules at top level
  for validator_path, _ in pairs(validator_paths_set) do
    local ok, validator_module = pcall(require, validator_path)
    if ok and type(validator_module) == "table" then
      log("Loaded validator module: " .. validator_path)
      VALIDATORS_BY_PATH[validator_path] = validator_module
    end
  end
end

--- Load validators for an action from pre-loaded validator modules
--- Validator modules always return an array of functions
--- @param action_name string Action name like "entity.place"
--- @return table<function> Array of validator functions
local function load_validators(action_name)
  local validators = {}
  local validator_paths = get_validator_paths(action_name)
  
  for _, validator_path in ipairs(validator_paths) do
    local validator_module = VALIDATORS_BY_PATH[validator_path]
    if validator_module then
      -- Validator modules always return an array of functions
      for _, validator_func in ipairs(validator_module) do
        table.insert(validators, validator_func)
      end
    end
  end
  
  return validators
end

-- ============================================================================
-- ACTION REGISTRY CLASS
-- ============================================================================

--- @class ActionRegistry
--- @field loaded boolean
--- @field actions table<Action> Array of action instances
--- @field actions_by_name table<string, Action> name -> action instance
--- @field events table<number, table<function>> event_id -> {handler, ...}
local ActionRegistry = {}
ActionRegistry.__index = ActionRegistry

--- Create a new registry instance
--- @return ActionRegistry
function ActionRegistry:new()
  local instance = {
    loaded = false,
    actions = {},          -- array of action instances
    actions_by_name = {},  -- name -> action instance
    events = {},          -- event_id -> {handler, ...}
  }
  setmetatable(instance, self)
  return instance
end

--- Load all actions listed in ACTION_MODULES. Safe to call multiple times.
function ActionRegistry:load()
  if self.loaded then return end

  -- Helper to register a single action instance
  local function register_action(action, module_path)
    if not (type(action) == "table" and type(action.name) == "string" and type(action.run) == "function") then
      return
    end
    
    -- Load validators hierarchically
    -- Use module_path to determine validator location (e.g., "actions.mining.action" -> "mining")
    -- Fallback to action.name if module_path not provided
    local ok, err = pcall(function()
      local validator_base_name = module_path and extract_action_name(module_path) or action.name
      local validators = load_validators(validator_base_name)
      action:attach_validators(validators)
      if #validators > 0 then
        log("Attached " .. #validators .. " validator(s) to action: " .. tostring(action.name) .. " (from " .. validator_base_name .. ")")
      end
    end)
    if not ok then
      log("Error attaching validator to action: " .. tostring(action.name))
      log(err)
    end

    table.insert(self.actions, action)
    self.actions_by_name[action.name] = action

    -- Collect event handlers (static handlers that don't need game_state)
    if type(action.events) == "table" then
      for event_id, handler in pairs(action.events) do
        if handler ~= nil then
          self.events[event_id] = self.events[event_id] or {}
          table.insert(self.events[event_id], handler)
        end
      end
    end
    
    -- Store action reference for lazy event creation (if _create_events exists)
    -- These will be resolved when get_events() is called (after game_state is set)
    if type(action._create_events) == "function" then
      action._needs_lazy_events = true
    end
  end

  -- Load all action modules
  for _, module_name in ipairs(ACTION_MODULES) do
    local ok, action_or_err = pcall(require, module_name)
    if ok and type(action_or_err) == "table" then
      -- Handle different return formats:
      -- 1) Single action table with name/run
      -- 2) Array of actions {action1, action2, ...}
      -- 3) Table with field `action`
      if type(action_or_err.name) == "string" and type(action_or_err.run) == "function" then
        register_action(action_or_err, module_name)
      elseif type(action_or_err[1]) == "table" then
        for _, a in ipairs(action_or_err) do
          register_action(a, module_name)
        end
      elseif type(action_or_err.action) == "table" then
        register_action(action_or_err.action, module_name)
      else
        log("Module did not return an action: " .. module_name)
      end
    else
      log("Error loading action: " .. module_name)
      log(action_or_err)
    end
  end

  self.loaded = true
end

--- Get action by name
--- @param name string Action name
--- @return Action|nil
function ActionRegistry:get(name)
  self:load()
  return self.actions_by_name[name]
end

--- Initialize all actions with game_state (must be called before get_action_interface)
--- @param game_state GameState instance
function ActionRegistry:init_actions(game_state)
  self:load()
  for _, action in ipairs(self.actions) do
    if type(action.set_game_state) == "function" then
      action:set_game_state(game_state)
    end
  end
end

--- Return action remote interface mapping
--- Keys are action names (e.g., "agent.walk"); values call action:run(params)
--- For convenience, also expose underscore versions (e.g., "agent_walk").
--- @return table<string, function> Remote interface for actions
function ActionRegistry:get_action_interface()
  self:load()

  local interface = {}
  for _, action in ipairs(self.actions) do
    local action_name = action.name
    local safe_name = string.gsub(action_name, "%.", "_")

    -- Actions now have game_state stored in instance
    local runner = function(params)
      return action:run(params)
    end

    -- interface[action_name] = runner
    interface[safe_name] = interface[safe_name] or runner
  end
  return interface
end

--- Return aggregated event handlers defined by actions
--- Aggregates all action events by event_id for registration in control.lua
--- Events are of type: defined event (defines.events.*), on_tick (defines.events.on_tick), or nth_tick
--- Note: Actions must be initialized with game_state (via init_actions) before calling this
--- @return table<number, table<function>> event_id -> {handler, ...}
function ActionRegistry:get_events()
  self:load()
  local aggregated = {}
  
  -- Regular event handlers (static, don't need game_state)
  for event_id, handlers in pairs(self.events) do
    if type(handlers) == "table" and #handlers > 0 then
      aggregated[event_id] = aggregated[event_id] or {}
      for _, handler in ipairs(handlers) do
        table.insert(aggregated[event_id], handler)
      end
    end
  end
  
  -- Lazy event creation (for handlers that need game_state via action.game_state)
  -- These are created on-demand after game_state is set
  for _, action in ipairs(self.actions) do
    if action._create_events and action.game_state and type(action._create_events) == "function" then
      local action_events = action._create_events(action)
      for event_id, handler in pairs(action_events) do
        if handler ~= nil then
          aggregated[event_id] = aggregated[event_id] or {}
          table.insert(aggregated[event_id], handler)
        end
      end
    end
  end
  
  return aggregated
end

--- Return action metadata (sync vs async classification)
--- Source of truth for Python-side action contracts
--- @return table<string, table> metadata with is_async flags
function ActionRegistry:get_action_metadata()
  return {
    -- ASYNC ACTIONS (complete across multiple ticks, send UDP completion)
    mine_resource = { is_async = true },
    agent_walk = { is_async = true },
    agent_walk_to = { is_async = true },
    agent_crafting_enqueue = { is_async = true },
    agent_crafting_cancel = { is_async = false },
    
    -- SYNC ACTIONS (complete in same RCON call)
    agent_teleport = { is_async = false },
    agent_place_entity = { is_async = false },
    agent_walk_cancel = { is_async = false },
    entity_rotate = { is_async = false },
    entity_pickup = { is_async = false },
    entity_set_recipe = { is_async = false },
    entity_inventory_set_item = { is_async = false },
    entity_inventory_get_item = { is_async = false },
    entity_inventory_set_limit = { is_async = false },
    enqueue_research = { is_async = false },
  }
end

return ActionRegistry:new()

