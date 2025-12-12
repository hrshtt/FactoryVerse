--- factorio_verse/core/game_state/MapGameState.lua
--- MapGameState sub-module for managing map-related functionality.
--- Static module - no instantiation required.

-- Module-level local references for global lookups (performance optimization)
local pairs = pairs
local ipairs = ipairs
-- local math_min = math.min
local table_insert = table.insert
local table_concat = table.concat

local utils = require("utils.utils")
local Resource = require("game_state.Resource")
-- local Entities = require("game_state.Entities")
local snapshot = require("utils.snapshot")
local serialize = require("utils.serialize")
local Agent = require("Agent")

-- ============================================================================
-- SNAPSHOT STATE MACHINE - Spreads chunk processing across multiple ticks
-- ============================================================================
-- 
-- The state machine processes ONE chunk at a time, but spreads the work for
-- that chunk across multiple ticks to avoid freezing the game.
--
-- Phases:
--   IDLE           -> No chunk being processed, look for next pending chunk
--   FIND_ENTITIES  -> Run find_entities_filtered calls (expensive!)
--   SERIALIZE      -> Serialize gathered data to JSON strings (batched)
--   WRITE          -> Write files to disk (batched, most expensive!)
--   COMPLETE       -> Mark chunk as done, transition to IDLE
--
-- Configuration:
--   ENTITIES_PER_TICK   - Max entities to serialize per tick
--   WRITES_PER_TICK     - Max file writes per tick (disk I/O is blocking!)
--   TILES_PER_TICK      - Max tiles to process per tick

local SnapshotPhase = {
    IDLE = 0,
    FIND_ENTITIES = 1,
    SERIALIZE = 2,
    WRITE = 3,
    COMPLETE = 4,
}

-- Tunable performance parameters
-- These control how much work is done per tick
local SnapshotConfig = {
    -- Entity serialization budget per tick
    -- Serializing involves accessing entity properties and building Lua tables
    ENTITIES_PER_TICK = 100,
    
    -- Tile processing budget per tick (water tiles, resource tiles)
    -- Tiles are simpler than entities but there can be thousands per chunk
    TILES_PER_TICK = 500,
    
    -- File writes per tick (MOST EXPENSIVE - disk I/O is blocking!)
    -- Each helpers.write_file call blocks the game until complete
    WRITES_PER_TICK = 3,
    
    -- JSON serializations per tick (helpers.table_to_json calls)
    -- Less expensive than disk I/O but still has overhead
    SERIALIZATIONS_PER_TICK = 200,
}

--- Snapshot state stored in storage for persistence across saves
--- @class SnapshotState
--- @field phase number Current phase (SnapshotPhase enum)
--- @field chunk_x number|nil Current chunk X coordinate
--- @field chunk_y number|nil Current chunk Y coordinate
--- @field gathered table|nil Gathered entity/resource data from FIND_ENTITIES phase
--- @field serialized table|nil Serialized JSON strings ready for writing
--- @field serialize_index number Current index in serialization batch
--- @field write_queue table Array of {path, content} pending writes
--- @field write_index number Current index in write queue

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

-- ============================================================================
-- SNAPSHOT STATE MACHINE HELPERS
-- These must be defined before get_snapshot_status() and admin_api
-- ============================================================================

--- Get or initialize the snapshot state machine state
--- @return SnapshotState
local function get_snapshot_state()
    if not storage.snapshot_state then
        storage.snapshot_state = {
            phase = SnapshotPhase.IDLE,
            chunk_x = nil,
            chunk_y = nil,
            gathered = nil,
            serialized = nil,
            serialize_index = 1,
            write_queue = {},
            write_index = 1,
        }
    end
    return storage.snapshot_state
end

--- Reset snapshot state to IDLE
local function reset_snapshot_state()
    local state = get_snapshot_state()
    state.phase = SnapshotPhase.IDLE
    state.chunk_x = nil
    state.chunk_y = nil
    state.gathered = nil
    state.serialized = nil
    state.serialize_index = 1
    state.write_queue = {}
    state.write_index = 1
end

--- Find next chunk that needs snapshotting
--- @return number|nil chunk_x
--- @return number|nil chunk_y
local function find_next_pending_chunk()
    local tracker = M.get_chunk_tracker()
    for chunk_key, chunk_entry in pairs(tracker.chunk_lookup) do
        if chunk_key and chunk_entry.snapshot_tick == nil then
            local xstr, ystr = string.match(chunk_key, "([^,]+),([^,]+)")
            return tonumber(xstr), tonumber(ystr)
        end
    end
    return nil, nil
end

--- Get current snapshot state machine status
--- @return table Status info including phase, current chunk, queue sizes
function M.get_snapshot_status()
    local state = get_snapshot_state()
    local tracker = M.get_chunk_tracker()
    
    -- Count pending chunks
    local pending_count = 0
    local completed_count = 0
    for _, chunk_entry in pairs(tracker.chunk_lookup) do
        if chunk_entry.snapshot_tick == nil then
            pending_count = pending_count + 1
        else
            completed_count = completed_count + 1
        end
    end
    
    local phase_names = {
        [SnapshotPhase.IDLE] = "IDLE",
        [SnapshotPhase.FIND_ENTITIES] = "FIND_ENTITIES",
        [SnapshotPhase.SERIALIZE] = "SERIALIZE",
        [SnapshotPhase.WRITE] = "WRITE",
        [SnapshotPhase.COMPLETE] = "COMPLETE",
    }
    
    return {
        phase = phase_names[state.phase] or "UNKNOWN",
        phase_id = state.phase,
        current_chunk = state.chunk_x and { x = state.chunk_x, y = state.chunk_y } or nil,
        pending_chunks = pending_count,
        completed_chunks = completed_count,
        serialize_index = state.serialize_index,
        write_queue_size = state.write_queue and #state.write_queue or 0,
        write_index = state.write_index,
        config = {
            entities_per_tick = SnapshotConfig.ENTITIES_PER_TICK,
            tiles_per_tick = SnapshotConfig.TILES_PER_TICK,
            writes_per_tick = SnapshotConfig.WRITES_PER_TICK,
            serializations_per_tick = SnapshotConfig.SERIALIZATIONS_PER_TICK,
        },
    }
end

--- Update snapshot config at runtime
--- @param config table Partial config to merge (e.g., {writes_per_tick = 5})
function M.set_snapshot_config(config)
    if not config then return end
    if config.entities_per_tick then
        SnapshotConfig.ENTITIES_PER_TICK = config.entities_per_tick
    end
    if config.tiles_per_tick then
        SnapshotConfig.TILES_PER_TICK = config.tiles_per_tick
    end
    if config.writes_per_tick then
        SnapshotConfig.WRITES_PER_TICK = config.writes_per_tick
    end
    if config.serializations_per_tick then
        SnapshotConfig.SERIALIZATIONS_PER_TICK = config.serializations_per_tick
    end
end

M.admin_api = {
    get_charted_chunks = M.get_charted_chunks,
    get_map_area_state = M.get_map_area_state,
    set_map_area_state = M.set_map_area_state,
    clear_map_area = M.clear_map_area,
    get_chunk_lookup = M.get_chunk_lookup,
    get_snapshot_status = M.get_snapshot_status,
    set_snapshot_config = M.set_snapshot_config,
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

--- PHASE: FIND_ENTITIES - Gather all entities/resources/tiles for the chunk
--- This phase does the expensive find_entities_filtered calls
--- We do all finds in one tick since splitting them would require complex state
--- @param state SnapshotState
--- @param chunk_x number
--- @param chunk_y number
local function phase_find_entities(state, chunk_x, chunk_y)
    local surface = game.surfaces[1]
    if not surface then
        reset_snapshot_state()
        return
    end
    
    -- NOTE: Factorio chunk is 32x32 tiles. For area-based APIs (find/count_*_filtered),
    -- use a full chunk bounding box with right_bottom at the next tile coordinate.
    -- This avoids missing the last row/column of the chunk (which can create "gaps"
    -- between adjacent chunks and fragment connected components like water).
    local chunk_area = {
        left_top = { x = chunk_x * 32, y = chunk_y * 32 },
        right_bottom = { x = (chunk_x + 1) * 32, y = (chunk_y + 1) * 32 }
    }
    local chunk = { x = chunk_x, y = chunk_y, area = chunk_area }
    
    -- Gather all data using Resource module (this does the find_entities_filtered calls)
    local gathered = Resource.gather_resources_for_chunk(chunk)
    
    -- Also gather player-placed entities (excluding ghosts)
    local player_entities = {}
    local entity_count = surface.count_entities_filtered {
        area = chunk_area,
        force = "player",
    }
    if entity_count > 0 then
        local all_entities = surface.find_entities_filtered {
            area = chunk_area,
            force = "player",
        }
        -- Filter out ghosts from player entities
        for _, entity in ipairs(all_entities) do
            if entity and entity.valid and entity.type ~= "entity-ghost" then
                table.insert(player_entities, entity)
            end
        end
    end
    
    -- Gather ghosts separately (for top-level ghosts-init.jsonl)
    local ghosts = {}
    local ghost_count = surface.count_entities_filtered {
        area = chunk_area,
        type = "entity-ghost",
    }
    if ghost_count > 0 then
        ghosts = surface.find_entities_filtered {
            area = chunk_area,
            type = "entity-ghost",
        }
    end
    
    -- Store gathered data in state
    state.gathered = {
        resources = gathered.resources,
        water = gathered.water,
        trees = gathered.trees,
        rocks = gathered.rocks,
        player_entities = player_entities,
        ghosts = ghosts,
        chunk = chunk,
    }
    
    -- Initialize serialization state
    state.serialized = {
        resources_json = {},      -- Array of JSON strings for tiles.jsonl
        water_json = {},          -- Array of JSON strings for water-tiles.jsonl
        entities_json = {},       -- Array of JSON strings for entities.jsonl (trees+rocks)
        player_entity_data = {},  -- Array of {entity, data} for individual entity files
        ghosts_json = {},         -- Array of JSON strings for top-level ghosts-init.jsonl
    }
    state.serialize_index = 1
    
    -- Transition to SERIALIZE phase
    state.phase = SnapshotPhase.SERIALIZE
    
    if snapshot.DEBUG and game and game.print then
        local total = #gathered.resources + #gathered.water + #gathered.trees + #gathered.rocks + #player_entities + #ghosts
        game.print(string.format("[snapshot] FIND_ENTITIES complete for chunk (%d, %d): %d items to serialize (%d ghosts)",
            chunk_x, chunk_y, total, #ghosts))
    end
end

--- PHASE: SERIALIZE - Convert gathered data to JSON strings (batched)
--- @param state SnapshotState
local function phase_serialize(state)
    local gathered = state.gathered
    local serialized = state.serialized
    local budget = SnapshotConfig.SERIALIZATIONS_PER_TICK
    local processed = 0
    local idx = state.serialize_index
    
    -- Calculate total items to serialize
    local total_resources = #gathered.resources
    local total_water = #gathered.water
    local total_trees = #gathered.trees
    local total_rocks = #gathered.rocks
    local total_player = #gathered.player_entities
    local total_ghosts = (gathered.ghosts and #gathered.ghosts) or 0
    local total_trees_rocks = total_trees + total_rocks
    
    -- Serialize resources (tiles.jsonl)
    while idx <= total_resources and processed < budget do
        local resource = gathered.resources[idx]
        local ok, json_str = pcall(helpers.table_to_json, resource)
        if ok and json_str then
            table_insert(serialized.resources_json, json_str)
        end
        idx = idx + 1
        processed = processed + 1
    end
    
    -- Serialize water tiles (water-tiles.jsonl)
    local water_start = total_resources + 1
    while idx >= water_start and idx < water_start + total_water and processed < budget do
        local water_idx = idx - total_resources
        local water = gathered.water[water_idx]
        local ok, json_str = pcall(helpers.table_to_json, water)
        if ok and json_str then
            table_insert(serialized.water_json, json_str)
        end
        idx = idx + 1
        processed = processed + 1
    end
    
    -- Serialize trees and rocks (entities.jsonl)
    local entities_start = water_start + total_water
    while idx >= entities_start and idx < entities_start + total_trees_rocks and processed < budget do
        local entity_idx = idx - total_resources - total_water
        local entity_data
        if entity_idx <= total_trees then
            entity_data = gathered.trees[entity_idx]
        else
            entity_data = gathered.rocks[entity_idx - total_trees]
        end
        if entity_data then
            local ok, json_str = pcall(helpers.table_to_json, entity_data)
            if ok and json_str then
                table_insert(serialized.entities_json, json_str)
            end
        end
        idx = idx + 1
        processed = processed + 1
    end
    
    -- Serialize player-placed entities (individual files)
    local player_start = entities_start + total_trees_rocks
    while idx >= player_start and idx < player_start + total_player and processed < budget do
        local player_idx = idx - total_resources - total_water - total_trees_rocks
        local entity = gathered.player_entities[player_idx]
        if entity and entity.valid then
            -- Use serialize module's serialization
            local entity_data = serialize.serialize_entity(entity)
            if entity_data then
                table_insert(serialized.player_entity_data, {
                    entity = entity,
                    data = entity_data,
                })
            end
        end
        idx = idx + 1
        processed = processed + 1
    end
    
    -- Serialize ghosts (for top-level ghosts-init.jsonl)
    local ghosts_start = player_start + total_player
    while idx >= ghosts_start and idx < ghosts_start + total_ghosts and processed < budget do
        local ghost_idx = idx - total_resources - total_water - total_trees_rocks - total_player
        local ghost = (gathered.ghosts and gathered.ghosts[ghost_idx]) or nil
        if ghost and ghost.valid then
            -- Use serialize module's ghost serialization
            local ghost_data = serialize.serialize_ghost(ghost)
            if ghost_data then
                -- Add chunk info to ghost data for tracking
                ghost_data.chunk = { x = state.chunk_x, y = state.chunk_y }
                local ok, json_str = pcall(helpers.table_to_json, ghost_data)
                if ok and json_str then
                    table_insert(serialized.ghosts_json, json_str)
                end
            end
        end
        idx = idx + 1
        processed = processed + 1
    end
    
    state.serialize_index = idx
    
    -- Check if serialization is complete
    local total_items = total_resources + total_water + total_trees_rocks + total_player + total_ghosts
    if idx > total_items then
        -- Build write queue - NEW APPROACH: single JSONL files per category
        state.write_queue = {}
        state.write_index = 1
        local chunk_x = state.chunk_x
        local chunk_y = state.chunk_y

        -- if not serialized then
        --     return
        -- end
        
        -- Queue resources_init.jsonl write (ore tiles)
        if #serialized.resources_json > 0 then
            local content = table_concat(serialized.resources_json, "\n") .. "\n"
            local path = snapshot.resources_init_path(chunk_x, chunk_y)
            table_insert(state.write_queue, {
                path = path,
                content = content,
                file_type = "resource",
                event_type = "file_created",
            })
        end
        
        -- Queue water_init.jsonl write
        if #serialized.water_json > 0 then
            local content = table_concat(serialized.water_json, "\n") .. "\n"
            local path = snapshot.water_init_path(chunk_x, chunk_y)
            table_insert(state.write_queue, {
                path = path,
                content = content,
                file_type = "water",
                event_type = "file_created",
            })
        end
        
        -- Queue trees_rocks_init.jsonl write (trees + rocks)
        if #serialized.entities_json > 0 then
            local content = table_concat(serialized.entities_json, "\n") .. "\n"
            local path = snapshot.trees_rocks_init_path(chunk_x, chunk_y)
            table_insert(state.write_queue, {
                path = path,
                content = content,
                file_type = "trees_rocks",
                event_type = "file_created",
            })
        end
        
        -- NEW: Queue single entities_init.jsonl for ALL player entities
        -- Instead of individual files per entity, we write one JSONL file
        if #serialized.player_entity_data > 0 then
            local entity_json_lines = {}
            for _, item in ipairs(serialized.player_entity_data) do
                local entity_data = item.data
                if entity_data then
                    local ok, json_str = pcall(helpers.table_to_json, entity_data)
                    if ok and json_str then
                        table_insert(entity_json_lines, json_str)
                    end
                end
            end
            
            if #entity_json_lines > 0 then
                local content = table_concat(entity_json_lines, "\n") .. "\n"
                local path = snapshot.entities_init_path(chunk_x, chunk_y)
                table_insert(state.write_queue, {
                    path = path,
                    content = content,
                    file_type = "entities_init",
                    event_type = "file_created",
                    entity_count = #entity_json_lines,
                })
            end
        end
        
        -- Queue ghosts for top-level ghosts-init.jsonl (append mode)
        -- Ghosts are tracked per chunk but written to top-level file
        if #serialized.ghosts_json > 0 then
            local content = table_concat(serialized.ghosts_json, "\n") .. "\n"
            local path = snapshot.ghosts_init_path()
            table_insert(state.write_queue, {
                path = path,
                content = content,
                file_type = "ghosts_init",
                event_type = "file_created",
                append = true,  -- Append to top-level file
                ghost_count = #serialized.ghosts_json,
                chunk = { x = chunk_x, y = chunk_y },
            })
        end
        
        -- Transition to WRITE phase
        state.phase = SnapshotPhase.WRITE
        
        if snapshot.DEBUG and game and game.print then
            game.print(string.format("[snapshot] SERIALIZE complete for chunk (%d, %d): %d files queued (was %d entities)",
                chunk_x, chunk_y, #state.write_queue, #serialized.player_entity_data))
        end
    end
end

--- PHASE: WRITE - Write files to disk (batched, most expensive!)
--- @param state SnapshotState
local function phase_write(state)
    local budget = SnapshotConfig.WRITES_PER_TICK
    local processed = 0
    local chunk_x = state.chunk_x
    local chunk_y = state.chunk_y
    
    while state.write_index <= #state.write_queue and processed < budget do
        local item = state.write_queue[state.write_index]
        
        -- Write file (use append mode for ghosts-init.jsonl)
        local append_mode = item.append == true
        local ok = pcall(helpers.write_file, item.path, item.content, append_mode)
        
        -- Send UDP notification on success (simplified for new approach)
        if ok then
            -- For entities_init, send chunk_init_complete notification
            if item.file_type == "entities_init" then
                snapshot.send_chunk_init_complete_udp(chunk_x, chunk_y, item.entity_count or 0)
            elseif item.file_type == "ghosts_init" then
                -- For ghosts, send file event with chunk info
                snapshot.send_file_event_udp(
                    item.event_type,
                    item.file_type,
                    chunk_x,
                    chunk_y,
                    nil, -- no position for bulk files
                    nil, -- no entity_name
                    nil, -- no component_type
                    item.path
                )
                if snapshot.DEBUG and game and game.print then
                    game.print(string.format("[snapshot] Appended %d ghosts to top-level file from chunk (%d, %d)",
                        item.ghost_count or 0, chunk_x, chunk_y))
                end
            else
                -- For other file types, use the standard file event
                snapshot.send_file_event_udp(
                    item.event_type,
                    item.file_type,
                    chunk_x,
                    chunk_y,
                    nil, -- no position for bulk files
                    nil, -- no entity_name
                    nil, -- no component_type
                    item.path
                )
            end
        elseif snapshot.DEBUG and game and game.print then
            game.print(string.format("[snapshot] WARNING: Failed to write file: %s", item.path))
        end
        
        state.write_index = state.write_index + 1
        processed = processed + 1
    end
    
    -- Check if all writes are complete
    if state.write_index > #state.write_queue then
        state.phase = SnapshotPhase.COMPLETE
        
        if snapshot.DEBUG and game and game.print then
            game.print(string.format("[snapshot] WRITE complete for chunk (%d, %d)", chunk_x, chunk_y))
        end
    end
end

--- PHASE: COMPLETE - Mark chunk as snapshotted and update tracker
--- @param state SnapshotState
local function phase_complete(state)
    local tracker = M.get_chunk_tracker()
    local chunk_x = state.chunk_x
    local chunk_y = state.chunk_y
    local gathered = state.gathered
    
    -- Update ChunkTracker with gathered data
    if gathered then
        -- Track resources
        local tracked_resources = {}
        for _, resource_data in ipairs(gathered.resources or {}) do
            local tracker_name = map_resource_name(resource_data.kind)
            if tracker_name and not tracked_resources[tracker_name] then
                tracker:mark_chunk_has("resource", tracker_name, chunk_x, chunk_y)
                tracked_resources[tracker_name] = true
            end
        end
        
        -- Track water
        if gathered.water and #gathered.water > 0 then
            tracker:mark_chunk_has("water", nil, chunk_x, chunk_y)
        end
        
        -- Track trees
        if gathered.trees and #gathered.trees > 0 then
            tracker:mark_chunk_has("entities", "trees", chunk_x, chunk_y)
        end
        
        -- Track rocks
        if gathered.rocks and #gathered.rocks > 0 then
            tracker:mark_chunk_has("entities", "rocks", chunk_x, chunk_y)
        end
        
        -- Track ghosts (for querying, but written to top-level file)
        if gathered.ghosts and #gathered.ghosts > 0 then
            tracker:mark_chunk_has("entities", "ghosts", chunk_x, chunk_y)
        end
    end
    
    -- Mark chunk as snapshotted
    tracker:mark_chunk_snapshotted(chunk_x, chunk_y)
    
    if snapshot.DEBUG and game and game.print then
        game.print(string.format("[snapshot] COMPLETE: Chunk (%d, %d) fully snapshotted", chunk_x, chunk_y))
    end
    
    -- Reset state for next chunk
    reset_snapshot_state()
end

--- Process one chunk snapshot per tick using state machine
--- Spreads the work across multiple ticks to maintain game performance
--- @param event table on_tick event
function M._on_tick_snapshot_chunks(event)
    local state = get_snapshot_state()
    
    -- IDLE: Find next chunk to process
    if state.phase == SnapshotPhase.IDLE then
        local chunk_x, chunk_y = find_next_pending_chunk()
        if chunk_x and chunk_y then
    local tracker = M.get_chunk_tracker()
            -- Double-check chunk still needs snapshotting
            if tracker:chunk_needs_snapshot(chunk_x, chunk_y) then
                state.chunk_x = chunk_x
                state.chunk_y = chunk_y
                state.phase = SnapshotPhase.FIND_ENTITIES
                
            if snapshot.DEBUG and game and game.print then
                    game.print(string.format("[snapshot] Starting chunk (%d, %d)", chunk_x, chunk_y))
                end
            end
        end
        return
    end
    
    -- FIND_ENTITIES: Gather all data (one tick)
    if state.phase == SnapshotPhase.FIND_ENTITIES then
        phase_find_entities(state, state.chunk_x, state.chunk_y)
            return
        end
        
    -- SERIALIZE: Convert to JSON (batched across ticks)
    if state.phase == SnapshotPhase.SERIALIZE then
        phase_serialize(state)
        return
    end
    
    -- WRITE: Write files to disk (batched across ticks)
    if state.phase == SnapshotPhase.WRITE then
        phase_write(state)
        return
    end
    
    -- COMPLETE: Finalize and reset
    if state.phase == SnapshotPhase.COMPLETE then
        phase_complete(state)
        return
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