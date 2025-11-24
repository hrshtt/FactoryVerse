--- factorio_verse/core/game_state/MapGameState.lua
--- MapGameState sub-module for managing map-related functionality.
--- Static module - no instantiation required.

-- Module-level local references for global lookups (performance optimization)
local pairs = pairs
local ipairs = ipairs

local utils = require("utils.utils")
local Resource = require("game_state.Resource")
local Entities = require("game_state.Entities")
local snapshot = require("utils.snapshot")
local Agent = require("Agent")

--- State tracker for charted chunks for agent utility, uses storage for persistence and registered_metatable for save/load persistence   
---@class ChunkTracker
---@field chunk_lookup table Chunk lookup structure (chunk-first)
--- Structure: chunk_lookup[{c_x, c_y}].resource[resource_name] = true
--- Structure: chunk_lookup[{c_x, c_y}].entities[entity_name] = true
--- Structure: chunk_lookup[{c_x, c_y}].water = true
--- Resource types: copper_ore, iron_ore, uranium_ore, coal, stone, crude_oil
--- Entity types: trees, rocks
local ChunkTracker = {}
ChunkTracker.__index = ChunkTracker

-- ============================================================================
-- METATABLE REGISTRATION (must be at module load time)
-- ====================================================c========================

-- Register metatable for save/load persistence
-- This must happen at module load time, not in on_init/on_load
script.register_metatable('ChunkTracker', ChunkTracker)

-- ============================================================================
-- CHUNK TRACKER CREATION
-- ============================================================================

--- Create or get the singleton ChunkTracker instance
--- @return ChunkTracker
function ChunkTracker:new()
    -- If tracker already exists, return it
    if storage.chunk_tracker then
        return storage.chunk_tracker
    end

    -- Create tracker instance with chunk-first lookup structure
    -- Chunks are added dynamically: chunk_lookup[{c_x, c_y}][category][name] = true
    local tracker = setmetatable({
        chunk_lookup = {}
    }, ChunkTracker)

    -- Store tracker instance
    storage.chunk_tracker = tracker

    return tracker
end

-- ============================================================================
-- CHUNK TRACKER UTILITY METHODS
-- ============================================================================

--- Get or create chunk entry in lookup
--- @param chunk_x number Chunk X coordinate
--- @param chunk_y number Chunk Y coordinate
--- @return table Chunk entry
function ChunkTracker:_get_chunk_entry(chunk_x, chunk_y)
    local chunk_key = chunk_x .. "," .. chunk_y
    local chunk_entry = self.chunk_lookup[chunk_key]
    if not chunk_entry then
        chunk_entry = {
            resource = {},
            entities = {},
            water = false,
            snapshot_tick = nil,  -- Tick when chunk was last snapshotted (nil = not snapshotted yet)
            dirty = false  -- TODO: True if chunk needs re-snapshotting due to mutation (not yet implemented)
        }
        self.chunk_lookup[chunk_key] = chunk_entry
    end
    return chunk_entry
end

--- Mark a chunk as containing a specific resource/entity type
--- @param category string Category: "resource", "entities", or "water"
--- @param name string|nil Resource/entity name (e.g., "copper_ore", "trees"). Required for "resource" and "entities", ignored for "water"
--- @param chunk_x number Chunk X coordinate
--- @param chunk_y number Chunk Y coordinate
function ChunkTracker:mark_chunk_has(category, name, chunk_x, chunk_y)
    local chunk_entry = self:_get_chunk_entry(chunk_x, chunk_y)
    
    if category == "water" then
        chunk_entry.water = true
    elseif category == "resource" then
        if not name then
            error("name parameter is required for 'resource' category")
        end
        chunk_entry.resource[name] = true
    elseif category == "entities" then
        if not name then
            error("name parameter is required for 'entities' category")
        end
        chunk_entry.entities[name] = true
    end
end

--- Check if a chunk contains a specific resource/entity type
--- @param category string Category: "resource", "entities", or "water"
--- @param name string|nil Resource/entity name (e.g., "copper_ore", "trees"). Required for "resource" and "entities", ignored for "water"
--- @param chunk_x number Chunk X coordinate
--- @param chunk_y number Chunk Y coordinate
--- @return boolean
function ChunkTracker:chunk_has(category, name, chunk_x, chunk_y)
    local chunk_key = chunk_x .. "," .. chunk_y
    local chunk_entry = self.chunk_lookup[chunk_key]
    
    if not chunk_entry then
        return false
    end
    
    if category == "water" then
        return chunk_entry.water == true
    elseif category == "resource" then
        if not name then
            return false
        end
        return chunk_entry.resource[name] == true
    elseif category == "entities" then
        if not name then
            return false
        end
        return chunk_entry.entities[name] == true
    end
    
    return false
end

--- Get chunk entry (for accessing all resources/entities at once)
--- @param chunk_x number Chunk X coordinate
--- @param chunk_y number Chunk Y coordinate
--- @return table|nil Chunk entry with resource, entities, water, and snapshot_tick fields
function ChunkTracker:get_chunk_entry(chunk_x, chunk_y)
    local chunk_key = chunk_x .. "," .. chunk_y
    return self.chunk_lookup[chunk_key]
end

--- Check if a chunk has been snapshotted
--- @param chunk_x number Chunk X coordinate
--- @param chunk_y number Chunk Y coordinate
--- @return boolean True if chunk has been snapshotted, false otherwise
function ChunkTracker:is_chunk_snapshotted(chunk_x, chunk_y)
    local chunk_entry = self:get_chunk_entry(chunk_x, chunk_y)
    if not chunk_entry then
        return false
    end
    return chunk_entry.snapshot_tick ~= nil
end

--- Mark a chunk as snapshotted
--- @param chunk_x number Chunk X coordinate
--- @param chunk_y number Chunk Y coordinate
--- @return boolean Success status
function ChunkTracker:mark_chunk_snapshotted(chunk_x, chunk_y)
    local chunk_entry = self:_get_chunk_entry(chunk_x, chunk_y)
    chunk_entry.snapshot_tick = game and game.tick or 0
    chunk_entry.dirty = false
    return true
end

--- Mark a chunk as needing snapshotting (e.g., when charted)
--- Creates chunk entry if it doesn't exist (with snapshot_tick = nil)
--- IMPORTANT: This just sets the flag - on_tick handler will check and process
--- Agents should overwrite flags, not read them, for safe control flow
--- NOTE: Will not re-queue chunks that have already been snapshotted
--- @param chunk_x number Chunk X coordinate
--- @param chunk_y number Chunk Y coordinate
function ChunkTracker:mark_chunk_needs_snapshot(chunk_x, chunk_y)
    local chunk_entry = self:_get_chunk_entry(chunk_x, chunk_y)
    -- Never re-snapshot an existing chunk
    -- If chunk has already been snapshotted, do nothing
    if chunk_entry.snapshot_tick ~= nil then
        -- Chunk has already been snapshotted, don't re-queue it
        return
    end
    -- Chunk entry already has snapshot_tick = nil (needs snapshotting)
    -- No change needed, chunk will be processed by on_tick handler
end

--- Mark a chunk as dirty (needs re-snapshotting due to mutation)
--- TODO: Implement entity mutation tracking to call this function when:
---   - Entities are placed/destroyed in a chunk
---   - Resources are mined/depleted in a chunk
---   - Other chunk mutations occur
--- Once implemented, update chunk_needs_snapshot() and _on_tick_snapshot_chunks() to check dirty flag
--- @param chunk_x number Chunk X coordinate
--- @param chunk_y number Chunk Y coordinate
function ChunkTracker:mark_chunk_dirty(chunk_x, chunk_y)
    local chunk_entry = self:_get_chunk_entry(chunk_x, chunk_y)
    chunk_entry.dirty = true
end

--- Check if a chunk needs snapshotting (never snapshotted)
--- Never returns true for chunks that have already been snapshotted
--- TODO: When mark_chunk_dirty() is implemented, add: or chunk_entry.dirty == true
--- @param chunk_x number Chunk X coordinate
--- @param chunk_y number Chunk Y coordinate
--- @return boolean True if chunk needs snapshotting
function ChunkTracker:chunk_needs_snapshot(chunk_x, chunk_y)
    local chunk_entry = self:get_chunk_entry(chunk_x, chunk_y)
    if not chunk_entry then
        return false
    end
    -- Only return true if chunk has never been snapshotted
    -- TODO: Add dirty check when mark_chunk_dirty() is implemented: or chunk_entry.dirty == true
    return chunk_entry.snapshot_tick == nil
end


local M = {}

-- ============================================================================
-- CHUNK TRACKER HELPER FUNCTIONS
-- ============================================================================

--- Map Factorio resource entity names to ChunkTracker resource names
--- Converts hyphenated names to underscore names (e.g., "copper-ore" -> "copper_ore")
--- @param factorio_name string Factorio resource entity name
--- @return string|nil Tracker resource name, or nil if not a tracked resource
local function map_resource_name(factorio_name)
    local resource_map = {
        ["copper-ore"] = "copper_ore",
        ["iron-ore"] = "iron_ore",
        ["uranium-ore"] = "uranium_ore",
        ["coal"] = "coal",
        ["stone"] = "stone",
        ["crude-oil"] = "crude_oil"
    }
    return resource_map[factorio_name]
end

function M.get_charted_chunks(sort_by_distance)
    local surface = game.surfaces[1]  -- Uses module-level local 'game'
    local force = M.get_player_force()
    local charted_chunks = {}

    if not (surface and force) then
        return charted_chunks
    end

    -- Get chunks charted by player force via force.is_chunk_charted()
    -- This works reliably on:
    --   - Saves where players have explored the map
    --   - Any server with connected LuaPlayer characters
    -- This does NOT work reliably on:
    --   - Headless servers with no connected players (known Factorio limitation)
    --   - force.chart() called but is_chunk_charted() still returns false
    -- Note: Agents now track their own charted chunks via Agent.charted_chunks field
    for chunk in surface.get_chunks() do
        if force.is_chunk_charted(surface, chunk) then
            table.insert(charted_chunks, { x = chunk.x, y = chunk.y, area = chunk.area })
        end
    end

    if sort_by_distance == true then
        utils.sort_coordinates_by_distance(charted_chunks)
    end

    return charted_chunks
end


--- Get all resource entities in specified chunks
--- Also updates ChunkTracker to mark chunks containing resources
--- @param chunks table - list of chunk areas {x, y, area}
--- @return table - entities grouped by resource name
function M.get_resources_in_chunks(chunks)
    local surface = game.surfaces[1]
    if not surface then return {} end

    local tracker = M.get_chunk_tracker()
    local resources_by_name = {}

    for _, chunk in ipairs(chunks) do
        local chunk_x = chunk.x
        local chunk_y = chunk.y
        
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

            -- Track unique resource types found in this chunk
            local tracked_resources = {}

            for _, entity in ipairs(entities) do
                local name = entity.name
                if not resources_by_name[name] then
                    resources_by_name[name] = {}
                end
                table.insert(resources_by_name[name], entity)
                
                -- Map Factorio resource name to tracker name and mark in ChunkTracker
                local tracker_name = map_resource_name(name)
                if tracker_name and not tracked_resources[tracker_name] then
                    tracker:mark_chunk_has("resource", tracker_name, chunk_x, chunk_y)
                    tracked_resources[tracker_name] = true
                end
            end
        end
    end

    return resources_by_name
end

--- Get water tiles using prototype detection for mod compatibility
--- Also updates ChunkTracker to mark chunks containing water tiles
--- @param chunks table - list of chunk areas {x, y, area}
--- @return table - water tiles and tile names
function M.get_water_tiles_in_chunks(chunks)
    local surface = game.surfaces[1]
    if not surface then return { tiles = {}, tile_names = {} } end

    local tracker = M.get_chunk_tracker()

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
        local chunk_x = chunk.x
        local chunk_y = chunk.y
        
        -- Check count first for early exit
        local water_count = surface.count_tiles_filtered {
            area = chunk.area,
            name = water_tile_names
        }
        if water_count > 0 then
            -- Mark chunk as having water in ChunkTracker
            tracker:mark_chunk_has("water", nil, chunk_x, chunk_y)
            
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

--- Get entities in a chunk (trees and rocks)
--- Also updates ChunkTracker to mark chunks containing trees and rocks
--- TODO: Move entity chunk lookups from Entities module to Map module (avoid circular deps)
--- @param chunk table - chunk area {x, y, area}
--- @return table - entities in chunk grouped by type
function M.get_entities_in_chunk(chunk)
    local surface = game.surfaces[1]
    if not surface then return {} end

    local tracker = M.get_chunk_tracker()
    local chunk_x = chunk.x
    local chunk_y = chunk.y
    
    local entities_by_type = {
        trees = {},
        rocks = {}
    }
    
    -- Find trees in chunk
    local tree_count = surface.count_entities_filtered {
        area = chunk.area,
        type = "tree"
    }
    if tree_count > 0 then
        local trees = surface.find_entities_filtered {
            area = chunk.area,
            type = "tree"
        }
        for _, tree in ipairs(trees) do
            table.insert(entities_by_type.trees, tree)
        end
        -- Mark chunk as having trees
        tracker:mark_chunk_has("entities", "trees", chunk_x, chunk_y)
    end
    
    -- Find rocks (simple-entities) in chunk
    -- Rocks are typically simple-entity type with names like "rock-big", "rock-huge", etc.
    local rock_count = surface.count_entities_filtered {
        area = chunk.area,
        type = "simple-entity"
    }
    if rock_count > 0 then
        local simple_entities = surface.find_entities_filtered {
            area = chunk.area,
            type = "simple-entity"
        }
        -- Filter for rocks (entities that are mineable and produce stone)
        for _, entity in ipairs(simple_entities) do
            if entity.valid and entity.prototype.mineable_properties then
                local products = entity.prototype.mineable_properties.products
                -- Check if it produces stone (typical rock behavior)
                local is_rock = false
                if products then
                    for _, product in ipairs(products) do
                        if product.name == "stone" then
                            is_rock = true
                            break
                        end
                    end
                end
                if is_rock then
                    table.insert(entities_by_type.rocks, entity)
                end
            end
        end
        -- Mark chunk as having rocks if any were found
        if #entities_by_type.rocks > 0 then
            tracker:mark_chunk_has("entities", "rocks", chunk_x, chunk_y)
        end
    end
    
    return entities_by_type
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

function M.get_player_force()
    return game.forces["player"]
end

function M.get_chunk_lookup()
    return M.get_chunk_tracker().chunk_lookup
end


M.admin_api = {
    get_charted_chunks = M.get_charted_chunks,
    get_map_area_state = M.get_map_area_state,
    set_map_area_state = M.set_map_area_state,
    clear_map_area = M.clear_map_area,
    get_chunk_lookup = M.get_chunk_lookup,
}

M.event_based_snapshot = {}

--- Build disk_write_snapshot event handlers table
--- @return table - {events = {event_id -> handler, ...}}
function M._build_disk_write_snapshot()
    local events = {}
    
    -- on_chunk_charted: mark chunks for snapshotting when charted by players
    events[defines.events.on_chunk_charted] = M._on_chunk_charted
    
    -- Agent.on_chunk_charted: mark chunks for snapshotting when charted by agents
    -- Note: Agents also mark chunks directly in charting.lua, but this handles the event for consistency
    if Agent.on_chunk_charted then
        events[Agent.on_chunk_charted] = M._on_agent_chunk_charted
    end
    
    return { events = events }
end

--- Process one chunk snapshot per tick (serialized snapshotting)
--- Only snapshots chunks that have never been snapshotted before
--- TODO: When mark_chunk_dirty() is implemented, also process chunks with dirty == true
--- @param event table on_tick event
function M._on_tick_snapshot_chunks(event)
    -- game.print(string.format("[snapshot] Processing chunks on tick %d", game.tick))
    local tracker = M.get_chunk_tracker()
    local chunk_x, chunk_y = nil, nil
    for chunk_key, chunk_entry in pairs(tracker.chunk_lookup) do
        -- Only process chunks that have never been snapshotted (snapshot_tick == nil)
        -- Never re-snapshot existing chunks
        -- TODO: When mark_chunk_dirty() is implemented, add: or chunk_entry.dirty == true
        if chunk_key and chunk_entry.snapshot_tick == nil then
            if snapshot.DEBUG and game and game.print then
                game.print(string.format("[snapshot] Found chunk to process: %s", chunk_key))
            end
            local xstr, ystr = string.match(chunk_key, "([^,]+),([^,]+)")
            chunk_x = tonumber(xstr)
            chunk_y = tonumber(ystr)
            break
        end
    end
    
    if chunk_x and chunk_y then
        -- Double-check that chunk still needs snapshotting (may have been processed by another handler)
        if not tracker:chunk_needs_snapshot(chunk_x, chunk_y) then
            return
        end
        
        if snapshot.DEBUG and game and game.print then
            game.print(string.format("[snapshot] Processing chunk (%d, %d)", chunk_x, chunk_y))
        end
        
        -- Snapshot the chunk (this will mark it as snapshotted on success)
        local success = M.snapshot_chunk_resources(chunk_x, chunk_y)
        
        if not success and snapshot.DEBUG and game and game.print then
            game.print(string.format("[snapshot] WARNING: Failed to snapshot chunk (%d, %d)", chunk_x, chunk_y))
        end
    -- else
    --     -- Debug: uncomment to verify handler is running when no chunks need snapshotting
    --     -- if snapshot.DEBUG and game and game.print then
    --     --     game.print("[snapshot] No chunks need snapshotting")
    --     -- end
    end
end

--- Get on_tick handlers
--- @return table Array of handler functions
function M.get_on_tick_handlers()
    return {
        M._on_tick_snapshot_chunks
    }
end

--- Get events (defined events and nth_tick)
--- @return table {defined_events = {event_id -> handler, ...}, nth_tick = {tick_interval -> handler, ...}}
function M.get_events()
    local events = {}
    local nth_tick = {}
    
    -- Add event_based_snapshot events
    if M.event_based_snapshot then
        if M.event_based_snapshot.nth_tick then
            for tick_interval, handler in pairs(M.event_based_snapshot.nth_tick) do
                nth_tick[tick_interval] = handler
            end
        end
    end
    
    -- Add disk_write_snapshot events
    if M.disk_write_snapshot then
        if M.disk_write_snapshot.events then
            for event_id, handler in pairs(M.disk_write_snapshot.events) do
                events[event_id] = handler
            end
        end
        if M.disk_write_snapshot.nth_tick then
            for tick_interval, handler in pairs(M.disk_write_snapshot.nth_tick) do
                nth_tick[tick_interval] = nth_tick[tick_interval] or {}
                if type(nth_tick[tick_interval]) == "table" then
                    table.insert(nth_tick[tick_interval], handler)
                else
                    nth_tick[tick_interval] = handler
                end
            end
        end
    end
    
    return {
        defined_events = events,
        nth_tick = nth_tick
    }
end

--- Register remote interface for map admin methods
--- @return table Remote interface table
function M.register_remote_interface()
    return M.admin_api
end

-- ============================================================================
-- INITIALIZATION
-- ============================================================================

--- Initialize Map module
--- Must be called during on_init/on_load
--- Builds event handlers for resource snapshotting
function M.init()
    -- Initialize ChunkTracker singleton
    ChunkTracker:new()
    
    -- Build disk_write_snapshot table after events are initialized
    M.disk_write_snapshot = M._build_disk_write_snapshot()
end

--- Get the ChunkTracker singleton instance
--- @return ChunkTracker
function M.get_chunk_tracker()
    return ChunkTracker:new()
end


-- ============================================================================
-- EVENT-DRIVEN RESOURCE SNAPSHOTTING
-- ============================================================================

--- Snapshot resources for a chunk
--- Called by on_tick handler to serialize snapshotting (one chunk per tick)
--- Also updates ChunkTracker with resource/entity/water tracking
--- Never snapshots chunks that have already been snapshotted
--- @param chunk_x number
--- @param chunk_y number
function M.snapshot_chunk_resources(chunk_x, chunk_y)
    local surface = game.surfaces[1]
    if not surface then
        return false
    end

    local tracker = M.get_chunk_tracker()
    
    -- Defensive check: never snapshot a chunk that has already been snapshotted
    if tracker:is_chunk_snapshotted(chunk_x, chunk_y) then
        if snapshot.DEBUG and game and game.print then
            game.print(string.format("[snapshot] Skipping chunk (%d, %d) - already snapshotted", chunk_x, chunk_y))
        end
        return false
    end

    local chunk_area = {
        left_top = { x = chunk_x * 32, y = chunk_y * 32 },
        right_bottom = { x = chunk_x * 32 + 31, y = chunk_y * 32 + 31 }
    }

    -- Gather resources for the chunk
    local chunk = { x = chunk_x, y = chunk_y, area = chunk_area }
    local gathered = Resource.gather_resources_for_chunk(chunk)
    
    -- Update ChunkTracker with gathered data
    -- Track resources
    local tracked_resources = {}
    for _, resource_data in ipairs(gathered.resources) do
        local tracker_name = map_resource_name(resource_data.kind)
        if tracker_name and not tracked_resources[tracker_name] then
            tracker:mark_chunk_has("resource", tracker_name, chunk_x, chunk_y)
            tracked_resources[tracker_name] = true
        end
    end
    
    -- Track water
    if #gathered.water > 0 then
        tracker:mark_chunk_has("water", nil, chunk_x, chunk_y)
    end
    
    -- Track trees
    if #gathered.trees > 0 then
        tracker:mark_chunk_has("entities", "trees", chunk_x, chunk_y)
    end
    
    -- Track rocks
    if #gathered.rocks > 0 then
        tracker:mark_chunk_has("entities", "rocks", chunk_x, chunk_y)
    end

    -- Write tiles.jsonl (resource tiles like ores) only if resources were found
    if #gathered.resources > 0 then
        local tiles_path = snapshot.resource_file_path(chunk_x, chunk_y, "tiles")
        local tiles_success = snapshot.write_resource_file(tiles_path, gathered.resources)
        if tiles_success then
            local udp_success = snapshot.send_file_event_udp("file_created", "resource", chunk_x, chunk_y, nil, nil, nil, tiles_path)
            if not udp_success and snapshot.DEBUG and game and game.print then
                game.print(string.format("[snapshot] WARNING: Failed to send UDP notification for tiles file: %s", tiles_path))
            end
        end
    end

    -- Write water-tiles.jsonl only if water tiles were found
    if #gathered.water > 0 then
        local water_tiles_path = snapshot.resource_file_path(chunk_x, chunk_y, "water-tiles")
        local water_tiles_success = snapshot.write_resource_file(water_tiles_path, gathered.water)
        if water_tiles_success then
            local udp_success = snapshot.send_file_event_udp("file_created", "water", chunk_x, chunk_y, nil, nil, nil, water_tiles_path)
            if not udp_success and snapshot.DEBUG and game and game.print then
                game.print(string.format("[snapshot] WARNING: Failed to send UDP notification for water-tiles file: %s", water_tiles_path))
            end
        end
    end

    -- Write entities.jsonl (rocks and trees combined) only if entities were found
    local entities = {}
    for _, rock in ipairs(gathered.rocks) do
        table.insert(entities, rock)
    end
    for _, tree in ipairs(gathered.trees) do
        table.insert(entities, tree)
    end
    if #entities > 0 then
        local entities_path = snapshot.resource_file_path(chunk_x, chunk_y, "entities")
        local entities_success = snapshot.write_resource_file(entities_path, entities)
        if entities_success then
            local udp_success = snapshot.send_file_event_udp("file_created", "entity", chunk_x, chunk_y, nil, nil, nil, entities_path)
            if not udp_success and snapshot.DEBUG and game and game.print then
                game.print(string.format("[snapshot] WARNING: Failed to send UDP notification for entities file: %s", entities_path))
            end
        end
    end

    -- Mark chunk as snapshotted after successfully processing (even if no resources/water/entities found)
    -- This prevents re-processing the same chunk when discovered again by agents or players
    -- IMPORTANT: This must be called to prevent infinite re-processing of the same chunk
    tracker:mark_chunk_snapshotted(chunk_x, chunk_y)
    
    return true
end

--- Handle chunk charted event (by players)
--- Mark chunk as needing snapshot (on_tick handler will process it)
--- @param event table - on_chunk_charted event
function M._on_chunk_charted(event)
    local chunk_x = event.position.x
    local chunk_y = event.position.y
    local tracker = M.get_chunk_tracker()
    tracker:mark_chunk_needs_snapshot(chunk_x, chunk_y)
end

--- Handle agent chunk charted event
--- Mark chunk as needing snapshot (on_tick handler will process it)
--- Note: Agents also mark chunks directly in charting.lua, but this handles the event for consistency
--- @param event table - Agent.on_chunk_charted event with {chunk_x, chunk_y}
function M._on_agent_chunk_charted(event)
    local chunk_x = event.chunk_x
    local chunk_y = event.chunk_y
    local tracker = M.get_chunk_tracker()
    tracker:mark_chunk_needs_snapshot(chunk_x, chunk_y)
end

return M