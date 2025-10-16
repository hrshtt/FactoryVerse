-- control.lua: registers action run methods on a remote interface and hooks events

local action_registry = require("core.action.ActionRegistry")
local action_queue = require("core.action.ActionQueue")
local utils = require("utils")

local ok, mod = pcall(require, "actions.agent.walk.action")
if ok then
  log("Yeah even the action was loaded")
else
  log("Wait, what? The action was not loaded?")
  log(mod)
end

-- Load admin api
local admin_api = require("core.admin_api")
admin_api.load_helpers()
admin_api.load_commands()

-- Load snapshot modules for event registration
local EntitiesSnapshot = require("core.snapshot.EntitiesSnapshot")
local ResourceSnapshot = require("core.snapshot.ResourceSnapshot")

-- Setup mutation logging
local MutationConfig = require("core.mutation.MutationConfig")
-- Use "minimal" profile by default - only action-based logging
-- Change to "full" to enable tick-based autonomous mutation logging
-- Change to "disabled" to turn off mutation logging entirely
MutationConfig.setup("minimal")

-- Register remote interface containing all actions' run methods
local function register_remote_interface()
  action_registry:register_remote_interface()
  action_queue:register_queue_remote_interface()
end

-- Hook any events exposed by actions (e.g., on_tick runners)
local function register_events()
  local events = action_registry:get_events()
  for event_id, handler in pairs(events) do
    -- Register one aggregated handler per event id
    script.on_event(event_id, handler)
  end
end

register_remote_interface()
register_events()

-- Register snapshot recurring events
local entities_events = EntitiesSnapshot.get_events()
if entities_events and entities_events.tick_interval then
  script.on_nth_tick(entities_events.tick_interval, entities_events.handler)
  log("Registered entities recurring snapshot (interval: " .. entities_events.tick_interval .. ")")
end

local resource_events = ResourceSnapshot.get_events()
if resource_events and resource_events.tick_interval then
  script.on_nth_tick(resource_events.tick_interval, resource_events.handler)
  log("Registered resources recurring snapshot (interval: " .. resource_events.tick_interval .. ")")
end

-- Force players to spectator when they join
script.on_event(defines.events.on_player_joined_game, function(event)
  log("hello from on_player_joined_game")
  utils.players_to_spectators()
end)

script.on_nth_tick(15, function()
  utils.chart_scanners()
end)

-- Perform registrations at different lifecycle points to be safe on reloads
script.on_init(function()
  log("hello from on_init")
  -- Configure action queue for non-blocking intent ingestion
  action_queue:set_immediate_mode(false)
  action_queue:set_max_queue_size(10000)
  -- Restore any persisted state
  action_queue:load_from_global()
end)

script.on_load(function()
  log("hello from on_load")
  admin_api.load_helpers()
  admin_api.load_commands()
  -- Restore persisted queue state after load
  action_queue:load_from_global()
end)

script.on_configuration_changed(function()
  log("hello from on_configuration_changed")
end)

-- Bounded action processing each tick (deterministic, fair executor)
local MAX_ACTIONS_PER_TICK = 10
script.on_nth_tick(1, function(event)
  if action_queue and action_queue.process_some then
    action_queue:process_some(MAX_ACTIONS_PER_TICK)
  end
end)
