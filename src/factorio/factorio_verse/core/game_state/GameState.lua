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
--- Methods: agent_state(), entities(), inventory(), power(), get_game(), get_surface()
local GameState = {}
GameState.__index = GameState


--- @return GameState
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
--- @return LuaSurface
function GameState:get_surface()
    local g = self:get_game()
    return g and g.surfaces[1] or nil
end

--- Register a charted area by converting it to chunk coordinates
--- Called after force.chart() to ensure snapshot works on headless servers
--- @param area table - {left_top = {x, y}, right_bottom = {x, y}}
function GameState:register_charted_area(area)
    if not area or not area.left_top or not area.right_bottom then
        return
    end
    
    if not storage.registered_charted_areas then
        storage.registered_charted_areas = {}
    end
    
    -- Convert world coordinates to chunk coordinates
    local min_chunk_x = math.floor(area.left_top.x / 32)
    local min_chunk_y = math.floor(area.left_top.y / 32)
    local max_chunk_x = math.floor(area.right_bottom.x / 32)
    local max_chunk_y = math.floor(area.right_bottom.y / 32)
    
    -- Register each chunk in the area
    for cx = min_chunk_x, max_chunk_x do
        for cy = min_chunk_y, max_chunk_y do
            local chunk_key = utils.chunk_key(cx, cy)
            storage.registered_charted_areas[chunk_key] = { x = cx, y = cy }
        end
    end
end

--- Check if a chunk was registered as charted (fallback for headless servers)
--- @param chunk_x number
--- @param chunk_y number
--- @return boolean
function GameState:is_registered_charted(chunk_x, chunk_y)
    if not storage.registered_charted_areas then
        return false
    end
    local chunk_key = utils.chunk_key(chunk_x, chunk_y)
    return storage.registered_charted_areas[chunk_key] ~= nil
end

--- @return LuaForce
function GameState:get_player_force()
    return game.forces["player"]
end

function GameState:get_visible_chunks(sort_by_distance)
    local surface = self:get_surface()
    local force = self:get_player_force()
    local visible_chunks = {}

    if not (surface and force) then
        return visible_chunks
    end

    for chunk in surface.get_chunks() do
        if force.is_chunk_visible(surface, chunk) then
            table.insert(visible_chunks, { x = chunk.x, y = chunk.y, area = chunk.area })
        end
    end

    if sort_by_distance == true then
        utils.sort_coordinates_by_distance(visible_chunks)
    end

    return visible_chunks
end

function GameState:get_charted_chunks(sort_by_distance)
    local surface = self:get_surface()
    local force = self:get_player_force()
    local charted_chunks = {}
    local generated_count = 0

    if not (surface and force) then
        return charted_chunks
    end

    -- ========================================================================
    -- SOURCE 1: PLAYER-CHARTED CHUNKS (Primary method - most reliable)
    -- ========================================================================
    -- Try to get chunks charted by LuaPlayer characters via force.is_chunk_charted()
    -- This works reliably on:
    --   - Saves where players have explored the map
    --   - Any server with connected LuaPlayer characters
    -- This does NOT work reliably on:
    --   - Headless servers with no connected players (known Factorio limitation)
    --   - force.chart() called but is_chunk_charted() still returns false
    for chunk in surface.get_chunks() do
        generated_count = generated_count + 1
        if force.is_chunk_charted(surface, chunk) then
            table.insert(charted_chunks, { x = chunk.x, y = chunk.y, area = chunk.area })
        end
    end

    -- ========================================================================
    -- SOURCE 2: AGENT-TRACKED CHUNKS (Fallback - headless servers)
    -- ========================================================================
    -- If is_chunk_charted() returned empty, fall back to manually registered areas
    -- This is populated by:
    --   - MapDiscovery:scan_and_discover() (on agent movement)
    --   - MapDiscovery.initialize() (on initial setup)
    -- We explicitly call gs:register_charted_area() because LuaEntity agents
    -- don't auto-chart chunks like LuaPlayer does
    if #charted_chunks == 0 and storage.registered_charted_areas then
        for _, chunk_data in pairs(storage.registered_charted_areas) do
            if chunk_data then
                -- Reconstruct area for registered chunk
                local area = {
                    left_top = { x = chunk_data.x * 32, y = chunk_data.y * 32 },
                    right_bottom = { x = (chunk_data.x + 1) * 32, y = (chunk_data.y + 1) * 32 }
                }
                table.insert(charted_chunks, { x = chunk_data.x, y = chunk_data.y, area = area })
            end
        end
    end

    if sort_by_distance == true then
        utils.sort_coordinates_by_distance(charted_chunks)
    end

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

--- Get all resource entities in specified chunks
--- @param chunks table - list of chunk areas
--- @return table - entities grouped by resource name
function GameState:get_resources_in_chunks(chunks)
    local surface = self:get_surface()
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
    local surface = self:get_surface()
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
    local surface = self:get_surface()
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

return GameState
