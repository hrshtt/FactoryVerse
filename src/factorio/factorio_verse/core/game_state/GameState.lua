--- factorio_verse/core/game_state/GameState.lua
--- GameState class for managing game state with composable sub-modules.

local GameStateError = require("core.Error")
local AgentGameState = require("core.game_state.AgentGameState")
local InventoryGameState = require("core.game_state.InventoryGameState")
local EntitiesGameState = require("core.game_state.EntitiesGameState")
local PowerGameState = require("core.game_state.PowerGameState")

--- @class GameState
--- Methods: agent(), entities(), inventory(), power(), get_game(), get_surface()
local GameState = {}
GameState.__index = GameState

function GameState:new()
    local instance = {}
    setmetatable(instance, self)
    return instance
end

-- Lazy getter for game
function GameState:get_game()
    return game
end

-- Lazy getter for surface
function GameState:get_surface()
    local g = self:get_game()
    return g and g.surfaces[1] or nil
end

-- Lazy getter for agent sub-module
function GameState:agent()
    if not self._agent then
        self._agent = AgentGameState:new(self)
    end
    return self._agent
end

-- Lazy getter for entities sub-module  
function GameState:entities()
    if not self._entities then
        self._entities = EntitiesGameState:new(self)
    end
    return self._entities
end

-- Lazy getter for inventory sub-module
function GameState:inventory()
    if not self._inventory then
        self._inventory = InventoryGameState:new(self)
    end
    return self._inventory
end

-- Lazy getter for power sub-module
function GameState:power()
    if not self._power then
        self._power = PowerGameState:new(self)
    end
    return self._power
end

function GameState:to_json(agent_id)
    local g = self:get_game()
    local surface = self:get_surface()
    return {
        agent_id = agent_id,
        tick = g and g.tick or 0,
        surface_name = surface and surface.name or nil,
        agent = self:agent():to_json(),
        entities = self:entities():to_json(),
        power = self:power():to_json()
    }
end

--- @class GameState.aliases
--- @field direction table
GameState.aliases = {
    direction = {
        [defines.direction.north] = defines.direction.north,
        n = defines.direction.north,
        north = defines.direction.north,
        up = defines.direction.north,

        [defines.direction.south] = defines.direction.south,
        s = defines.direction.south,
        south = defines.direction.south,
        down = defines.direction.south,

        [defines.direction.east] = defines.direction.east,
        e = defines.direction.east,
        east = defines.direction.east,
        right = defines.direction.east,

        [defines.direction.west] = defines.direction.west,
        w = defines.direction.west,
        west = defines.direction.west,
        left = defines.direction.west,

        [defines.direction.northeast] = defines.direction.northeast,
        ne = defines.direction.northeast,
        northeast = defines.direction.northeast,

        [defines.direction.northwest] = defines.direction.northwest,
        nw = defines.direction.northwest,
        northwest = defines.direction.northwest,

        [defines.direction.southeast] = defines.direction.southeast,
        se = defines.direction.southeast,
        southeast = defines.direction.southeast,

        [defines.direction.southwest] = defines.direction.southwest,
        sw = defines.direction.southwest,
        southwest = defines.direction.southwest,
    }
}


return GameState
