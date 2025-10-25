-- factorio_verse/core/action/ActionRegistry.lua
-- Simple utilities to load action modules and expose their run methods for remote interface

local ValidatorRegistry = require("core.action.ValidatorRegistry")

local ActionRegistry = {}
ActionRegistry.__index = ActionRegistry

-- Enumerate known action modules under factorio_verse/actions/**/action.lua
-- Note: Factorio runtime cannot list files, so we keep a static list here.
local ACTION_MODULES = {
  -- agent
  "actions.agent.walk.action",
  -- "actions.agent.send_message.action",

  -- entity
  "actions.entity.place.action",
  "actions.entity.rotate.action",
  "actions.entity.pickup.action",
  "actions.entity.set_recipe.action",
  "actions.entity.inventory.set_item.action",
  "actions.entity.inventory.get_item.action",
  "actions.entity.inventory.set_limit.action",
  -- "actions.entity.move.action",
  -- "actions.entity.remove.action",
  -- "actions.entity.connect.action",

  -- item
  "actions.crafting.craft_sync.action",
  -- "actions.item.transfer.action",

  -- resources / research
  "actions.mine_resource.action",
  "actions.research.enqueue_research.action",
  -- "actions.research.dequeue_research.action",
}

--- Create a new registry instance
--- @return table
function ActionRegistry:new()
  local instance = {
    loaded = false,
    actions = {},         -- array of action instances
    actions_by_name = {}, -- name -> action instance
    events = {},          -- event_id -> {handler, ...}
  }
  setmetatable(instance, self)
  return instance
end

--- Load all actions listed in ACTION_MODULES. Safe to call multiple times.
function ActionRegistry:load()
  if self.loaded then return end

  local validator_registry = ValidatorRegistry:new()

  validator_registry:build_registry()


  -- Helper to register a single action instance
  local function register_action(action)
    if not (type(action) == "table" and type(action.name) == "string" and type(action.run) == "function") then
      return
    end
    local ok2, err = pcall(function()
      action:attach_validators(validator_registry:get_validations(action.name))
    end)
    if ok2 then
      log("Attached validator to action: " .. tostring(action.name))
    else
      log("Error attaching validator to action: " .. tostring(action.name))
      log(err)
    end

    table.insert(self.actions, action)
    self.actions_by_name[action.name] = action

    if type(action.events) == "table" then
      for event_id, handler in pairs(action.events) do
        if handler ~= nil then
          self.events[event_id] = self.events[event_id] or {}
          table.insert(self.events[event_id], handler)
        end
      end
    end
  end

  for _, module_name in ipairs(ACTION_MODULES) do
    local ok, action_or_err = pcall(require, module_name)
    if ok and type(action_or_err) == "table" then
      -- Cases:
      -- 1) Single action table with name/run
      -- 2) Array of actions {action1, action2, ...}
      -- 3) Table with field `action`
      if type(action_or_err.name) == "string" and type(action_or_err.run) == "function" then
        register_action(action_or_err)
      elseif type(action_or_err[1]) == "table" then
        for _, a in ipairs(action_or_err) do
          register_action(a)
        end
      elseif type(action_or_err.action) == "table" then
        register_action(action_or_err.action)
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

--- Return a mapping suitable for remote.add_interface("actions", ...)
--- Keys are action names (e.g., "agent.walk"); values call action:run(params)
--- For convenience, also expose underscore versions (e.g., "agent_walk").
--- @return table<string, function>
function ActionRegistry:get_remote_interface()
  self:load()

  local interface = {}
  for _, action in ipairs(self.actions) do
    local action_name = action.name
    local safe_name = string.gsub(action_name, "%.", "_")

    local runner = function(params)
      return action:run(params)
    end

    interface[action_name] = runner
    interface[safe_name] = interface[safe_name] or runner
  end
  return interface
end

--- Get an action by its name.
--- @param name string
--- @return table|nil
function ActionRegistry:get(name)
  self:load()
  return self.actions_by_name[name]
end

--- Return aggregated event handlers defined by actions (if any)
--- @return table<number, function>
function ActionRegistry:get_events()
  self:load()
  local aggregated = {}
  for event_id, handlers in pairs(self.events) do
    if type(handlers) == "table" and #handlers > 0 then
      aggregated[event_id] = function(event)
        for _, handler in ipairs(handlers) do
          handler(event)
        end
      end
    end
  end
  return aggregated
end

--- Register the remote interface named "actions" with the game runtime
--- Safe to call multiple times; Factorio will error if an interface already exists,
--- so prefer calling this once from control.lua.
function ActionRegistry:register_remote_interface()
  local iface = self:get_remote_interface()
  if remote and remote.add_interface then
    if remote.interfaces["actions"] then
      log("Removing actions interface")
      remote.remove_interface("actions")
    end
    log("Adding actions interface")
    remote.add_interface("actions", iface)
  end
end

return ActionRegistry:new()
