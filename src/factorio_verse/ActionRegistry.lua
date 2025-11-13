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
  "actions.agent.walk",
  "actions.agent.teleport",
  "actions.agent.place_entity",
  "actions.agent.place_in_line",
  "actions.agent.crafting",
  "actions.agent.mining",
  "actions.agent.research",

  -- entity
  "actions.entity.rotate",
  "actions.entity.pickup",
  "actions.entity.set_recipe",
  "actions.entity.inventory_get_item",
  "actions.entity.inventory_set_item",
  "actions.entity.inventory_set_limit",
  "actions.entity.inventory_set_filter",
}

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
    
    -- Validators removed - validation now handled by:
    -- 1. ParamSpec format validation (in Action._pre_run)
    -- 2. GameContext resolution (in action _pre_run overrides)
    -- 3. Logical validation (in action run() methods)

    table.insert(self.actions, action)
    self.actions_by_name[action.name] = action

    -- Auto-register cancel action for AsyncActions
    if action.is_async and type(action.cancel) == "function" and action.cancel_params then
      -- For crafting, use "dequeue" instead of "cancel" in the name
      local cancel_name = (action.name == "agent.crafting.enqueue") and "agent.crafting.dequeue" or (action.name .. ".cancel")
      
      local cancel_action = {
        name = cancel_name,
        run = function(self, params) return action:cancel(params) end,
        is_sync = true,   -- Cancel is always sync
        is_async = false, -- Cancel is always sync
        cancel_params = action.cancel_params,
        set_game_state = function(self, game_state) action:set_game_state(game_state) end,
      }
      table.insert(self.actions, cancel_action)
      self.actions_by_name[cancel_name] = cancel_action
      log("Auto-registered cancel action: " .. cancel_name)
    end

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
      -- Handle return formats:
      -- 1) Array of actions {action1, action2, ...} (e.g., walk.lua returns {WalkToAction, WalkCancelAction})
      -- 2) Table with field `action` (standard format: {action = Action, params = Params})
      if type(action_or_err[1]) == "table" then
        -- Array format: multiple actions in one file
        for _, a in ipairs(action_or_err) do
          register_action(a, module_name)
        end
      elseif type(action_or_err.action) == "table" then
        -- Standard format: {action = Action, params = Params}
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

--- Convert action name to metadata key format
--- "agent.crafting.enqueue" -> "agent_crafting_enqueue"
--- @param action_name string
--- @return string
local function action_name_to_metadata_key(action_name)
  local result = string.gsub(action_name, "%.", "_")
  return result
end

--- Return action metadata (sync vs async classification)
--- Dynamically generated from registered actions
--- Source of truth for Python-side action contracts
--- @return table<string, table> metadata with is_async flags
function ActionRegistry:get_action_metadata()
  self:load()  -- Ensure actions are loaded
  
  local metadata = {}
  
  for _, action in ipairs(self.actions) do
    if action.name then
      local metadata_key = action_name_to_metadata_key(action.name)
      -- Use is_async if explicitly set, otherwise derive from is_sync
      local is_async = action.is_async
      if is_async == nil then
        is_async = not (action.is_sync == true)
      end
      
      metadata[metadata_key] = {
        is_async = is_async
      }
    end
  end
  
  return metadata
end

return ActionRegistry:new()

