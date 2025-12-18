-- control.lua: Event dispatcher for fv_snapshot mod
-- Registers snapshot-related remote interfaces and event handlers
-- Note: This mod depends on fv_embodied_agent (for Agent class)

local utils = require("utils.utils")
local snapshot = require("utils.snapshot")

-- Require game state modules at module level (required by Factorio)
local Entities = require("game_state.Entities")
local Resource = require("game_state.Resource")
local Map = require("game_state.Map")
local Power = require("game_state.Power")
local Research = require("game_state.Research")
local Agents = require("game_state.Agents")

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
    local modules = { Entities, Resource, Map, Power, Research, Agents }

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

    -- 3. Entity status tracking (every 120 ticks)
    -- Map orchestrates getting chunks, Entities provides the tracking logic
    -- Changed from 60 to 120 ticks to reduce performance overhead
    -- ONLY runs during MAINTENANCE phase (disabled during initial snapshotting)
    add_nth_tick_handler(120, function()
        -- Check system phase before running status tracking
        if Map.get_system_phase() == "MAINTENANCE" then
            local charted_chunks = Map.get_charted_chunks()
            Entities.track_all_charted_chunk_entity_status(charted_chunks)
            -- Also dump compressed status to disk
            Entities.dump_status_to_disk(charted_chunks)
        end
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

    -- Collect all modules
    local modules = {
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
-- SNAPSHOT DIRECTORY CLEANUP
-- ============================================================================

--- Clear the snapshot directory to ensure a clean state for new maps
--- This prevents stale data from previous map sessions from being loaded
local function clear_snapshot_directory()
    local snapshot_base_dir = snapshot.SNAPSHOT_BASE_DIR
    
    -- Attempt to remove the entire snapshot directory tree
    local ok, err = pcall(function()
        helpers.remove_path(snapshot_base_dir)
    end)
    
    if ok then
        log("🧹 Cleared snapshot directory: " .. snapshot_base_dir)
    else
        log("⚠️  Failed to clear snapshot directory: " .. tostring(err))
        -- Continue anyway - the directory might not exist yet
    end
end

-- ============================================================================
-- LIFECYCLE CALLBACKS
-- ============================================================================

script.on_init(function()
    log("hello from fv_snapshot on_init")

    -- Clear snapshot directory FIRST to ensure clean state for new map
    -- This is critical when starting a new map with a fresh seed
    clear_snapshot_directory()

    -- Initialize game state modules (must happen before event registration)
    -- This generates custom event IDs that will be used in event handlers
    Entities.init()
    Resource.init()
    Map.init()

    log("Initialized fv_snapshot game state modules and custom events")

    -- Register remote interfaces (required for mods, also works for scenarios)
    register_all_remote_interfaces()

    -- Register events (game is available during on_init)
    register_all_events()
end)

script.on_load(function()
    log("hello from fv_snapshot on_load")

    -- Initialize game state modules (must happen before event registration)
    -- Custom events are preserved across reload, but we need to rebuild disk_write_snapshot tables
    Entities.init()
    Resource.init()
    Map.init() -- Will check and queue chunks if needed

    log("Re-initialized fv_snapshot game state modules after mod reload")

    -- Re-register remote interfaces (required for mods, also works for scenarios)
    -- Remote interfaces are cleared on reload, so we must re-register them
    register_all_remote_interfaces()

    -- Re-register events (game is available during on_load)
    -- This is needed because event handlers may be lost after mod reload
    register_all_events()
end)

script.on_configuration_changed(function()
    log("hello from fv_snapshot on_configuration_changed")
end)

