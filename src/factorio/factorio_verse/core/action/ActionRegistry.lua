-- factorio_verse/core/action/ActionRegistry.lua
-- Simple utilities to load action modules and expose their run methods for remote interface

local ActionRegistry = {}
ActionRegistry.__index = ActionRegistry

-- Enumerate known action modules under factorio_verse/actions/**/action.lua
-- Note: Factorio runtime cannot list files, so we keep a static list here.
local ACTION_MODULES = {
  -- agent
  "factorio_verse.actions.agent.walk.action",
  "factorio_verse.actions.agent.send_message.action",

  -- entity
  "factorio_verse.actions.entity.place.action",
  "factorio_verse.actions.entity.move.action",
  "factorio_verse.actions.entity.remove.action",
  "factorio_verse.actions.entity.set_recipe.action",
  "factorio_verse.actions.entity.connect.action",

  -- item
  "factorio_verse.actions.item.craft.action",
  "factorio_verse.actions.item.transfer.action",

  -- resources / research
  "factorio_verse.actions.mine_resource.action",
  "factorio_verse.actions.start_research.action",
}

--- Create a new registry instance
--- @return table
function ActionRegistry:new()
  local instance = {
    loaded = false,
    actions = {},          -- array of action instances
    actions_by_name = {},  -- name -> action instance
    events = {},           -- event_id -> {handler, ...}
  }
  setmetatable(instance, self)
  return instance
end

--- Load all actions listed in ACTION_MODULES. Safe to call multiple times.
function ActionRegistry:load()
  if self.loaded then return end

  for _, module_name in ipairs(ACTION_MODULES) do
    local ok, action_or_err = pcall(require, module_name)
    if ok and type(action_or_err) == "table" then
      local action = action_or_err
      if type(action.name) == "string" and type(action.run) == "function" then
        table.insert(self.actions, action)
        self.actions_by_name[action.name] = action

        -- Optionally collect event handlers defined on actions
        if type(action.events) == "table" then
          for event_id, handler in pairs(action.events) do
            if handler ~= nil then
              self.events[event_id] = self.events[event_id] or {}
              table.insert(self.events[event_id], handler)
            end
          end
        end
      end
    else
      -- Silently ignore missing/invalid modules to keep registry resilient
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
    if not (remote.interfaces and remote.interfaces["actions"]) then
      remote.add_interface("actions", iface)
    end
  end
end

return ActionRegistry:new()


