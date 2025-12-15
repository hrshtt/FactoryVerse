-- control.lua: Event dispatcher for fv_embodied_agent mod
-- Registers agent-related remote interfaces and event handlers

local utils = require("utils.utils")

-- Require game state modules at module level (required by Factorio)
local Agents = require("game_state.Agents")
local Agent = require("Agent")

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
    local modules = { Agents }

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

    -- Register agent admin interface
    if Agents and Agents.register_remote_interface then
        local interface = Agents.register_remote_interface()
        if interface and next(interface) ~= nil then
            local interface_name = "agent"
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

    -- Register global documentation API
    -- Returns paramspec for each method (the only runtime-relevant metadata)
    local docs_interface = {
        get_all_methods = function()
            local interface_methods = Agent.get_interface_methods()
            if not interface_methods then
                return { error = "Interface methods not available" }
            end
            local methods = {}
            for method_name, meta in pairs(interface_methods) do
                methods[method_name] = {
                    paramspec = meta.paramspec,
                }
            end
            return methods
        end,
        get_method_schema = function(method_name)
            if not method_name or type(method_name) ~= "string" then
                return { error = "method_name (string) is required" }
            end
            local interface_methods = Agent.get_interface_methods()
            if not interface_methods then
                return { error = "Interface methods not available" }
            end
            local meta = interface_methods[method_name]
            if not meta then
                return { error = "Method '" .. method_name .. "' not found" }
            end
            return {
                method_name = method_name,
                paramspec = meta.paramspec,
            }
        end,
    }
    if remote.interfaces["factorio_verse_docs"] then
        log("Removing existing 'factorio_verse_docs' interface")
        remote.remove_interface("factorio_verse_docs")
    end
    log("Registering 'factorio_verse_docs' interface")
    remote.add_interface("factorio_verse_docs", docs_interface)
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
    log("hello from fv_embodied_agent on_init")

    -- Initialize agents storage
    if not storage.agents then
        storage.agents = {}
        log("Initialized empty agents storage for new game")
    end

    log("Initialized fv_embodied_agent game state modules")

    -- Register remote interfaces (required for mods, also works for scenarios)
    register_all_remote_interfaces()

    -- Register events (game is available during on_init)
    register_all_events()

    -- Re-register agent interfaces for any existing agents (shouldn't be any on init, but be safe)
    register_existing_agent_interfaces()
end)

script.on_load(function()
    log("hello from fv_embodied_agent on_load")

    log("Re-initialized fv_embodied_agent game state modules after mod reload")

    -- Re-register remote interfaces (required for mods, also works for scenarios)
    -- Remote interfaces are cleared on reload, so we must re-register them
    register_all_remote_interfaces()

    -- Re-register events (game is available during on_load)
    -- This is needed because event handlers may be lost after mod reload
    register_all_events()

    -- Re-register agent interfaces for existing agents (critical for hot reload)
    -- Remote interfaces are cleared on reload, but agent instances persist in storage
    register_existing_agent_interfaces()
end)

script.on_configuration_changed(function()
    log("hello from fv_embodied_agent on_configuration_changed")
end)

