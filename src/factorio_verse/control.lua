-- control.lua: Central event dispatcher using aggregation pattern
-- Coordinates game state modules to aggregate events and register remote interfaces
-- Events can only be registered once, so we aggregate all handlers and register via chains
--
-- Note: Per-agent remote interfaces (agent_1, agent_2, etc.) are registered automatically
-- when agents are created via Agent:register_remote_interface()

local utils = require("utils.utils")

-- Require game state modules at module level (required by Factorio)
local Agents = require("game_state.Agents")
local Entities = require("game_state.Entities")
local Resource = require("game_state.Resource")
local Map = require("game_state.Map")
local Power = require("game_state.Power")
local Research = require("game_state.Research")

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

--- Aggregate all events from all modules
--- Events can only be registered once, so we aggregate all handlers into chains
--- @return table - {defined_events = {event_id -> [handler, ...]}, nth_tick = {tick_interval -> [handler, ...]}}
local function aggregate_all_events()
    local defined_events = {}    -- {event_id -> [handler1, handler2, ...]}
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

    -- Collect all modules
    local modules = { Agents, Entities, Resource, Map, Power, Research }

    -- 1. Aggregate on_tick handlers from all modules
    for _, module in ipairs(modules) do
        if module and module.get_on_tick_handlers then
            local handlers = module.get_on_tick_handlers()
            if handlers then
                for _, handler in ipairs(handlers) do
                    add_defined_event(defines.events.on_tick, handler)
                end
            end
        end
    end

    -- 2. Aggregate events (defined_events and nth_tick) from all modules
    for _, module in ipairs(modules) do
        if module and module.get_events then
            local events = module.get_events()
            if events then
                -- Aggregate defined events
                if events.defined_events then
                    for event_id, handler in pairs(events.defined_events) do
                        add_defined_event(event_id, handler)
                    end
                end

                -- Aggregate nth_tick events
                if events.nth_tick then
                    for tick_interval, handler in pairs(events.nth_tick) do
                        -- Handle both single handler and array of handlers
                        if type(handler) == "table" and handler[1] then
                            -- Array of handlers
                            for _, h in ipairs(handler) do
                                add_nth_tick_handler(tick_interval, h)
                            end
                        else
                            -- Single handler
                            add_nth_tick_handler(tick_interval, handler)
                        end
                    end
                end
            end
        end
    end

    -- 3. Entity status tracking (every 60 ticks)
    -- Map orchestrates getting chunks, Entities provides the tracking logic
    add_nth_tick_handler(60, function()
        local charted_chunks = Map.get_charted_chunks()
        Entities.track_all_charted_chunk_entity_status(charted_chunks)
    end)

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

    -- Note: Per-agent remote interfaces (agent_1, agent_2, etc.) are registered
    -- automatically when agents are created via Agent:register_remote_interface()
    -- These interfaces expose agent methods directly (walk_to, mine_resource, etc.)

    -- Collect all modules
    local modules = {
        { name = "agent",    module = Agents },
        { name = "entities", module = Entities },
        { name = "map",      module = Map },
        { name = "power",    module = Power },
        { name = "research", module = Research },
        { name = "resource", module = Resource },
    }

    -- Register each module's remote interface
    for _, mod_info in ipairs(modules) do
        local module = mod_info.module
        if module and module.register_remote_interface then
            local interface = module.register_remote_interface()
            if interface and next(interface) ~= nil then
                local interface_name = mod_info.name
                if remote.interfaces[interface_name] then
                    log("Removing existing '" .. interface_name .. "' interface")
                    remote.remove_interface(interface_name)
                end
                local method_count = 0
                for _ in pairs(interface) do method_count = method_count + 1 end
                log("Registering '" .. interface_name .. "' interface with " .. method_count .. " methods")
                remote.add_interface(interface_name, interface)
            end
        end
    end
end

register_all_remote_interfaces()

-- ============================================================================
-- REGISTER EXISTING AGENT INTERFACES (for hot reload)
-- ============================================================================

--- Re-register remote interfaces for all existing agents
--- Called after on_init/on_load to restore interfaces lost during hot reload
--- Agent instances persist in storage with metatables, but remote interfaces are cleared
local function register_existing_agent_interfaces()
    if not remote or not remote.add_interface then
        return
    end

    if not storage.agents then
        return
    end

    local registered_count = 0
    for agent_id, agent in pairs(storage.agents) do
        -- Verify agent is valid (has metatable methods)
        if agent and type(agent.register_remote_interface) == "function" then
            -- Check if interface already exists (shouldn't happen, but be safe)
            local interface_name = "agent_" .. agent_id
            if not remote.interfaces[interface_name] then
                agent:register_remote_interface()
                registered_count = registered_count + 1
            end
        end
    end

    if registered_count > 0 then
        log("Re-registered " .. registered_count .. " agent remote interface(s) after reload")
    end
end

-- ============================================================================
-- LIFECYCLE CALLBACKS
-- ============================================================================

script.on_init(function()
    log("hello from on_init")

    -- Initialize agents storage
    if not storage.agents then
        storage.agents = {}
        log("Initialized empty agents storage for new game")
    end

    -- Initialize game state modules (must happen before event registration)
    -- This generates custom event IDs that will be used in event handlers
    Entities.init()
    Resource.init()
    Map.init()

    log("Initialized game state modules and custom events")

    -- Register events (game is available during on_init)
    register_all_events()

    -- Re-register agent interfaces for any existing agents (shouldn't be any on init, but be safe)
    register_existing_agent_interfaces()
end)

script.on_load(function()
    log("hello from on_load")

    -- Initialize game state modules (must happen before event registration)
    -- Custom events are preserved across reload, but we need to rebuild disk_write_snapshot tables
    Entities.init()
    Resource.init()
    Map.init() -- Will check and queue chunks if needed

    log("Re-initialized game state modules after mod reload")

    -- Re-register events (game is available during on_load)
    -- This is needed because event handlers may be lost after mod reload
    register_all_events()

    -- Re-register agent interfaces for existing agents (critical for hot reload)
    -- Remote interfaces are cleared on reload, but agent instances persist in storage
    register_existing_agent_interfaces()
end)

script.on_configuration_changed(function()
    log("hello from on_configuration_changed")
end)
