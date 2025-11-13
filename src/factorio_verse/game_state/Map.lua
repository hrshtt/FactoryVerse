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
        -- Check count first for early exit
        local resource_count = surface.count_entities_filtered {
            area = chunk.area,
            type = "resource"
        }
        if resource_count > 0 then
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
        -- Check count first for early exit
        local water_count = surface.count_tiles_filtered {
            area = chunk.area,
            name = water_tile_names
        }
        if water_count > 0 then
            local tiles = surface.find_tiles_filtered {
                area = chunk.area,
                name = water_tile_names
            }
            for _, tile in ipairs(tiles) do
                table.insert(all_tiles, tile)
            end
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
--- Also raises custom event for agent chunk discovery to trigger resource snapshotting
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
    
    -- Register each chunk in the area and raise custom event for resource snapshotting
    for cx = min_chunk_x, max_chunk_x do
        for cy = min_chunk_y, max_chunk_y do
            local chunk_key = utils.chunk_key(cx, cy)
            storage.registered_charted_areas[chunk_key] = { x = cx, y = cy }
            
            -- Raise custom event for agent chunk discovery (triggers resource snapshotting)
            if M.custom_events and M.custom_events.agent_chunk_discovered then
                script.raise_event(M.custom_events.agent_chunk_discovered, {
                    position = { x = cx, y = cy }
                })
            end
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

--- Build disk_write_snapshot event handlers table
--- @return table - {events = {event_id -> handler, ...}}
function M._build_disk_write_snapshot()
    local events = {}
    
    -- on_chunk_generated: snapshot resources if in initial 7x7 area
    events[defines.events.on_chunk_generated] = M._on_chunk_generated
    
    -- on_chunk_charted: snapshot resources for charted chunks
    events[defines.events.on_chunk_charted] = M._on_chunk_charted
    
    -- agent_chunk_discovered: custom event for agent chunk discovery
    if M.custom_events and M.custom_events.agent_chunk_discovered then
        events[M.custom_events.agent_chunk_discovered] = M._on_agent_chunk_discovered
    end
    
    return { events = events }
end

--- Get disk_write_snapshot events
--- @return table - {events = {event_id -> handler, ...}}
function M.get_disk_write_snapshot_events()
    return M.disk_write_snapshot or {}
end

-- ============================================================================
-- INITIALIZATION
-- ============================================================================

-- Custom event IDs (initialized in init())
M.custom_events = {}

--- Initialize Map module
--- Must be called during on_init/on_load
--- Creates custom event for agent chunk discovery and builds event handlers
function M.init()
    -- Generate custom event ID for agent chunk discovery
    M.custom_events.agent_chunk_discovered = script.generate_event_name()
    log("Map: Generated custom event 'agent_chunk_discovered': " .. tostring(M.custom_events.agent_chunk_discovered))
    
    -- Build disk_write_snapshot table after events are initialized
    M.disk_write_snapshot = M._build_disk_write_snapshot()
end

--- Calculate and store initial 7x7 chunk area from spawn position
--- Called during on_init to set up initial chunk boundaries
function M.initialize_initial_chunk_area()
    local surface = game.surfaces[1]
    local force = M.get_player_force()
    if not (surface and force) then
        return
    end

    -- Get spawn position (origin)
    local origin = force.get_spawn_position(surface)
    local origin_chunk = utils.to_chunk_coordinates(origin)
    
    -- Calculate 7x7 chunk area (3 chunks in each direction from center)
    -- Center chunk is at origin_chunk, so range is -3 to +3
    local initial_chunks = {}
    for dx = -3, 3 do
        for dy = -3, 3 do
            local chunk_x = origin_chunk.x + dx
            local chunk_y = origin_chunk.y + dy
            local chunk_key = utils.chunk_key(chunk_x, chunk_y)
            initial_chunks[chunk_key] = { x = chunk_x, y = chunk_y }
        end
    end

    storage.initial_chunk_area = initial_chunks
    log("Map: Initialized 7x7 chunk area (49 chunks) from spawn position")
end

--- Check if a chunk is in the initial 7x7 area
--- @param chunk_x number
--- @param chunk_y number
--- @return boolean
function M.is_in_initial_area(chunk_x, chunk_y)
    if not storage.initial_chunk_area then
        return false
    end
    local chunk_key = utils.chunk_key(chunk_x, chunk_y)
    return storage.initial_chunk_area[chunk_key] ~= nil
end

-- ============================================================================
-- EVENT-DRIVEN RESOURCE SNAPSHOTTING
-- ============================================================================

--- Snapshot resources for a chunk
--- Called by event handlers when chunks are generated/charted/discovered
--- @param chunk_x number
--- @param chunk_y number
function M.snapshot_chunk_resources(chunk_x, chunk_y)
    local surface = game.surfaces[1]
    if not surface then
        return
    end

    local chunk_area = {
        left_top = { x = chunk_x * 32, y = chunk_y * 32 },
        right_bottom = { x = (chunk_x + 1) * 32, y = (chunk_y + 1) * 32 }
    }

    -- Gather resources for the chunk
    local chunk = { x = chunk_x, y = chunk_y, area = chunk_area }
    local gathered = Resource.gather_resources_for_chunk(chunk)

    -- Write resources.jsonl only if resources were found
    if #gathered.resources > 0 then
        local resources_path = snapshot.resource_file_path(chunk_x, chunk_y, "resources")
        local resources_success = snapshot.write_resource_file(resources_path, gathered.resources)
        if resources_success then
            local udp_success = snapshot.send_file_event_udp("file_created", "resource", chunk_x, chunk_y, nil, nil, nil, resources_path)
            if not udp_success and snapshot.DEBUG and game and game.print then
                game.print(string.format("[snapshot] WARNING: Failed to send UDP notification for resource file: %s", resources_path))
            end
        end
    end

    -- Write water.jsonl only if water tiles were found
    if #gathered.water > 0 then
        local water_path = snapshot.resource_file_path(chunk_x, chunk_y, "water")
        local water_success = snapshot.write_resource_file(water_path, gathered.water)
        if water_success then
            local udp_success = snapshot.send_file_event_udp("file_created", "water", chunk_x, chunk_y, nil, nil, nil, water_path)
            if not udp_success and snapshot.DEBUG and game and game.print then
                game.print(string.format("[snapshot] WARNING: Failed to send UDP notification for water file: %s", water_path))
            end
        end
    end

    -- Write trees.jsonl only if trees were found
    if #gathered.trees > 0 then
        local trees_path = snapshot.resource_file_path(chunk_x, chunk_y, "trees")
        local trees_success = snapshot.write_resource_file(trees_path, gathered.trees)
        if trees_success then
            local udp_success = snapshot.send_file_event_udp("file_created", "trees", chunk_x, chunk_y, nil, nil, nil, trees_path)
            if not udp_success and snapshot.DEBUG and game and game.print then
                game.print(string.format("[snapshot] WARNING: Failed to send UDP notification for trees file: %s", trees_path))
            end
        end
    end
end

--- Handle chunk generated event
--- Snapshot resources if chunk is in initial 7x7 area
--- @param event table - on_chunk_generated event
function M._on_chunk_generated(event)
    local chunk_x = event.position.x
    local chunk_y = event.position.y
    
    -- Only snapshot if in initial 7x7 area
    if M.is_in_initial_area(chunk_x, chunk_y) then
        M.snapshot_chunk_resources(chunk_x, chunk_y)
    end
end

--- Handle chunk charted event (by players)
--- Snapshot resources for the charted chunk
--- @param event table - on_chunk_charted event
function M._on_chunk_charted(event)
    local chunk_x = event.position.x
    local chunk_y = event.position.y
    M.snapshot_chunk_resources(chunk_x, chunk_y)
end

--- Handle agent chunk discovered event (custom event)
--- Snapshot resources for the discovered chunk
--- @param event table - agent_chunk_discovered custom event
function M._on_agent_chunk_discovered(event)
    local chunk_x = event.position.x
    local chunk_y = event.position.y
    M.snapshot_chunk_resources(chunk_x, chunk_y)
end

return M