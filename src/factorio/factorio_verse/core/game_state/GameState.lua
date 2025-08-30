--- factorio_verse/core/game_state/GameState.lua
--- GameState class for managing game state with composable sub-modules.

local game_state_aliases = require("core.game_state.GameStateAliases")
local GameStateError = require("core.Error")
local AgentGameState = require("core.game_state.AgentGameState")
local InventoryGameState = require("core.game_state.InventoryGameState")
local EntitiesGameState = require("core.game_state.EntitiesGameState")
local PowerGameState = require("core.game_state.PowerGameState")
local utils = require("utils")
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

function GameState:get_visible_chunks(sort_by_distance)
    local surface = self:get_surface()
    local force = game.forces["player"]
    local visible_chunks = {}

    if not (surface and force) then
        return visible_chunks
    end

    for chunk in surface.get_chunks() do
        if force.is_chunk_visible(surface, chunk) then
            table.insert(visible_chunks, {x = chunk.x, y = chunk.y, area = chunk.area})
        end
    end

    if sort_by_distance == true then
        utils.sort_coordinates_by_distance(visible_chunks)
    end

    return visible_chunks
end

function GameState:get_charted_chunks(sort_by_distance)
    local surface = self:get_surface()
    local force = game.forces["player"]
    local charted_chunks = {}

    if not (surface and force) then
        return charted_chunks
    end

    for chunk in surface.get_chunks() do
        if force.is_chunk_charted(surface, chunk) then
            table.insert(charted_chunks, {x = chunk.x, y = chunk.y, area = chunk.area})
        end
    end

    if sort_by_distance == true then
        utils.sort_coordinates_by_distance(charted_chunks)
    end

    log("Charted chunks: " .. helpers.table_to_json(charted_chunks))

    return charted_chunks
end

-- Lazy getter for agent sub-module
function GameState:agent_state()
    if not self._agent then
        self._agent = AgentGameState:new(self)
    end
    return self._agent
end

-- Lazy getter for entities sub-module  
function GameState:entities_state()
    if not self._entities then
        self._entities = EntitiesGameState:new(self)
    end
    return self._entities
end

-- Lazy getter for inventory sub-module
function GameState:inventory_state()
    if not self._inventory then
        self._inventory = InventoryGameState:new(self)
    end
    return self._inventory
end

-- Lazy getter for power sub-module
function GameState:power_state()
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
        agent = self:agent_state():to_json(),
        entities = self:entities_state():to_json(),
        power = self:power_state():to_json()
    }
end

function GameState:get_resource_patches()
    local surface = self:get_surface()
    -- return surface.find_resource_patches()
end

--- @class GameState.aliases
--- @field direction table
GameState.aliases = game_state_aliases

return GameState
