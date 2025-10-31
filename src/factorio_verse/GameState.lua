--- factorio_verse/core/game_state/GameState.lua
--- GameState class for managing game state with composable sub-modules.

local game_state_aliases = require("core.game_state.GameStateAliases")
local GameStateError = require("core.Error")
local AgentGameState = require("core.game_state.Agent")
local InventoryGameState = require("core.game_state.Inventory")
local EntitiesGameState = require("core.game_state.Entities")
local PowerGameState = require("core.game_state.Power")
local MapGameState = require("core.game_state.Map")
local ResourceGameState = require("core.game_state.Resource")
local utils = require("utils")
--- @class GameState
local GameState = {}
GameState.__index = GameState


--- @return GameState
function GameState:new()
    local instance = {}
    setmetatable(instance, self)
    return instance
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

-- Lazy getter for map sub-module
function GameState:map()
    if not self._map then
        self._map = MapGameState:new(self)
    end
    return self._map
end

-- Lazy getter for resource sub-module
function GameState:resource_state()
    if not self._resource then
        self._resource = ResourceGameState:new(self)
    end
    return self._resource
end

function GameState:to_json(agent_id)
    local surface = game.surfaces[1]
    return {
        agent_id = agent_id,
        tick = game.tick or 0,
        surface_name = surface and surface.name or nil,
        agent = self:agent():to_json(),
        entities = self:entities():to_json(),
        power = self:power():to_json()
    }
end

--- Get all resource entities in specified chunks
--- @param chunks table - list of chunk areas
--- @return table - entities grouped by resource name
function GameState:get_resources_in_chunks(chunks)
    local surface = game.surfaces[1]
    if not surface then return {} end

    local resources_by_name = {}

    for _, chunk in ipairs(chunks) do
        local entities = surface.find_entities_filtered {
            area = chunk.area,
            type = "resource"
        }

        for _, entity in ipairs(entities) do
            local name = entity.name
            if not resources_by_name[name] then
                resources_by_name[name] = {}
            end
            table.insert(resources_by_name[name], entity)
        end
    end

    return resources_by_name
end

--- Get water tiles using prototype detection for mod compatibility
--- @param chunks table - list of chunk areas
--- @return table - water tiles and tile names
function GameState:get_water_tiles_in_chunks(chunks)
    local surface = game.surfaces[1]
    if not surface then return { tiles = {}, tile_names = {} } end

    -- Detect water tile names via prototypes for mod compatibility
    local water_tile_names = {}
    local ok_proto, tiles_or_err = pcall(function()
        return prototypes.get_tile_filtered({ { filter = "collision-mask", mask = "water-tile" } })
    end)

    if ok_proto and tiles_or_err then
        for _, t in pairs(tiles_or_err) do
            table.insert(water_tile_names, t.name)
        end
    else
        -- fallback to vanilla names
        water_tile_names = { "water", "deepwater", "water-green", "deepwater-green" }
    end

    local all_tiles = {}
    for _, chunk in ipairs(chunks) do
        local tiles = surface.find_tiles_filtered {
            area = chunk.area,
            name = water_tile_names
        }
        for _, tile in ipairs(tiles) do
            table.insert(all_tiles, tile)
        end
    end

    return {
        tiles = all_tiles,
        tile_names = water_tile_names
    }
end

--- Get connected water tiles from a starting position using flood fill
--- @param position table - starting position {x, y}
--- @param water_tile_names table - list of water tile names
--- @return table - connected tiles or empty table if error
function GameState:get_connected_water_tiles(position, water_tile_names)
    local surface = game.surfaces[1]
    if not surface then return {} end

    local ok, connected = pcall(function()
        return surface.get_connected_tiles(position, water_tile_names, true)
    end)

    if not ok or not connected then
        -- Fallback: try without diagonal parameter
        ok, connected = pcall(function()
            return surface.get_connected_tiles(position, water_tile_names)
        end)
    end

    return (ok and connected) or {}
end

--- @class GameState.aliases
--- @field direction table
GameState.aliases = game_state_aliases

function GameState:get_nth_tick_handlers()
    local map_state = self:map()
        if not map_state then return {} end
    return map_state.nth_tick_handlers
end

return GameState
