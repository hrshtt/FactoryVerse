--- factorio_verse/core/game_state/GameState.lua
--- GameState class for managing game state with composable sub-modules.

local GameStateError = require("factorio_verse.core.Error")
local AgentGameState = require("factorio_verse.core.game_state.AgentGameState")
local InventoryGameState = require("factorio_verse.core.game_state.InventoryGameState")
local EntitiesGameState = require("factorio_verse.core.game_state.EntitiesGameState")
local PowerGameState = require("factorio_verse.core.game_state.PowerGameState")

--- @class GameState
--- @field game table
--- @field surface table
--- @field agent AgentGameState
--- @field inventory InventoryGameState
--- @field entities EntitiesGameState
--- @field power PowerGameState
local GameState = {}
GameState.__index = GameState

function GameState:new()
    local instance = {
        game = game,
        surface = nil
    }

    instance.surface = game.surfaces[1]

    setmetatable(instance, self)

    -- Initialize sub-modules
    instance.agent = AgentGameState:new()
    instance.entities = EntitiesGameState:new(instance)
    instance.inventory = InventoryGameState:new(instance)
    instance.power = PowerGameState:new(instance)

    return instance
end

function GameState:to_json(agent_id)
    return {
        agent_id = agent_id,
        tick = self.game and self.game.tick or 0,
        surface_name = self.surface and self.surface.name or nil,
        agent = self.agent:to_json(),
        entities = self.entities:to_json(),
        power = self.power:to_json()
    }
end

--- @class GameState.aliases
--- @field direction table
GameState.aliases = {
    direction = {
        n = defines.direction.north,
        north = defines.direction.north,
        up = defines.direction.north,

        s = defines.direction.south,
        south = defines.direction.south,
        down = defines.direction.south,

        e = defines.direction.east,
        east = defines.direction.east,
        right = defines.direction.east,

        w = defines.direction.west,
        west = defines.direction.west,
        left = defines.direction.west,

        ne = defines.direction.northeast,
        northeast = defines.direction.northeast,

        nw = defines.direction.northwest,
        northwest = defines.direction.northwest,

        se = defines.direction.southeast,
        southeast = defines.direction.southeast,

        sw = defines.direction.southwest,
        southwest = defines.direction.southwest,
    }
}


return GameState
