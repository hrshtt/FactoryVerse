-- control.lua: Central event dispatcher using aggregation pattern
-- All modules export get_events() which returns {event_id -> handler}
-- This file aggregates them and registers each event once with script.on_event

local action_registry = require("core.action.ActionRegistry")
local action_queue = require("core.action.ActionQueue")
local utils = require("utils")

-- Load admin api
local admin_api = require("core.admin_api")
admin_api.load_helpers()
admin_api.load_commands()

-- Load modules that export events
local Snapshot = require("core.snapshot.Snapshot")
local GameState = require("core.game_state.GameState"):new()

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

-- ============================================================================
-- EVENT DISPATCHER PATTERN
-- ============================================================================
-- Central place to aggregate events from all modules and register them once

local function count_keys(tbl)
    local count = 0
    for _ in pairs(tbl or {}) do
        count = count + 1
    end
    return count
end

local function aggregate_all_events()
    local all_handlers = {} -- {event_id -> [handler1, handler2, ...], ...}
    local nth_tick_handlers = {} -- {tick_interval -> [handler1, handler2, ...], ...}
    
    local function add_event_handler(event_id, handler)
        if event_id and handler then
            all_handlers[event_id] = all_handlers[event_id] or {}
            table.insert(all_handlers[event_id], handler)
        end
    end
    
    local function add_nth_tick_handler(tick_interval, handler)
        if tick_interval and handler then
            nth_tick_handlers[tick_interval] = nth_tick_handlers[tick_interval] or {}
            table.insert(nth_tick_handlers[tick_interval], handler)
        end
    end
    
    -- 1. Action Registry Events
    local action_events = action_registry:get_events()
    for event_id, handler in pairs(action_events or {}) do
        add_event_handler(event_id, handler)
    end
    
    -- 2. Snapshot Events (resource depletion, chunk charted)
    local snapshot = Snapshot:get_instance()
    local snapshot_events = snapshot:get_events()
    for event_id, handler in pairs(snapshot_events or {}) do
        add_event_handler(event_id, handler)
    end
    
    -- 2b. Snapshot nth_tick Events (recurring snapshots)
    local snapshot_nth_tick_events = snapshot:get_nth_tick_handlers()
    for tick_interval, handler in pairs(snapshot_nth_tick_events or {}) do
        add_nth_tick_handler(tick_interval, handler)
    end
    
    -- 3. Map Discovery nth_tick Events
    local map_discovery_nth_tick_events = GameState:map_discovery_nth_tick_handlers()
    for tick_interval, handler in pairs(map_discovery_nth_tick_events or {}) do
        add_nth_tick_handler(tick_interval, handler)
    end
    
    -- 4. Player Events (custom handlers)
    add_event_handler(defines.events.on_player_created, on_player_created)
    add_event_handler(defines.events.on_player_joined_game, function(event)
        log("hello from on_player_joined_game")
        utils.players_to_spectators()
    end)
    
    return all_handlers, nth_tick_handlers
end

local function register_all_events()
    local all_handlers, nth_tick_handlers = aggregate_all_events()
    
    -- Register standard events (event_id -> aggregated handler)
    for event_id, handlers_list in pairs(all_handlers) do
        script.on_event(event_id, function(event)
            for _, handler in ipairs(handlers_list) do
                local ok, err = pcall(handler, event)
                if not ok then
                    log("Error in event handler for " .. tostring(event_id) .. ": " .. tostring(err))
                end
            end
        end)
    end
    
    -- Register on_nth_tick events
    for tick_interval, handlers_list in pairs(nth_tick_handlers) do
        script.on_nth_tick(tick_interval, function(event)
            for _, handler in ipairs(handlers_list) do
                local ok, err = pcall(handler, event)
                if not ok then
                    log("Error in nth_tick handler (interval=" .. tostring(tick_interval) .. "): " .. tostring(err))
                end
            end
        end)
    end
    
    log("Event dispatcher initialized: registered " .. 
        count_keys(all_handlers) .. " standard events and " .. 
        count_keys(nth_tick_handlers) .. " nth_tick event groups")
end

-- ============================================================================
-- REGISTER REMOTE INTERFACES
-- ============================================================================

action_registry:register_remote_interface()
action_queue:register_queue_remote_interface()

-- ============================================================================
-- REGISTER ALL EVENTS USING DISPATCHER
-- ============================================================================

register_all_events()

-- ============================================================================
-- ACTION QUEUE HANDLER (called by on_load after snapshot, and at init)
-- ============================================================================

local MAX_ACTIONS_PER_TICK = 10

local function register_action_queue_handler()
  script.on_nth_tick(1, function(event)
    if action_queue and action_queue.process_some then
      action_queue:process_some(MAX_ACTIONS_PER_TICK)
    end
  end)
end

-- ============================================================================
-- LIFECYCLE CALLBACKS
-- ============================================================================

script.on_init(function()
  log("hello from on_init")
  -- Configure action queue for non-blocking intent ingestion
  action_queue:set_immediate_mode(false)
  action_queue:set_max_queue_size(10000)
  -- Restore any persisted state
  action_queue:load_from_global()
  -- Initialize agent_characters storage
  if not storage.agent_characters then
    storage.agent_characters = {}
    log("Initialized empty agent_characters storage for new game")
  end
  
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
  
  -- Register a one-time tick handler for initial snapshot
  local handler_registered = false
  local function check_and_snapshot(event)
    if handler_registered then return end
    handler_registered = true
    
    -- Take snapshot ONLY on server startup with no clients
    if game.is_multiplayer() and #game.connected_players == 0 then
      log("Server startup detected - taking initial map snapshot")
      local surface = game.surfaces[1]
      if surface and #surface.find_entities() > 0 then
        log("Existing entities found - taking snapshot")
        local snapshot = Snapshot:get_instance()
        snapshot:take_map_snapshot({
          async = true,
          chunks_per_tick = 2,
          components = {"entities", "resources"}
        })
      else
        log("No entities found - skipping snapshot")
      end
    else
      log("Client load or players present - skipping snapshot")
    end
    
    -- Unregister this handler - it will never fire again
    script.on_nth_tick(1, nil)
    
    -- Re-register the action queue processing handler for tick 1
    register_action_queue_handler()
  end
  
  -- Register handler to fire on next tick
  script.on_nth_tick(1, check_and_snapshot)
end)

script.on_configuration_changed(function()
  log("hello from on_configuration_changed")
end)

-- Register action queue handler for tick 1 processing
register_action_queue_handler()
