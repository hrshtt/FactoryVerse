--- factorio_verse/core/game_state/GameState.lua
--- GameState class for managing game state with composable sub-modules.

local game_state_aliases = require("game_state.GameStateAliases")
local AgentGameState = require("game_state.agent.Agent")
local InventoryGameState = require("game_state.Inventory")
local EntitiesGameState = require("game_state.Entities")
local PowerGameState = require("game_state.Power")
local MapGameState = require("game_state.Map")
local ResourceGameState = require("game_state.Resource")
local ResearchGameState = require("game_state.Research")


--- @class GameState
--- @field agent AgentGameState
--- @field entities EntitiesGameState
--- @field inventory InventoryGameState
--- @field power PowerGameState
--- @field map MapGameState
--- @field resource_state ResourceGameState
--- @field research ResearchGameState
local GameState = {}
GameState.__index = GameState


--- @return GameState
function GameState:new()
    local instance = {}
    
    -- Eager initialization: Create all sub-modules immediately (no lazy loading overhead)
    -- Direct property access (no method call overhead)
    instance.agent = AgentGameState:new(instance)
    instance.entities = EntitiesGameState:new(instance)
    instance.inventory = InventoryGameState:new(instance)
    instance.power = PowerGameState:new(instance)
    instance.map = MapGameState:new(instance)
    instance.resource_state = ResourceGameState:new(instance)
    instance.research = ResearchGameState:new(instance)
    
    -- Update cached references in modules that depend on other modules
    -- (e.g., agent caches inventory, but inventory is created after agent)
    if instance.agent and instance.agent.inventory == nil then
        instance.agent.inventory = instance.inventory
    end
    
    setmetatable(instance, self)
    return instance
end

--- @class GameState.aliases
--- @field direction table
GameState.aliases = game_state_aliases

--- Aggregate admin APIs from all game state sub-modules
--- Admin-level remote API useful for working with the mod
--- @return table<string, function> Admin API interface
function GameState:get_admin_api()
    local admin_interface = {}
    local ParamSpec = require("types.ParamSpec")
    
    -- All sub-modules (already initialized)
    local submodules = {
        { name = "agent", instance = self.agent },
        { name = "inventory", instance = self.inventory },
        { name = "power", instance = self.power },
        { name = "map", instance = self.map },
        { name = "research", instance = self.research },
    }
    
    for _, submod in ipairs(submodules) do
        if submod.instance and submod.instance.admin_api then
            for api_name, api_func in pairs(submod.instance.admin_api) do
                local spec = submod.instance.AdminApiSpecs and submod.instance.AdminApiSpecs[api_name]
                
                admin_interface[submod.name .. "." .. api_name] = function(...)
                    local normalized_args = ParamSpec:normalize_varargs(spec, ...)
                    return api_func(submod.instance, table.unpack(normalized_args))
                end
            end
        end
    end
    
    return admin_interface
end

--- Aggregate on-demand snapshot methods from all game state sub-modules
--- Remote API for reaching snapshots of the game state on demand
--- @return table<string, function> On-demand snapshot interface
function GameState:get_on_demand_snapshot_api()
    local snapshot_interface = {}
    local ParamSpec = require("types.ParamSpec")
    
    -- All sub-modules (already initialized)
    local submodules = {
        { name = "agent", instance = self.agent },
        { name = "inventory", instance = self.inventory },
        { name = "power", instance = self.power },
        { name = "research", instance = self.research },
    }
    
    for _, submod in ipairs(submodules) do
        if submod.instance then
            -- Handle both plural and singular property names
            local snapshots = submod.instance.on_demand_snapshots
            if snapshots then
                for snapshot_name, snapshot_func in pairs(snapshots) do
                    -- Check if there's a spec for this snapshot method (reuse AdminApiSpecs if available)
                    local spec = submod.instance.AdminApiSpecs and submod.instance.AdminApiSpecs[snapshot_name]
                    
                    snapshot_interface[submod.name .. "." .. snapshot_name] = function(...)
                        if spec then
                            -- Normalize arguments like admin API does
                            local normalized_args = ParamSpec:normalize_varargs(spec, ...)
                            return snapshot_func(submod.instance, table.unpack(normalized_args))
                        else
                            -- No spec available, pass through as-is
                            return snapshot_func(submod.instance, ...)
                        end
                    end
                end
            end
        end
    end
    
    return snapshot_interface
end

--- Aggregate event-based snapshot events from all game state sub-modules
--- Event-based UDP send logic for sending important game snapshots outside of the mod
--- Returns events categorized by type: defined events, on_tick, nth_tick
--- @return table - {defined_events = {event_id -> handler, ...}, on_tick = {handler, ...}, nth_tick = {tick_interval -> handler, ...}}
function GameState:get_event_based_snapshot_events()
    local defined_events = {}
    local on_tick_handlers = {}
    local nth_tick_handlers = {}
    
    -- All sub-modules (already initialized)
    local submodules = {
        { name = "agent", instance = self.agent },
        { name = "entities", instance = self.entities },
        { name = "inventory", instance = self.inventory },
        { name = "power", instance = self.power },
        { name = "map", instance = self.map },
        { name = "resource_state", instance = self.resource_state },
        { name = "research", instance = self.research },
    }
    
    for _, submod in ipairs(submodules) do
        if submod.instance and submod.instance.get_event_based_snapshot_events then
            local event_snapshot = submod.instance:get_event_based_snapshot_events()
            
            -- Handle defined events (defines.events.*)
            if event_snapshot.events then
                for event_id, handler in pairs(event_snapshot.events) do
                    defined_events[event_id] = defined_events[event_id] or {}
                    table.insert(defined_events[event_id], handler)
                    -- Check if it's on_tick
                    if event_id == defines.events.on_tick then
                        table.insert(on_tick_handlers, handler)
                    end
                end
            end
            
            -- Handle nth_tick events
            if event_snapshot.nth_tick then
                for tick_interval, handler in pairs(event_snapshot.nth_tick) do
                    nth_tick_handlers[tick_interval] = nth_tick_handlers[tick_interval] or {}
                    table.insert(nth_tick_handlers[tick_interval], handler)
                end
            end
        end
    end
    
    return {
        defined_events = defined_events,
        on_tick = on_tick_handlers,
        nth_tick = nth_tick_handlers
    }
end

--- Aggregate disk write snapshot events from all game state sub-modules
--- Events that write files to disk based on actions updating entities or properties
--- Will eventually be coupled to UDP send to let outside consumers know a file has been updated
--- Returns events categorized by type: defined events, on_tick, nth_tick
--- @return table - {defined_events = {event_id -> handler, ...}, on_tick = {handler, ...}, nth_tick = {tick_interval -> handler, ...}}
function GameState:get_disk_write_snapshot_events()
    local defined_events = {}
    local on_tick_handlers = {}
    local nth_tick_handlers = {}
    
    -- All sub-modules (already initialized)
    local submodules = {
        { name = "agent", instance = self.agent },
        { name = "entities", instance = self.entities },
        { name = "inventory", instance = self.inventory },
        { name = "power", instance = self.power },
        { name = "map", instance = self.map },
        { name = "resource_state", instance = self.resource_state },
        { name = "research", instance = self.research },
    }
    
    for _, submod in ipairs(submodules) do
        if submod.instance and submod.instance.disk_write_snapshot then
            local disk_snapshot = submod.instance.disk_write_snapshot
            
            -- Handle defined events (defines.events.*)
            if disk_snapshot.events then
                for event_id, handler in pairs(disk_snapshot.events) do
                    defined_events[event_id] = defined_events[event_id] or {}
                    table.insert(defined_events[event_id], handler)
                    -- Check if it's on_tick
                    if event_id == defines.events.on_tick then
                        table.insert(on_tick_handlers, handler)
                    end
                end
            end
            
            -- Handle nth_tick events
            if disk_snapshot.nth_tick then
                for tick_interval, handler in pairs(disk_snapshot.nth_tick) do
                    nth_tick_handlers[tick_interval] = nth_tick_handlers[tick_interval] or {}
                    table.insert(nth_tick_handlers[tick_interval], handler)
                end
            end
        end
    end
    
    return {
        defined_events = defined_events,
        on_tick = on_tick_handlers,
        nth_tick = nth_tick_handlers
    }
end

--- Aggregate regular game state events from all game state sub-modules
--- Regular game state events used internally by the mod
--- Returns events categorized by type: defined events, on_tick, nth_tick
--- @return table - {defined_events = {event_id -> handler, ...}, on_tick = {handler, ...}, nth_tick = {tick_interval -> handler, ...}}
function GameState:get_game_state_events()
    local defined_events = {}
    local on_tick_handlers = {}
    local nth_tick_handlers = {}
    
    -- Agent activity events (walking, mining state machines)
    if self.agent and self.agent.get_activity_events then
        local activity_events = self.agent:get_activity_events()
        for event_id, handler in pairs(activity_events) do
            defined_events[event_id] = defined_events[event_id] or {}
            table.insert(defined_events[event_id], handler)
            -- Check if it's on_tick
            if event_id == defines.events.on_tick then
                table.insert(on_tick_handlers, handler)
            end
        end
    end
    
    -- All sub-modules (already initialized)
    local submodules = {
        { name = "agent", instance = self.agent },
        { name = "entities", instance = self.entities },
        { name = "inventory", instance = self.inventory },
        { name = "power", instance = self.power },
        { name = "map", instance = self.map },
        { name = "resource_state", instance = self.resource_state },
        { name = "research", instance = self.research },
    }
    
    for _, submod in ipairs(submodules) do
        if submod.instance and submod.instance.game_state_events then
            local gs_events = submod.instance.game_state_events
            
            -- Handle defined events (defines.events.*)
            if gs_events.events then
                for event_id, handler in pairs(gs_events.events) do
                    defined_events[event_id] = defined_events[event_id] or {}
                    table.insert(defined_events[event_id], handler)
                    -- Check if it's on_tick
                    if event_id == defines.events.on_tick then
                        table.insert(on_tick_handlers, handler)
                    end
                end
            end
            
            -- Handle nth_tick events
            if gs_events.nth_tick then
                for tick_interval, handler in pairs(gs_events.nth_tick) do
                    nth_tick_handlers[tick_interval] = nth_tick_handlers[tick_interval] or {}
                    table.insert(nth_tick_handlers[tick_interval], handler)
                end
            end
        end
    end
    
    return {
        defined_events = defined_events,
        on_tick = on_tick_handlers,
        nth_tick = nth_tick_handlers
    }
end

--- Aggregate nth_tick handlers from all game state sub-modules
--- Combines nth_tick handlers from various sources (map discovery, etc.)
--- @return table - {tick_interval -> handler, ...}
function GameState:get_nth_tick_handlers()
    local nth_tick_handlers = {}
    
    -- Map discovery nth_tick handlers (legacy pattern)
    local map_state = self.map
    if map_state and map_state.nth_tick_handlers then
        for tick_interval, handler in pairs(map_state.nth_tick_handlers) do
            nth_tick_handlers[tick_interval] = nth_tick_handlers[tick_interval] or {}
            table.insert(nth_tick_handlers[tick_interval], handler)
        end
    end
    
    -- Get nth_tick from event_based_snapshot
    local event_based = self:get_event_based_snapshot_events()
    for tick_interval, handlers in pairs(event_based.nth_tick) do
        nth_tick_handlers[tick_interval] = nth_tick_handlers[tick_interval] or {}
        for _, handler in ipairs(handlers) do
            table.insert(nth_tick_handlers[tick_interval], handler)
        end
    end
    
    -- Get nth_tick from disk_write_snapshot
    local disk_write = self:get_disk_write_snapshot_events()
    for tick_interval, handlers in pairs(disk_write.nth_tick) do
        nth_tick_handlers[tick_interval] = nth_tick_handlers[tick_interval] or {}
        for _, handler in ipairs(handlers) do
            table.insert(nth_tick_handlers[tick_interval], handler)
        end
    end
    
    -- Get nth_tick from game_state_events
    local gs_events = self:get_game_state_events()
    for tick_interval, handlers in pairs(gs_events.nth_tick) do
        nth_tick_handlers[tick_interval] = nth_tick_handlers[tick_interval] or {}
        for _, handler in ipairs(handlers) do
            table.insert(nth_tick_handlers[tick_interval], handler)
        end
    end
    
    return nth_tick_handlers
end

return GameState
