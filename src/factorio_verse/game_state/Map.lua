--- factorio_verse/core/game_state/MapGameState.lua
--- MapGameState sub-module for managing map-related functionality.
--- Static module - no instantiation required.

-- Module-level local references for global lookups (performance optimization)
local pairs = pairs
local ipairs = ipairs

local Config = require("Config")
local utils = require("utils.utils")
local Resource = require("game_state.Resource")
local Entities = require("game_state.Entities")
local snapshot = require("utils.snapshot")

local M = {}

function M.get_charted_chunks(sort_by_distance)
    local surface = game.surfaces[1]  -- Uses module-level local 'game'
    local force = M.get_player_force()
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


--- Get all resource entities in specified chunks
--- @param chunks table - list of chunk areas
--- @return table - entities grouped by resource name
function M.get_resources_in_chunks(chunks)
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
function M.get_water_tiles_in_chunks(chunks)
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
function M.get_connected_water_tiles(position, water_tile_names)
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


--- Prints to rcon (as JSON string) or writes to a file the comprehensive state of the map area.
--- This module SHOULD NOT own all the logic; it is a wrapper around helpers exposed by Entities.lua, Inventory.lua, and Resources.lua.
--- Note: This operation is likely to be very heavy.
--- 
--- POSSIBLE SOLUTION: Blueprint logic (e.g., using LuaSurface.create_blueprint or LuaPlayer.can_place_blueprint) might be leveraged to encode/decode map state,
--- but Factorio has hard and soft limits for blueprints:
---   - A blueprint can have no more than 10,000 entities and 10,000 tiles (hard limit; see LuaBlueprintEntity and LuaTile).
---   - Attempting to create blueprints larger than this will fail or be capped; for reference see https://lua-api.factorio.com/latest/LuaBlueprintEntity.html and relevant forum discussions.
--- For comprehensive map state exceeding blueprint limits, chunked or streamed approaches are required; avoid trying to handle large areas as a single blueprint.
function M.get_map_area_state(bounding_box)
end

--- set the state of the map area, state is a JSON string
function M.set_map_area_state(bounding_box, state)
end

function M.clear_map_area(bounding_box)
end

function M.track_chunk_charting()
end

function M.get_player_force()
    return game.forces["player"]
end

--- Register a charted area by converting it to chunk coordinates
--- Called after force.chart() to ensure snapshot works on headless servers
--- @param area table - {left_top = {x, y}, right_bottom = {x, y}}
function M.register_charted_area(area)
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
function M.is_registered_charted(chunk_x, chunk_y)
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
            M.track_chunk_charting()
        end,
    }
}

-- ============================================================================
-- DEFERRED DUMP FOR INITIAL SNAPSHOT
-- ============================================================================

--- Scan once and queue chunks for deferred dump
--- Scans all charted chunks once, then queues them for deferred snapshotting across ticks
--- Only needed for existing saves (not new games)
function M.init_deferred_dump()
    if not storage.snapshot_dump_queue then
        storage.snapshot_dump_queue = {}
    end

    -- Mark dump as in progress
    storage.snapshot_dump_complete = false

    -- Scan once: get all charted chunks
    local charted_chunks = M.get_charted_chunks()
    
    -- Queue all chunks for deferred dump
    for _, chunk in ipairs(charted_chunks) do
        local chunk_key = utils.chunk_key(chunk.x, chunk.y)
        storage.snapshot_dump_queue[chunk_key] = { x = chunk.x, y = chunk.y }
    end

    if #charted_chunks > 0 then
        log("Map: Scanned and queued " .. #charted_chunks .. " chunks for deferred dump")
    else
        -- No chunks to dump, mark as complete immediately
        storage.snapshot_dump_complete = true
    end
end

--- Process one chunk from the dump queue
--- Called on each tick to gradually dump all chunks
--- Returns true if dumping is still in progress, false if complete
--- @return boolean - true if dumping continues, false if complete
function M.process_deferred_dump_queue()
    -- Early exit if dump already complete
    if storage.snapshot_dump_complete then
        return false
    end

    if not storage.snapshot_dump_queue then
        storage.snapshot_dump_complete = true
        return false
    end

    -- Process one chunk per tick
    local chunk_key, chunk_data = next(storage.snapshot_dump_queue)
    if not chunk_key or not chunk_data then
        -- Queue is empty, dump complete
        storage.snapshot_dump_complete = true
        log("Map: Deferred dump complete - all chunks processed")
        return false
    end

    -- Remove from queue
    storage.snapshot_dump_queue[chunk_key] = nil

    -- Dump the chunk (snapshot entities and resources)
    M.snapshot_chunk(chunk_data.x, chunk_data.y)
    
    return true
end

--- Snapshot a single chunk (entities and resources)
--- @param chunk_x number
--- @param chunk_y number
function M.snapshot_chunk(chunk_x, chunk_y)
    local surface = game.surfaces[1]
    if not surface then
        return
    end

    local chunk_area = {
        left_top = { x = chunk_x * 32, y = chunk_y * 32 },
        right_bottom = { x = (chunk_x + 1) * 32, y = (chunk_y + 1) * 32 }
    }

    -- Snapshot entities
    local entities = surface.find_entities_filtered { area = chunk_area }
    for _, entity in ipairs(entities) do
        if entity and entity.valid then
            -- Only snapshot player-placed entities (not resources, trees, etc.)
            -- Resources are handled separately
            -- During initial scan, treat as create (is_update = false)
            if entity.type ~= "resource" and entity.type ~= "tree" and 
               entity.type ~= "simple-entity" and entity.type ~= "corpse" then
                Entities.write_entity_snapshot(entity, false)
            end
        end
    end

    -- Snapshot resources
    local chunk = { x = chunk_x, y = chunk_y, area = chunk_area }
    local gathered = Resource.gather_resources_for_chunk(chunk)

    -- Write resources.jsonl
    local resources_path = snapshot.resource_file_path(chunk_x, chunk_y, "resources")
    snapshot.write_resource_file(resources_path, gathered.resources)

    -- Write water.jsonl
    local water_path = snapshot.resource_file_path(chunk_x, chunk_y, "water")
    snapshot.write_resource_file(water_path, gathered.water)
end

return M