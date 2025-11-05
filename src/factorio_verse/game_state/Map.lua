-- Module-level local references for global lookups (performance optimization)
local pairs = pairs
local ipairs = ipairs

local Config = require("core.Config")
local utils = require("core.utils")

local M = {}
M.__index = M

--- @class MapGameState
--- @field game_state GameState
--- @field resource_state ResourceGameState
--- @field on_demand_snapshots table
--- @field admin_api table
function M:new(game_state)
    local instance = {
        game_state = game_state,
        -- Cache frequently-used sibling modules (constructor-level caching for performance)
        resource_state = game_state.resource_state,
    }
    setmetatable(instance, self)
    return instance
end

function M:get_charted_chunks(sort_by_distance)
    local surface = game.surfaces[1]  -- Uses module-level local 'game'
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

-- Returns chunk coordinates from a position object using Factorio's logic (same as LuaSurface::get_chunk_position)
-- See: https://lua-api.factorio.com/latest/LuaSurface.html#LuaSurface.get_chunk_position
function M:to_chunk_coordinates(position)
    -- position may be {x=..., y=...} or {1=..., 2=...}, prefer .x/.y
    local x = position.x or position[1]
    local y = position.y or position[2]
    local chunk_x = math.floor(x / 32)
    local chunk_y = math.floor(y / 32)
    return { x = chunk_x, y = chunk_y }
end

--- Get all resource entities in specified chunks
--- @param chunks table - list of chunk areas
--- @return table - entities grouped by resource name
function M:get_resources_in_chunks(chunks)
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
function M:get_water_tiles_in_chunks(chunks)
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
function M:get_connected_water_tiles(position, water_tile_names)
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

--- Gather all resources for a specific chunk
--- @param chunk table - {x, y, area}
--- @return table - {resources = {...}, rocks = {...}, trees = {...}, water = {...}}
function M:gather_resources_for_chunk(chunk)
    local surface = game.surfaces[1]

    local gathered = {
        resources = {}, -- Mineable resources (iron, copper, coal, crude-oil, etc.)
        rocks = {},     -- Simple entities (rock-huge, rock-big, etc.)
        trees = {},     -- Tree entities
        water = {}      -- Water tiles
    }

    -- Resources (including crude oil)
    local resources_in_chunk = self:get_resources_in_chunks({ chunk })
    if resources_in_chunk then
        for resource_name, entities in pairs(resources_in_chunk) do
            for _, entity in ipairs(entities) do
                table.insert(gathered.resources, self.resource_state:serialize_resource_tile(entity, resource_name))
            end
        end
    end

    -- Rocks
    local rock_entities = surface.find_entities_filtered({ area = chunk.area, type = "simple-entity" })
    for _, entity in ipairs(rock_entities) do
        if entity.name and (entity.name:match("rock") or entity.name:match("stone")) then
            table.insert(gathered.rocks, self.resource_state:serialize_rock(entity, chunk))
        end
    end

    -- Trees
    local tree_entities = surface.find_entities_filtered({ area = chunk.area, type = "tree" })
    for _, entity in ipairs(tree_entities) do
        table.insert(gathered.trees, self.resource_state:serialize_tree(entity, chunk))
    end

    -- Water
    local water_data = self:get_water_tiles_in_chunks({ chunk })
    if water_data and water_data.tiles then
        for _, tile in ipairs(water_data.tiles) do
            local x, y = utils.extract_position(tile)
            if x and y then
                table.insert(gathered.water, { kind = "water", x = x, y = y, amount = 0 })
            end
        end
    end

    return gathered
end

--- Prints to rcon (as JSON string) or writes to a file the comprehensive state of the map area.
--- This module SHOULD NOT own all the logic; it is a wrapper around helpers exposed by Entities.lua, Inventory.lua, and Resources.lua.
--- Note: This operation is likely to be very heavy.
--- 
--- POSSIBLE SOLUTION: Blueprint logic (e.g., using LuaSurface.create_blueprint or LuaPlayer.can_place_blueprint) might be leveraged to encode/decode map state,
--- but Factorio has hard and soft limits for blueprints:
---   - A blueprint can have no more than 10,000 entities and 10,000 tiles (hard limit; see LuaBlueprintEntity and LuaTile).
---   - Attempting to create blueprints larger than this will fail or be capped; for reference see https://lua-api.factorio.com/latest/LuaBlueprintEntity.html and relevant forum discussions.
--- For comprehensive map state exceeding blueprint limits, chunked or streamed approaches are required; avoid trying to handle large areas as a single blueprint.
function M:get_map_area_state(bounding_box)
end

--- set the state of the map area, state is a JSON string
function M:set_map_area_state(bounding_box, state)
end

function M:clear_map_area(bounding_box)
end

function M:track_chunk_charting()
end

function M:get_player_force()
    return game.forces["player"]
end

--- Register a charted area by converting it to chunk coordinates
--- Called after force.chart() to ensure snapshot works on headless servers
--- @param area table - {left_top = {x, y}, right_bottom = {x, y}}
function M:register_charted_area(area)
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
function M:is_registered_charted(chunk_x, chunk_y)
    if not storage.registered_charted_areas then
        return false
    end
    local chunk_key = utils.chunk_key(chunk_x, chunk_y)
    return storage.registered_charted_areas[chunk_key] ~= nil
end

M.admin_api = {
    get_charted_chunks = M.get_charted_chunks,
    get_map_area_state = M.get_map_area_state,
    set_map_area_state = M.set_map_area_state,
    clear_map_area = M.clear_map_area,
}

M.event_based_snapshot = {
    nth_tick = {
        [60] = function(event)
            M:track_chunk_charting()
        end,
    }
}

return M