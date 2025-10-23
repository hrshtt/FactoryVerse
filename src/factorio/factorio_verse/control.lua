-- control.lua: registers action run methods on a remote interface and hooks events

local action_registry = require("core.action.ActionRegistry")
local action_queue = require("core.action.ActionQueue")
local utils = require("utils")

-- Load admin api
local admin_api = require("core.admin_api")
admin_api.load_helpers()
admin_api.load_commands()

-- Load snapshot modules for event registration
local Snapshot = require("core.snapshot.Snapshot")
local MapDiscovery = require("core.MapDiscovery")

local function on_player_created(e)
  local player = game.get_player(e.player_index)
  if player then
    local character = player.character
    player.character = nil
    if character then
      character.destroy()
    end
  end
end

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
local snapshot = Snapshot:get_instance()

-- Recurring entity status (every 60 ticks)
script.on_nth_tick(60, function(event)
  snapshot:take_recurring_status()
end)

-- Resource depletion event
script.on_event(defines.events.on_resource_depleted, function(event)
  if event.entity and event.entity.valid then
    local chunk_x = math.floor(event.entity.position.x / 32)
    local chunk_y = math.floor(event.entity.position.y / 32)
    snapshot:take_chunk_snapshot(chunk_x, chunk_y, {components = {"resources"}})
  end
end)

-- Chunk charted event
script.on_event(defines.events.on_chunk_charted, function(event)
  local chunk_x = event.area.left_top.x / 32
  local chunk_y = event.area.left_top.y / 32
  snapshot:take_chunk_snapshot(chunk_x, chunk_y, {components = {"entities", "resources"}})
end)

-- Register map discovery events
local map_discovery_events = MapDiscovery.get_events()
if map_discovery_events and map_discovery_events.tick_interval then
  script.on_nth_tick(map_discovery_events.tick_interval, map_discovery_events.handler)
  log("Registered map discovery (interval: " .. map_discovery_events.tick_interval .. ")")
end


-- Force players to spectator when they join
script.on_event(defines.events.on_player_joined_game, function(event)
  log("hello from on_player_joined_game")
  utils.players_to_spectators()
end)

-- script.on_nth_tick(15, function()
--   utils.chart_scanners()
-- end)

script.on_event(defines.events.on_player_created, on_player_created)

-- Perform registrations at different lifecycle points to be safe on reloads
script.on_init(function()
  log("hello from on_init")
  -- Configure action queue for non-blocking intent ingestion
  action_queue:set_immediate_mode(false)
  action_queue:set_max_queue_size(10000)
  -- Restore any persisted state
  action_queue:load_from_global()
  
  -- Take initial snapshot asynchronously
  local snapshot = Snapshot:get_instance()
  snapshot:take_map_snapshot({
    async = true,
    chunks_per_tick = 2,
    components = {"entities", "resources"}
  })
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
