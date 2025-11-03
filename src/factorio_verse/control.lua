-- control.lua: Central event dispatcher using aggregation pattern
-- Coordinates ActionRegistry and GameState to aggregate events and register remote interfaces
-- Events can only be registered once, so we aggregate all handlers and register via chains

local ActionRegistry = require("core.ActionRegistry")
local ActionQueue = require("core.ActionQueue")
local GameState = require("GameState")
local utils = require("utils")

-- Initialize core instances
local game_state = GameState:new()
local action_registry = ActionRegistry
local action_queue = ActionQueue

-- ============================================================================
-- EVENT DISPATCHER PATTERN
-- ============================================================================

local function count_keys(tbl)
    local count = 0
    for _ in pairs(tbl or {}) do
        count = count + 1
    end
    return count
end

--- Aggregate all events from all sources
--- Events can only be registered once, so we aggregate all handlers into chains
--- @return table - {defined_events = {event_id -> [handler, ...]}, nth_tick = {tick_interval -> [handler, ...]}}
local function aggregate_all_events()
    local defined_events = {} -- {event_id -> [handler1, handler2, ...]}
    local nth_tick_handlers = {} -- {tick_interval -> [handler1, handler2, ...]}
    
    local function add_defined_event(event_id, handler)
        if event_id and handler then
            defined_events[event_id] = defined_events[event_id] or {}
            table.insert(defined_events[event_id], handler)
        end
    end
    
    local function add_nth_tick_handler(tick_interval, handler)
        if tick_interval and handler then
            nth_tick_handlers[tick_interval] = nth_tick_handlers[tick_interval] or {}
            table.insert(nth_tick_handlers[tick_interval], handler)
        end
    end
    
    -- Initialize actions with game_state before getting events/interface
    action_registry:init_actions(game_state)
    
    -- 1. Action Registry Events
    -- Actions export events as {event_id -> handler} or {event_id -> factory(game_state)}
    local action_events = action_registry:get_events()
    for event_id, handlers in pairs(action_events or {}) do
        for _, handler in ipairs(handlers) do
            add_defined_event(event_id, handler)
        end
    end
    
    -- 2. GameState Event-Based Snapshot Events
    local event_based_snapshot = game_state:get_event_based_snapshot_events()
    for event_id, handlers in pairs(event_based_snapshot.defined_events or {}) do
        for _, handler in ipairs(handlers) do
            add_defined_event(event_id, handler)
        end
    end
    for tick_interval, handlers in pairs(event_based_snapshot.nth_tick or {}) do
        for _, handler in ipairs(handlers) do
            add_nth_tick_handler(tick_interval, handler)
        end
    end
    
    -- 3. GameState Disk Write Snapshot Events
    local disk_write_snapshot = game_state:get_disk_write_snapshot_events()
    for event_id, handlers in pairs(disk_write_snapshot.defined_events or {}) do
        for _, handler in ipairs(handlers) do
            add_defined_event(event_id, handler)
        end
    end
    for tick_interval, handlers in pairs(disk_write_snapshot.nth_tick or {}) do
        for _, handler in ipairs(handlers) do
            add_nth_tick_handler(tick_interval, handler)
        end
    end
    
    -- 4. GameState Regular Events (internal game state events)
    local game_state_events = game_state:get_game_state_events()
    for event_id, handlers in pairs(game_state_events.defined_events or {}) do
        for _, handler in ipairs(handlers) do
            add_defined_event(event_id, handler)
        end
    end
    for tick_interval, handlers in pairs(game_state_events.nth_tick or {}) do
        for _, handler in ipairs(handlers) do
            add_nth_tick_handler(tick_interval, handler)
        end
    end
    
    -- 5. GameState nth_tick Handlers (legacy map discovery, etc.)
    local gs_nth_tick = game_state:get_nth_tick_handlers()
    for tick_interval, handlers in pairs(gs_nth_tick or {}) do
        if type(handlers) == "table" then
            for _, handler in ipairs(handlers) do
                add_nth_tick_handler(tick_interval, handler)
            end
        else
            -- Support legacy single handler format
            add_nth_tick_handler(tick_interval, handlers)
        end
    end
    
    -- 6. Player Events (custom handlers)
    -- add_defined_event(defines.events.on_player_created, function(e)
    --     local player = game.get_player(e.player_index)
    --     if player then
    --         local character = player.character
    --         player.character = nil
    --         if character then
    --             character.destroy()
    --         end
    --     end
    -- end)
    
    return {
        defined_events = defined_events,
        nth_tick = nth_tick_handlers
    }
end

--- Register all aggregated events
--- Events are registered once per event_id/tick_interval with aggregated handler chains
local function register_all_events()
    local aggregated = aggregate_all_events()
    
    -- Register defined events (defines.events.*) - each event_id registered once with aggregated handlers
    for event_id, handlers_list in pairs(aggregated.defined_events) do
        script.on_event(event_id, function(event)
            for _, handler in ipairs(handlers_list) do
                handler(event)
            end
        end)
    end
    
    -- Register nth_tick events - each tick_interval registered once with aggregated handlers
    for tick_interval, handlers_list in pairs(aggregated.nth_tick) do
        script.on_nth_tick(tick_interval, function(event)
            for _, handler in ipairs(handlers_list) do
                handler(event)
            end
        end)
    end
    
    log("Event dispatcher initialized: registered " .. 
        count_keys(aggregated.defined_events) .. " defined events and " .. 
        count_keys(aggregated.nth_tick) .. " nth_tick event groups")
end

-- ============================================================================
-- REGISTER REMOTE INTERFACES
-- ============================================================================

local function register_all_remote_interfaces()
    if not remote or not remote.add_interface then
        return
    end
    
    -- Register action interface (sync actions)
    -- Actions already initialized with game_state above
    local action_iface = action_registry:get_action_interface()
    if remote.interfaces["action"] then
        log("Removing existing 'action' interface")
        remote.remove_interface("action")
    end
    local action_count = 0
    for _ in pairs(action_iface) do action_count = action_count + 1 end
    log("Registering 'action' interface with " .. action_count .. " actions")
    remote.add_interface("action", action_iface)
    
    -- Register admin interface (from GameState)
    local admin_iface = game_state:get_admin_api()
    if remote.interfaces["admin"] then
        log("Removing existing 'admin' interface")
        remote.remove_interface("admin")
    end
    local admin_count = 0
    for _ in pairs(admin_iface) do admin_count = admin_count + 1 end
    log("Registering 'admin' interface with " .. admin_count .. " methods")
    remote.add_interface("admin", admin_iface)
    
    -- Register on-demand snapshot interface (from GameState)
    local snapshot_iface = game_state:get_on_demand_snapshot_api()
    if remote.interfaces["snapshot"] then
        log("Removing existing 'snapshot' interface")
        remote.remove_interface("snapshot")
    end
    local snapshot_count = 0
    for _ in pairs(snapshot_iface) do snapshot_count = snapshot_count + 1 end
    log("Registering 'snapshot' interface with " .. snapshot_count .. " methods")
    remote.add_interface("snapshot", snapshot_iface)
    
    -- Register action queue interface (async actions)
    action_queue:register_queue_remote_interface()
end

register_all_remote_interfaces()

-- ============================================================================
-- REGISTER ALL EVENTS USING DISPATCHER
-- Events must be registered in on_init/on_load, not at module load time
-- ============================================================================

-- ============================================================================
-- ACTION QUEUE HANDLER
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
    action_queue:load_from_global()
    
    -- Initialize agent_characters storage
    if not storage.agent_characters then
        storage.agent_characters = {}
        log("Initialized empty agent_characters storage for new game")
    end
    
    -- Register events (game is available during on_init)
    register_all_events()
end)

script.on_load(function()
    log("hello from on_load")
    
    -- Register action queue processing handler
    register_action_queue_handler()
    
    -- Re-register events (game is available during on_load)
    -- This is needed because event handlers may be lost after mod reload
    register_all_events()
end)

script.on_configuration_changed(function()
    log("hello from on_configuration_changed")
end)

-- Register action queue handler for tick 1 processing
register_action_queue_handler()
