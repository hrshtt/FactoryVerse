--- factorio_verse/core/game_state/GameState.lua
--- GameState class for managing game state with composable sub-modules.

local game_state_aliases = require("game_state.GameStateAliases")
local AgentGameState = require("game_state.Agent")
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
    
    setmetatable(instance, self)
    return instance
end

--- @class GameState.aliases
--- @field direction table
GameState.aliases = game_state_aliases

function GameState:get_nth_tick_handlers()
    local map_state = self.map
    if not map_state then return {} end
    return map_state.nth_tick_handlers
end

--- Aggregate admin APIs from all game state sub-modules
--- @return table<string, function> Admin API interface
function GameState:get_admin_api()
    local admin_interface = {}
    
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
                admin_interface[submod.name .. "." .. api_name] = function(...)
                    return api_func(submod.instance, ...)
                end
            end
        end
    end
    
    return admin_interface
end

--- Aggregate snapshot methods from all game state sub-modules
--- Handles 'on_demand_snapshots'
--- @return table<string, function> Snapshot interface
function GameState:get_snapshot_api()
    local snapshot_interface = {}
    
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
                    snapshot_interface[submod.name .. "." .. snapshot_name] = function(...)
                        return snapshot_func(submod.instance, ...)
                    end
                end
            end
        end
    end
    
    return snapshot_interface
end

return GameState
