--- factorio_verse/core/game_state/MapGameState.lua
--- MapGameState sub-module for managing map-related functionality.
--- Static module - no instantiation required.

-- Module-level local references for global lookups (performance optimization)
local pairs = pairs
local ipairs = ipairs
local math_floor = math.floor
local table_insert = table.insert
local table_concat = table.concat
local string_format = string.format
-- Cache helpers functions for performance (called frequently in serialization)
local table_to_json = helpers.table_to_json
local write_file = helpers.write_file

local utils = require("utils.utils")
local Resource = require("game_state.Resource")
-- local Entities = require("game_state.Entities")
local snapshot = require("utils.snapshot")
local forces = require("utils.forces")
local serialize = require("__fv_embodied_agent__/utils/serialize")
local udp_payloads = require("utils.udp_payloads")

-- Agent is from fv_embodied_agent mod (dependency)
local Agent = require("__fv_embodied_agent__.Agent")

-- Forward declaration for functions used by ChunkTracker (defined later)
local enqueue_chunk_for_snapshot

-- ============================================================================
-- DEBUG FLAG
-- ============================================================================
local DEBUG = false  -- Enable detailed logging for performance analysis

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

-- ============================================================================
-- SYSTEM PHASE - Separates initial snapshotting from maintenance
-- ============================================================================
--
-- INITIAL_SNAPSHOTTING: Process all initially charted chunks ASAP
--   - Disable entity status tracking (no 120-tick scans)
--   - Disable event-driven entity updates
--   - Run snapshot state machine at maximum throughput
--   - Exit when pending_chunks queue is empty
--
-- MAINTENANCE: Keep snapshots up-to-date as game evolves
--   - Enable entity status tracking (120-tick scans)
--   - Enable event-driven entity updates
--   - Process new charted chunks as they appear
--   - Handle dirty chunks (mutations)

local SystemPhase = {
    INITIAL_SNAPSHOTTING = "INITIAL_SNAPSHOTTING",
    MAINTENANCE = "MAINTENANCE"
}

-- ============================================================================
-- ORCHESTRATION MODE - Controls when/how snapshotting is triggered
-- ============================================================================
--
-- AUTO: Snapshot immediately on chunk charted (default, backward compatible)
--   - on_chunk_charted triggers immediate queue for snapshotting
--   - Standard flow: INITIAL_SNAPSHOTTING -> MAINTENANCE
--
-- DEFERRED: Track charted chunks but wait for explicit trigger
--   - on_chunk_charted records chunks but doesn't queue for snapshotting
--   - Call trigger_initial_snapshot() to start processing
--   - Useful when scenario needs setup before snapshotting
--
-- SELECTIVE: Only snapshot areas explicitly requested
--   - on_chunk_charted is ignored for snapshotting purposes
--   - Call snapshot_area() to snapshot specific regions
--   - Essential for lab-grid cell isolation
--
local OrchestrationMode = {
    AUTO = "AUTO",
    DEFERRED = "DEFERRED",
    SELECTIVE = "SELECTIVE"
}

--- Get the configured orchestration mode
--- Reads from mod settings if available, falls back to storage override, then default
--- @return string OrchestrationMode enum value
local function get_orchestration_mode()
    -- Check if runtime override is set (via remote interface)
    if storage.orchestration_mode then
        return storage.orchestration_mode
    end

    -- Try to read from mod settings
    if settings and settings.global then
        local setting_value = settings.global["fv-snapshot-orchestration-mode"]
        if setting_value and setting_value.value then
            return setting_value.value
        end
    end

    -- Fallback to AUTO (backward compatible)
    return OrchestrationMode.AUTO
end

--- Set the orchestration mode at runtime (via remote interface)
--- @param mode string OrchestrationMode enum value
--- @return boolean success
local function set_orchestration_mode(mode)
    if mode ~= OrchestrationMode.AUTO and
       mode ~= OrchestrationMode.DEFERRED and
       mode ~= OrchestrationMode.SELECTIVE then
        log(string.format("[Map] Invalid orchestration mode: %s", tostring(mode)))
        return false
    end
    storage.orchestration_mode = mode
    log(string.format("[Map] Orchestration mode set to: %s", mode))
    return true
end

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

--- System state for snapshot management
--- @class SystemState
--- @field phase string Current system phase (SystemPhase enum)
--- @field pending_chunks table Array of {x, y, priority} chunks needing snapshot
--- @field stats table System statistics {chunks_snapshotted, chunks_pending, phase_start_tick, initial_snapshot_duration_ticks}
--- @field bootstrap_wait_ticks number Ticks to wait after on_init before checking for MAINTENANCE transition (allows charting to complete)
--- @field current_wait_tick number Current tick counter during bootstrap waiting

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

--- Initialize ChunkTracker storage (only call in on_init or on_configuration_changed!)
--- IMPORTANT: This modifies storage, so it CANNOT be called in on_load()
function ChunkTracker:init_storage()
    -- Only create if it doesn't exist
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

--- Get the singleton ChunkTracker instance (assumes already initialized)
--- For on_load, storage is already populated from save
--- @return ChunkTracker|nil
function ChunkTracker:get()
    return storage.chunk_tracker
end

--- Create or get the singleton ChunkTracker instance
--- DEPRECATED: Use init_storage() in on_init and get() in on_load
--- @return ChunkTracker
function ChunkTracker:new()
    -- If tracker already exists, return it
    if storage.chunk_tracker then
        return storage.chunk_tracker
    end

    -- Fallback: create if doesn't exist (only safe in on_init/on_configuration_changed)
    return self:init_storage()
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
            dirty = false,  -- TODO: True if chunk needs re-snapshotting due to mutation (not yet implemented)
            has_tracked_entities = false,  -- Cache: true if chunk has entities from tracked forces
            tracked_entity_count = 0,  -- Cache: count of entities from tracked forces in chunk
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
--- IMPORTANT: This enqueues the chunk for processing by the state machine
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
    -- Chunk entry has snapshot_tick = nil (needs snapshotting)
    -- Enqueue it for processing (uses forward-declared function)
    enqueue_chunk_for_snapshot(chunk_x, chunk_y, 1)
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
    -- Use ChunkTracker data instead of iterating all generated chunks
    -- This fixes the O(all generated chunks) performance issue that caused freezes at tick 32000
    -- ChunkTracker only contains charted chunks, populated by event handlers
    local charted_chunks = {}
    local tracker = M.get_chunk_tracker()
    
    -- Iterate chunk_lookup (only charted chunks) instead of surface.get_chunks() (all generated chunks)
    for chunk_key, chunk_entry in pairs(tracker.chunk_lookup) do
        -- Only return chunks with tracked force entities for status tracking
        if chunk_entry.has_tracked_entities then
            -- Parse chunk coordinates from key
            local x, y = chunk_key:match("([^,]+),([^,]+)")
            local chunk_x = tonumber(x)
            local chunk_y = tonumber(y)
            
            table.insert(charted_chunks, {
                x = chunk_x,
                y = chunk_y,
                area = {
                    left_top = { x = chunk_x * 32, y = chunk_y * 32 },
                    right_bottom = { x = (chunk_x + 1) * 32, y = (chunk_y + 1) * 32 }
                }
            })
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

    -- Use vanilla water tile names (works for all standard Factorio tiles)
    local water_tile_names = { "water", "deepwater", "water-green", "deepwater-green" }

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

    -- Try with diagonal parameter first
    local connected = surface.get_connected_tiles(position, water_tile_names, true)
    if not connected then
        -- Fallback: try without diagonal parameter
        connected = surface.get_connected_tiles(position, water_tile_names)
    end

    return connected or {}
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

function M.get_chunk_lookup()
    return M.get_chunk_tracker().chunk_lookup
end

-- ============================================================================
-- SYSTEM STATE MANAGEMENT
-- ============================================================================

--- Initialize system state storage (only call in on_init or on_configuration_changed!)
--- IMPORTANT: This modifies storage, so it CANNOT be called in on_load()
--- @param force boolean|nil If true, reinitialize even if exists (for migration)
local function init_system_state_storage(force)
    if force or not storage.system_state then
        storage.system_state = {
            phase = SystemPhase.INITIAL_SNAPSHOTTING,
            pending_chunks = {},  -- Queue of {x, y, priority}
            deferred_chunks = {},  -- Chunks tracked but not yet queued (DEFERRED mode)
            stats = {
                chunks_snapshotted = 0,
                chunks_pending = 0,
                phase_start_tick = game and game.tick or 0,
                initial_snapshot_duration_ticks = nil,
            },
            -- Bootstrap waiting: Allow time for scenario/freeplay charting to complete
            -- Scenarios like freeplay call force.chart() which is ASYNCHRONOUS
            -- The on_chunk_charted events fire AFTER chart() returns
            -- We wait 300 ticks (~5 seconds) to let initial charting complete before checking queue
            bootstrap_wait_ticks = 300,  -- Configurable wait time
            current_wait_tick = 0,
        }
    end
    -- Migration: Ensure deferred_chunks exists for existing saves
    -- This is safe here because this function is only called from on_init/on_configuration_changed
    if storage.system_state and not storage.system_state.deferred_chunks then
        storage.system_state.deferred_chunks = {}
    end
end

--- Get the system state (assumes already initialized)
--- @return SystemState
local function get_system_state()
    -- In on_load, storage is already populated from save
    -- In on_init, init_system_state_storage() must be called first
    return storage.system_state
end

--- Get current system phase
--- @return string SystemPhase enum value
local function get_system_phase()
    local state = get_system_state()
    return state.phase
end

--- Transition to MAINTENANCE phase
local function transition_to_maintenance()
    local state = get_system_state()
    if state.phase == SystemPhase.MAINTENANCE then
        return  -- Already in maintenance
    end
    
    state.phase = SystemPhase.MAINTENANCE
    state.stats.initial_snapshot_duration_ticks = game.tick - state.stats.phase_start_tick
    
    -- Log transition with performance summary
    if DEBUG and game and game.print then
        local duration_seconds = state.stats.initial_snapshot_duration_ticks / 60
        game.print("═══════════════════════════════════════════════════════════")
        game.print(string.format("[Snapshot System] ✅ Initial snapshotting COMPLETE after %.1f seconds (%d ticks).", 
            duration_seconds, state.stats.initial_snapshot_duration_ticks))
        game.print(string.format("[Snapshot System] Total chunks snapshotted: %d", state.stats.chunks_snapshotted))
        game.print(string.format("[Snapshot System] Average: %.2f seconds/chunk", 
            duration_seconds / math.max(1, state.stats.chunks_snapshotted)))
        game.print(string.format("[Snapshot System] Transitioning to MAINTENANCE mode."))
        game.print("═══════════════════════════════════════════════════════════")
    end
    
    -- Send UDP notification
    local payload = udp_payloads.system_phase_changed(SystemPhase.MAINTENANCE, state.stats)
    udp_payloads.send_event(payload)
end

--- Enqueue a chunk for snapshotting
--- @param chunk_x number
--- @param chunk_y number
--- @param priority number|nil Priority (default 1, higher = processed first)
enqueue_chunk_for_snapshot = function(chunk_x, chunk_y, priority)
    local state = get_system_state()
    priority = priority or 1
    
    -- Check if already in queue
    for _, chunk in ipairs(state.pending_chunks) do
        if chunk.x == chunk_x and chunk.y == chunk_y then
            return  -- Already queued
        end
    end
    
    table.insert(state.pending_chunks, {
        x = chunk_x,
        y = chunk_y,
        priority = priority
    })
    state.stats.chunks_pending = #state.pending_chunks
    
    -- If we receive chunks during bootstrap waiting, reset the wait counter
    -- This handles the case where charting happens over multiple ticks
    if state.phase == SystemPhase.INITIAL_SNAPSHOTTING and state.current_wait_tick > 0 then
        if DEBUG then
            game.print(string.format("[Snapshot System] Chunk (%d,%d) enqueued during bootstrap wait (tick %d). Resetting wait counter.",
                chunk_x, chunk_y, state.current_wait_tick))
        end
        state.current_wait_tick = 0  -- Reset wait, more chunks are coming
    end
end

-- Also expose as module function
M.enqueue_chunk_for_snapshot = enqueue_chunk_for_snapshot

--- Dequeue next pending chunk (highest priority first)
--- @return number|nil chunk_x
--- @return number|nil chunk_y
local function dequeue_next_pending_chunk()
    local state = get_system_state()
    local queue = state.pending_chunks
    
    if #queue == 0 then
        return nil, nil
    end
    
    -- For now, FIFO (could add priority sorting later if needed)
    local chunk = table.remove(queue, 1)
    state.stats.chunks_pending = #queue
    
    return chunk.x, chunk.y
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

--- DEPRECATED: Old implementation that scanned chunk_lookup with pairs()
--- This was expensive for large chunk counts (O(n) every tick)
--- Replaced with queue-based approach (enqueue/dequeue)
--- Kept for reference only - DO NOT USE
local function find_next_pending_chunk_DEPRECATED()
    local tracker = M.get_chunk_tracker()
    for chunk_key, chunk_entry in pairs(tracker.chunk_lookup) do
        if chunk_key and chunk_entry.snapshot_tick == nil then
            local xstr, ystr = string.match(chunk_key, "([^,]+),([^,]+)")
            return tonumber(xstr), tonumber(ystr)
        end
    end
    return nil, nil
end

--- Send snapshot state payload
--- @param state_name string State name (IDLE, FIND_ENTITIES, SERIALIZE, WRITE, COMPLETE)
--- @param chunk table|nil Chunk coordinates {x, y}
--- @param progress table|nil Progress metrics
local function send_snapshot_state_payload(state_name, chunk, progress)
    local payload = udp_payloads.snapshot_state(state_name, chunk, game.tick, progress)
    udp_payloads.send_snapshot_state(payload)
end

--- Get current snapshot state machine status
--- @return table Status info including phase, current chunk, queue sizes
function M.get_snapshot_status()
    local state = get_snapshot_state()
    local sys_state = get_system_state()
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
        system_phase = sys_state.phase,
        current_chunk = state.chunk_x and { x = state.chunk_x, y = state.chunk_y } or nil,
        pending_chunks = pending_count,
        completed_chunks = completed_count,
        serialize_index = state.serialize_index,
        write_queue_size = state.write_queue and #state.write_queue or 0,
        write_index = state.write_index,
        bootstrap_wait = {
            current_tick = sys_state.current_wait_tick,
            total_ticks = sys_state.bootstrap_wait_ticks,
            waiting = sys_state.phase == SystemPhase.INITIAL_SNAPSHOTTING and #sys_state.pending_chunks == 0,
        },
        config = {
            entities_per_tick = SnapshotConfig.ENTITIES_PER_TICK,
            tiles_per_tick = SnapshotConfig.TILES_PER_TICK,
            writes_per_tick = SnapshotConfig.WRITES_PER_TICK,
            serializations_per_tick = SnapshotConfig.SERIALIZATIONS_PER_TICK,
            bootstrap_wait_ticks = sys_state.bootstrap_wait_ticks,
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
    if config.bootstrap_wait_ticks then
        local sys_state = get_system_state()
        sys_state.bootstrap_wait_ticks = config.bootstrap_wait_ticks
    end
end

--- Get current system phase (for external modules)
--- @return string SystemPhase enum value
function M.get_system_phase()
    return get_system_phase()
end

-- ============================================================================
-- ORCHESTRATION MODE API
-- ============================================================================

--- Get the current orchestration mode
--- @return string OrchestrationMode enum value ("AUTO", "DEFERRED", or "SELECTIVE")
function M.get_orchestration_mode()
    return get_orchestration_mode()
end

--- Set the orchestration mode at runtime
--- @param mode string OrchestrationMode enum value ("AUTO", "DEFERRED", or "SELECTIVE")
--- @return table {success: boolean, mode?: string, error?: string}
function M.set_orchestration_mode(mode)
    if set_orchestration_mode(mode) then
        return { success = true, mode = mode }
    else
        return { success = false, error = "Invalid mode: " .. tostring(mode) .. ". Must be AUTO, DEFERRED, or SELECTIVE." }
    end
end

--- Trigger initial snapshotting for DEFERRED mode
--- Moves all deferred chunks to the pending queue
--- @return table {success: boolean, chunks_queued: number}
function M.trigger_initial_snapshot()
    local sys_state = get_system_state()
    local tracker = M.get_chunk_tracker()
    local chunks_queued = 0

    -- Move all deferred chunks to pending queue
    for chunk_key, chunk in pairs(sys_state.deferred_chunks) do
        tracker:mark_chunk_needs_snapshot(chunk.x, chunk.y)
        chunks_queued = chunks_queued + 1
    end

    -- Clear deferred list
    sys_state.deferred_chunks = {}

    -- If we queued chunks and we're not already snapshotting, start
    if chunks_queued > 0 and sys_state.phase == SystemPhase.MAINTENANCE then
        sys_state.phase = SystemPhase.INITIAL_SNAPSHOTTING
        sys_state.stats.phase_start_tick = game.tick
    end

    if DEBUG and game and game.print then
        game.print(string.format("[Map] trigger_initial_snapshot: queued %d chunks", chunks_queued))
    end

    return { success = true, chunks_queued = chunks_queued }
end

--- Convert world bounds to chunk coordinates
--- @param bounds table {left_top: {x, y}, right_bottom: {x, y}}
--- @return table List of {x, y} chunk coordinates
local function bounds_to_chunks(bounds)
    local chunks = {}
    local min_chunk_x = math.floor(bounds.left_top.x / 32)
    local min_chunk_y = math.floor(bounds.left_top.y / 32)
    local max_chunk_x = math.floor((bounds.right_bottom.x - 1) / 32)
    local max_chunk_y = math.floor((bounds.right_bottom.y - 1) / 32)

    for cy = min_chunk_y, max_chunk_y do
        for cx = min_chunk_x, max_chunk_x do
            table.insert(chunks, { x = cx, y = cy })
        end
    end

    return chunks
end

--- Snapshot a specific area (for SELECTIVE mode or targeted re-snapshotting)
--- Enqueues all chunks overlapping the bounding box for snapshotting
--- @param bounds table {left_top: {x, y}, right_bottom: {x, y}} in world coordinates
--- @param priority number|nil Priority for queue (higher = processed first, default 10)
--- @return table {success: boolean, chunks_queued: number, chunks: table}
function M.snapshot_area(bounds, priority)
    if not bounds or not bounds.left_top or not bounds.right_bottom then
        return { success = false, error = "Invalid bounds: must have left_top and right_bottom" }
    end

    priority = priority or 10  -- Higher priority for explicit requests
    local chunks = bounds_to_chunks(bounds)
    local tracker = M.get_chunk_tracker()
    local sys_state = get_system_state()

    -- snapshot_area is snapshot-at-least-once: chunks with an existing
    -- snapshot are skipped — but that skip must be VISIBLE to the caller,
    -- not silent (a caller seeing chunks_queued > 0 while zero files get
    -- written was the frozen-tick failure of the 2026-06-10 field run).
    -- Use re_snapshot_area to force fresh files.
    local queued = 0
    local skipped = 0
    for _, chunk in ipairs(chunks) do
        local entry = tracker:_get_chunk_entry(chunk.x, chunk.y)
        if entry.snapshot_tick == nil then
            enqueue_chunk_for_snapshot(chunk.x, chunk.y, priority)
            queued = queued + 1
        else
            skipped = skipped + 1
        end
    end

    -- If we're in maintenance and chunks were queued, switch to initial snapshotting
    -- This ensures the snapshot state machine processes them
    if queued > 0 and sys_state.phase == SystemPhase.MAINTENANCE then
        sys_state.phase = SystemPhase.INITIAL_SNAPSHOTTING
        sys_state.stats.phase_start_tick = game.tick
    end

    if DEBUG and game and game.print then
        game.print(string.format("[Map] snapshot_area: queued %d, skipped %d (already snapshotted) from bounds (%d,%d) to (%d,%d)",
            queued, skipped, bounds.left_top.x, bounds.left_top.y, bounds.right_bottom.x, bounds.right_bottom.y))
    end

    return {
        success = true,
        chunks_queued = queued,
        chunks_skipped = skipped,
        chunks = chunks,
        warning = skipped > 0
            and (skipped .. " chunk(s) already snapshotted were NOT re-queued; no new files will be written for them. Use re_snapshot_area to force fresh files.")
            or nil,
    }
end

--- Re-snapshot an area (clears existing snapshot state and re-processes)
--- Useful after cell reset in lab-grid scenario
--- @param bounds table {left_top: {x, y}, right_bottom: {x, y}} in world coordinates
--- @param priority number|nil Priority for queue (higher = processed first, default 10)
--- @return table {success: boolean, chunks_queued: number, chunks: table}
function M.re_snapshot_area(bounds, priority)
    if not bounds or not bounds.left_top or not bounds.right_bottom then
        return { success = false, error = "Invalid bounds: must have left_top and right_bottom" }
    end

    priority = priority or 10
    local chunks = bounds_to_chunks(bounds)
    local tracker = M.get_chunk_tracker()
    local sys_state = get_system_state()

    for _, chunk in ipairs(chunks) do
        -- Clear the snapshot tick to force re-processing, then enqueue once
        -- (mark_chunk_needs_snapshot would enqueue a duplicate at priority 1)
        local entry = tracker:_get_chunk_entry(chunk.x, chunk.y)
        entry.snapshot_tick = nil
        enqueue_chunk_for_snapshot(chunk.x, chunk.y, priority)
    end

    -- Switch to initial snapshotting if needed
    if #chunks > 0 and sys_state.phase == SystemPhase.MAINTENANCE then
        sys_state.phase = SystemPhase.INITIAL_SNAPSHOTTING
        sys_state.stats.phase_start_tick = game.tick
    end

    if DEBUG and game and game.print then
        game.print(string.format("[Map] re_snapshot_area: cleared and queued %d chunks from bounds (%d,%d) to (%d,%d)",
            #chunks, bounds.left_top.x, bounds.left_top.y, bounds.right_bottom.x, bounds.right_bottom.y))
    end

    return { success = true, chunks_queued = #chunks, chunks = chunks }
end

M.admin_api = {
    get_charted_chunks = M.get_charted_chunks,
    get_map_area_state = M.get_map_area_state,
    set_map_area_state = M.set_map_area_state,
    clear_map_area = M.clear_map_area,
    get_chunk_lookup = M.get_chunk_lookup,
    get_snapshot_status = M.get_snapshot_status,
    set_snapshot_config = M.set_snapshot_config,
    get_system_phase = M.get_system_phase,
    enqueue_chunk_for_snapshot = M.enqueue_chunk_for_snapshot,  -- For test-driven forced re-snapshotting
    -- Orchestration mode API
    get_orchestration_mode = M.get_orchestration_mode,
    set_orchestration_mode = M.set_orchestration_mode,
    trigger_initial_snapshot = M.trigger_initial_snapshot,
    snapshot_area = M.snapshot_area,
    re_snapshot_area = M.re_snapshot_area,
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
    if Agent and Agent.on_chunk_charted then
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
    local start_tick = game.tick
    if DEBUG then
        game.print(string_format("[PERF] FIND_ENTITIES START: chunk (%d,%d) at tick %d", chunk_x, chunk_y, start_tick))
    end
    
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
    if DEBUG then
        game.print("[PERF]   Calling Resource.gather_resources_for_chunk...")
    end
    local gathered = Resource.gather_resources_for_chunk(chunk)
    if DEBUG then
        game.print(string_format("[PERF]   Resources gathered: resources=%d, trees=%d, rocks=%d, water=%d",
            #gathered.resources, #gathered.trees, #gathered.rocks, #gathered.water))
    end
    
    -- Also gather built entities from tracked forces (excluding ghosts)
    -- PERFORMANCE: count first, then find only if count > 0
    -- Use dynamic forces to include player + all agent forces
    local tracked_forces = forces.get_tracked_forces()
    local tracked_entities = {}
    if DEBUG then
        game.print("[PERF]   Counting tracked force entities...")
    end
    local entity_count = surface.count_entities_filtered {
        area = chunk_area,
        force = tracked_forces,
    }
    if DEBUG then
        game.print(string_format("[PERF]   Tracked force entity count: %d", entity_count))
    end
    if entity_count > 0 then
        local all_entities = surface.find_entities_filtered {
            area = chunk_area,
            force = tracked_forces,
        }
        -- Filter out ghosts and character entities (in Lua, not C++)
        -- Use numeric for loop for hot path performance
        local all_entities_count = #all_entities
        for i = 1, all_entities_count do
            local entity = all_entities[i]
            if entity and entity.valid and entity.type ~= "entity-ghost" and entity.type ~= "character" then
                tracked_entities[#tracked_entities + 1] = entity
            end
        end
        if DEBUG then
            game.print(string_format("[PERF]   Tracked entities after filtering: %d", #tracked_entities))
        end
    end
    
    -- Gather ghosts separately (for chunk-wise ghosts-init.jsonl)
    -- PERFORMANCE: count first, then find only if count > 0
    local ghosts = {}
    if DEBUG then
        game.print("[PERF]   Counting ghosts...")
    end
    local ghost_count = surface.count_entities_filtered {
        area = chunk_area,
        type = "entity-ghost",
    }
    if DEBUG then
        game.print(string_format("[PERF]   Ghost count: %d", ghost_count))
    end
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
        tracked_entities = tracked_entities,
        ghosts = ghosts,
        chunk = chunk,
    }
    
    local end_tick = game.tick
    local total = #gathered.resources + #gathered.water + #gathered.trees + #gathered.rocks + #tracked_entities + #ghosts
    if DEBUG then
        local duration = end_tick - start_tick
        game.print(string_format("[PERF] FIND_ENTITIES COMPLETE: chunk (%d,%d) - took %d ticks, found %d items (res=%d, water=%d, trees=%d, rocks=%d, entities=%d, ghosts=%d)", 
            chunk_x, chunk_y, duration, total, #gathered.resources, #gathered.water, #gathered.trees, #gathered.rocks, #tracked_entities, #ghosts))
        if duration > 0 then
            game.print(string_format("[PERF] ⚠️  WARNING: FIND_ENTITIES took %d ticks - this should complete in 1 tick!", duration))
        end
    end
    
    -- Initialize serialization state
    state.serialized = {
        resources_json = {},      -- Array of JSON strings for tiles.jsonl
        water_json = {},          -- Array of JSON strings for water-tiles.jsonl
        entities_json = {},       -- Array of JSON strings for entities.jsonl (trees+rocks)
        entity_data = {},  -- Array of {entity, data} for individual entity files
        ghosts_json = {},         -- Array of JSON strings for chunk-wise ghosts-init.jsonl
    }
    state.serialize_index = 1
    
    -- Transition to SERIALIZE phase
    state.phase = SnapshotPhase.SERIALIZE
    
    -- No UDP notification needed - only COMPLETE state matters for external systems
    
    if DEBUG and game and game.print then
        game.print(string_format("[snapshot] FIND_ENTITIES complete for chunk (%d, %d): %d items to serialize (%d ghosts)",
            chunk_x, chunk_y, total, #ghosts))
    end
end

--- PHASE: SERIALIZE - Convert gathered data to JSON strings (batched)
--- @param state SnapshotState
local function phase_serialize(state)
    local start_tick = game.tick
    local gathered = state.gathered
    local serialized = state.serialized
    local budget = SnapshotConfig.SERIALIZATIONS_PER_TICK
    local processed = 0
    local idx = state.serialize_index
    local serialization_failures = 0
    -- Cache state variables for performance (used multiple times)
    local chunk_x = state.chunk_x
    local chunk_y = state.chunk_y
    
    -- Cache gathered arrays locally to avoid repeated table lookups in hot loops
    local gathered_resources = gathered.resources
    local gathered_water = gathered.water
    local gathered_trees = gathered.trees
    local gathered_rocks = gathered.rocks
    local gathered_tracked_entities = gathered.tracked_entities
    local gathered_ghosts = gathered.ghosts
    
    -- Cache serialized arrays locally for hot loops
    local serialized_resources_json = serialized.resources_json
    local serialized_water_json = serialized.water_json
    local serialized_entities_json = serialized.entities_json
    local serialized_entity_data = serialized.entity_data
    local serialized_ghosts_json = serialized.ghosts_json
    
    -- Calculate total items to serialize (cache lengths for repeated use)
    local total_resources = #gathered_resources
    local total_water = #gathered_water
    local total_trees = #gathered_trees
    local total_rocks = #gathered_rocks
    local total_entities = #gathered_tracked_entities
    local total_ghosts = (gathered_ghosts and #gathered_ghosts) or 0
    local total_trees_rocks = total_trees + total_rocks
    
    if DEBUG and idx == 1 then
        local total = total_resources + total_water + total_trees + total_rocks + total_entities + total_ghosts
        game.print(string_format("[PERF] SERIALIZE START: tick %d, total=%d items, budget=%d/tick", 
            start_tick, total, budget))
    end
    
    -- Serialize resources (tiles.jsonl)
    -- Use numeric for loop with direct indexing for hot path
    local resource_end = total_resources
    while idx <= resource_end and processed < budget do
        local resource = gathered_resources[idx]
        local json_str = table_to_json(resource)
        if json_str then
            serialized_resources_json[#serialized_resources_json + 1] = json_str
        else
            serialization_failures = serialization_failures + 1
        end
        idx = idx + 1
        processed = processed + 1
    end
    
    -- Serialize water tiles (water-tiles.jsonl)
    local water_start = total_resources + 1
    local water_end = total_resources + total_water
    local water_offset = total_resources  -- Pre-calculate offset for performance
    while idx >= water_start and idx <= water_end and processed < budget do
        local water_idx = idx - water_offset
        local water = gathered_water[water_idx]
        local json_str = table_to_json(water)
        if json_str then
            serialized_water_json[#serialized_water_json + 1] = json_str
        else
            serialization_failures = serialization_failures + 1
        end
        idx = idx + 1
        processed = processed + 1
    end
    
    -- Serialize trees and rocks (entities.jsonl)
    local entities_start = water_end + 1
    local entities_end = water_end + total_trees_rocks
    local entities_offset = total_resources + total_water  -- Pre-calculate offset for performance
    while idx >= entities_start and idx <= entities_end and processed < budget do
        local entity_idx = idx - entities_offset
        local entity_data
        if entity_idx <= total_trees then
            entity_data = gathered_trees[entity_idx]
        else
            entity_data = gathered_rocks[entity_idx - total_trees]
        end
        if entity_data then
            local json_str = table_to_json(entity_data)
            if json_str then
                serialized_entities_json[#serialized_entities_json + 1] = json_str
            else
                serialization_failures = serialization_failures + 1
            end
        end
        idx = idx + 1
        processed = processed + 1
    end
    
    -- Serialize built entities from tracked forces
    -- For initial chunk snapshot, entities are pre-existing (not built by agent or player during this session)
    local pre_existing_builder_info = {
        label = "pre-existing",
        placed_tick = nil,  -- Unknown when pre-existing entities were placed
    }
    local entities_start = entities_end + 1
    local entities_end_idx = entities_end + total_entities
    local entities_offset = entities_offset + total_trees_rocks  -- Pre-calculate offset for performance
    while idx >= entities_start and idx <= entities_end_idx and processed < budget do
        local entity_idx = idx - entities_offset
        local entity = gathered_tracked_entities[entity_idx]
        if entity and entity.valid then
            -- Use serialize module's serialization with pre-existing builder info
            local entity_data = serialize.serialize_entity(entity, pre_existing_builder_info)
            if entity_data then
                serialized_entity_data[#serialized_entity_data + 1] = {
                    entity = entity,
                    data = entity_data,
                }
            end
        end
        idx = idx + 1
        processed = processed + 1
    end
    
    -- Serialize ghosts (for chunk-wise ghosts-init.jsonl)
    -- For initial chunk snapshot, ghosts are pre-existing (not placed by agent or player during this session)
    local ghosts_start = entities_end_idx + 1
    local ghosts_end = entities_end_idx + total_ghosts
    local ghosts_offset = entities_offset + total_entities  -- Pre-calculate offset for performance
    while idx >= ghosts_start and idx <= ghosts_end and processed < budget do
        local ghost_idx = idx - ghosts_offset
        local ghost = gathered_ghosts and gathered_ghosts[ghost_idx]
        if ghost and ghost.valid then
            -- Use serialize module's ghost serialization with pre-existing label
            local ghost_data = serialize.serialize_ghost(ghost, pre_existing_builder_info)
            if ghost_data then
                -- Add chunk info to ghost data for tracking
                ghost_data.chunk = { x = chunk_x, y = chunk_y }
                local json_str = table_to_json(ghost_data)
                if json_str then
                    serialized_ghosts_json[#serialized_ghosts_json + 1] = json_str
                else
                    serialization_failures = serialization_failures + 1
                end
            end
        end
        idx = idx + 1
        processed = processed + 1
    end
    
    state.serialize_index = idx
    
    -- Log performance metrics for this tick
    if DEBUG and processed > 0 then
        local end_tick = game.tick
        local duration = end_tick - start_tick
        game.print(string_format("[PERF] SERIALIZE tick %d: processed %d items (%d failures), took %d ticks",
            end_tick, processed, serialization_failures, duration))
        if duration > 0 then
            game.print(string_format("[PERF] ⚠️  WARNING: SERIALIZE took %d ticks for %d items - should be 1 tick!", duration, processed))
        end
    end
    
    -- Check if serialization is complete
    local total_items = total_resources + total_water + total_trees_rocks + total_entities + total_ghosts
    if idx > total_items then
        -- Build write queue - NEW APPROACH: single JSONL files per category
        state.write_queue = {}
        state.write_index = 1
        local write_queue = state.write_queue  -- Cache for repeated insertions

        -- First line of every init file: tick metadata, so freshness is
        -- falsifiable from disk (init files previously carried no tick and
        -- staleness was invisible to the loader). Loader skips kind=chunk_meta.
        local chunk_meta_line = table_to_json({
            kind = "chunk_meta",
            tick = game.tick,
            chunk_x = chunk_x,
            chunk_y = chunk_y,
        })

        -- Queue resources-init.jsonl write (ore tiles)
        if #serialized_resources_json > 0 then
            local content = chunk_meta_line .. "\n" .. table_concat(serialized_resources_json, "\n") .. "\n"
            local path = snapshot.resources_init_path(chunk_x, chunk_y)
            write_queue[#write_queue + 1] = {
                path = path,
                content = content,
                file_type = "resource",
                event_type = "file_created",
            }
        end
        
        -- Queue water-init.jsonl write
        if #serialized_water_json > 0 then
            local content = chunk_meta_line .. "\n" .. table_concat(serialized_water_json, "\n") .. "\n"
            local path = snapshot.water_init_path(chunk_x, chunk_y)
            write_queue[#write_queue + 1] = {
                path = path,
                content = content,
                file_type = "water",
                event_type = "file_created",
            }
        end
        
        -- Queue trees_rocks-init.jsonl write (trees + rocks)
        if #serialized_entities_json > 0 then
            local content = chunk_meta_line .. "\n" .. table_concat(serialized_entities_json, "\n") .. "\n"
            local path = snapshot.trees_rocks_init_path(chunk_x, chunk_y)
            write_queue[#write_queue + 1] = {
                path = path,
                content = content,
                file_type = "trees_rocks",
                event_type = "file_created",
            }
        end
        
        -- Queue single entities-init.jsonl for all tracked force entities
        -- Instead of individual files per entity, we write one JSONL file
        local serialized_entity_count = #serialized_entity_data
        if serialized_entity_count > 0 then
            local entity_json_lines = {}
            -- Use numeric for loop for hot path
            for i = 1, serialized_entity_count do
                local item = serialized_entity_data[i]
                local entity_data = item.data
                if entity_data then
                    local json_str = table_to_json(entity_data)
                    if json_str then
                        entity_json_lines[#entity_json_lines + 1] = json_str
                    end
                end
            end
            
            local entity_json_count = #entity_json_lines
            if entity_json_count > 0 then
                local content = chunk_meta_line .. "\n" .. table_concat(entity_json_lines, "\n") .. "\n"
                local path = snapshot.entities_init_path(chunk_x, chunk_y)
                write_queue[#write_queue + 1] = {
                    path = path,
                    content = content,
                    file_type = "entities_init",
                    event_type = "file_created",
                    entity_count = entity_json_count,
                }
            end
        end
        
        -- Queue ghosts for chunk-wise ghosts-init.jsonl
        local ghosts_json_count = #serialized_ghosts_json
        if ghosts_json_count > 0 then
            local content = chunk_meta_line .. "\n" .. table_concat(serialized_ghosts_json, "\n") .. "\n"
            local path = snapshot.ghosts_init_path(chunk_x, chunk_y)
            write_queue[#write_queue + 1] = {
                path = path,
                content = content,
                file_type = "ghosts_init",
                event_type = "file_created",
                append = false,  -- Chunk-wise file, not append mode
                ghost_count = ghosts_json_count,
                chunk = { x = chunk_x, y = chunk_y },
            }
        end
        
        -- Transition to WRITE phase
        state.phase = SnapshotPhase.WRITE
        
        -- No UDP notification needed - only COMPLETE state matters for external systems
        
        if DEBUG then
            game.print(string_format("[DEBUG Map.phase_serialize] Tick %d: SERIALIZE complete for chunk (%d, %d): %d files queued (%d entities)",
                game.tick, chunk_x, chunk_y, #write_queue, serialized_entity_count))
        end
    elseif DEBUG and processed > 0 then
        game.print(string_format("[DEBUG Map.phase_serialize] Tick %d: Serialized %d items, index now %d", 
            game.tick, processed, idx))
    end
end

--- PHASE: WRITE - Write files to disk (batched, most expensive!)
--- @param state SnapshotState
local function phase_write(state)
    local start_tick = game.tick
    local budget = SnapshotConfig.WRITES_PER_TICK
    local processed = 0
    local chunk_x = state.chunk_x
    local chunk_y = state.chunk_y
    local write_failures = 0
    
    -- Cache write_queue locally for hot loop
    local write_queue = state.write_queue
    local write_queue_len = #write_queue
    local write_index = state.write_index
    
    if DEBUG and write_index == 1 then
        game.print(string_format("[PERF] WRITE START: tick %d, chunk (%d,%d), %d files queued, budget=%d writes/tick", 
            start_tick, chunk_x, chunk_y, write_queue_len, budget))
    end
    
    -- Pre-create chunk table once for UDP notifications (avoid repeated allocation)
    local chunk = { x = chunk_x, y = chunk_y }
    
    while write_index <= write_queue_len and processed < budget do
        local item = write_queue[write_index]
        
        -- Write file (use append mode for ghosts-init.jsonl)
        -- Disk I/O is BLOCKING and expensive - each write can take 0.1-1ms depending on disk speed
        local append_mode = item.append == true
        
        -- Write to disk (return value logged but not used for control flow)
        local ok = write_file(item.path, item.content, append_mode)
        
        if not ok then
            write_failures = write_failures + 1
            if DEBUG and game and game.print then
                game.print(string_format("[snapshot] WARNING: Failed to write file: %s", item.path))
            end
        end
        
        -- Send UDP notification using payload module
        -- CRITICAL: Always send UDP regardless of write success to maintain Factorio determinism
        -- Note: We only send notifications for entities_init (chunk_init_complete) and snapshot state transitions
        -- Individual init file writes (resources, water, trees_rocks) don't need notifications because:
        -- 1. Bootstrapping waits for COMPLETE state, then loads all init files at once
        -- 2. Updates use entity_operation events (append-only log), not init file writes
        local file_type = item.file_type
        
        -- For entities_init, send chunk_init_complete notification (useful for knowing when entity data is ready)
        if file_type == "entities_init" then
            local payload = udp_payloads.chunk_init_complete(chunk, item.entity_count or 0)
            udp_payloads.send_event(payload)
        elseif file_type == "ghosts_init" then
            -- Ghosts written to chunk-wise file
            if DEBUG and game and game.print then
                game.print(string_format("[snapshot] Wrote %d ghosts to chunk (%d, %d) ghosts-init.jsonl",
                    item.ghost_count or 0, chunk_x, chunk_y))
            end
        end
        -- Other init files (resources, water, trees_rocks) - no notification needed
        
        write_index = write_index + 1
        processed = processed + 1
    end
    
    -- Update state with new write_index
    state.write_index = write_index
    
    -- Log performance metrics for this tick
    if DEBUG and processed > 0 then
        local end_tick = game.tick
        local duration = end_tick - start_tick
        local remaining = write_queue_len - write_index + 1
        game.print(string_format("[PERF] WRITE tick %d: wrote %d files (%d failures), %d remaining, took %d ticks",
            end_tick, processed, write_failures, remaining, duration))
        if duration > 0 then
            game.print(string_format("[PERF] ⚠️  WARNING: WRITE took %d ticks for %d files - disk I/O is blocking!", duration, processed))
        end
    end
    
    -- Check if all writes are complete
    if write_index > write_queue_len then
        -- Clear memory IMMEDIATELY before transitioning to COMPLETE
        -- This prevents memory accumulation during large snapshotting operations
        state.gathered = nil
        state.serialized = nil
        state.write_queue = {}
        
        -- Hint to Lua garbage collector (helps but doesn't guarantee immediate collection)
        collectgarbage("step", 100)
        
        state.phase = SnapshotPhase.COMPLETE
        
        -- Send snapshot state payload
        local progress = {
            files_written = write_queue_len,
        }
        send_snapshot_state_payload(udp_payloads.SNAPSHOT_STATE.COMPLETE, chunk, progress)
        
        if DEBUG and game and game.print then
            game.print(string_format("[snapshot] WRITE complete for chunk (%d, %d)", chunk_x, chunk_y))
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
    
    if DEBUG then
        game.print(string_format("[DEBUG Map.phase_complete] Tick %d: Completing chunk (%d,%d)", 
            game.tick, chunk_x, chunk_y))
    end
    
    -- Update ChunkTracker with gathered data
    if gathered then
        -- Track resources
        local tracked_resources = {}
        local gathered_resources = gathered.resources
        if gathered_resources then
            local resources_count = #gathered_resources
            for i = 1, resources_count do
                local resource_data = gathered_resources[i]
            local tracker_name = map_resource_name(resource_data.kind)
            if tracker_name and not tracked_resources[tracker_name] then
                tracker:mark_chunk_has("resource", tracker_name, chunk_x, chunk_y)
                tracked_resources[tracker_name] = true
                end
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
    
    -- Update system statistics
    local sys_state = get_system_state()
    sys_state.stats.chunks_snapshotted = sys_state.stats.chunks_snapshotted + 1
    
    if DEBUG and game and game.print then
        game.print(string_format("[snapshot] COMPLETE: Chunk (%d, %d) fully snapshotted (total: %d, pending: %d)", 
            chunk_x, chunk_y, sys_state.stats.chunks_snapshotted, sys_state.stats.chunks_pending))
    end
    
    -- Reset state for next chunk (will transition to IDLE)
    reset_snapshot_state()
    -- No UDP notification needed - IDLE is internal state only
end

--- Process one chunk snapshot per tick using state machine
--- Spreads the work across multiple ticks to maintain game performance
--- @param event table on_tick event
function M._on_tick_snapshot_chunks(event)
    local tick_start = game.tick
    local state = get_snapshot_state()
    local sys_state = get_system_state()
    
    -- Early exit optimization: If we're in IDLE phase with no pending chunks and not in bootstrap wait
    if state.phase == SnapshotPhase.IDLE then
        -- During INITIAL_SNAPSHOTTING, we MUST CHECK bootstrap wait even if pending chunks > 0
        -- because we want to wait for charting to complete before *starting* processing
        if sys_state.phase == SystemPhase.INITIAL_SNAPSHOTTING then
             if sys_state.current_wait_tick < sys_state.bootstrap_wait_ticks then
                 -- Still waiting for bootstrap
                 sys_state.current_wait_tick = sys_state.current_wait_tick + 1
                 if DEBUG and sys_state.current_wait_tick % 60 == 0 then
                    game.print(string.format("[Snapshot System] Bootstrap waiting... %d/%d ticks",
                        sys_state.current_wait_tick, sys_state.bootstrap_wait_ticks))
                 end
                 -- If wait complete, transition happens in the ELSE block below (when queue checked) or we can force it here?
                 -- Actually, if pending_chunks > 0, we normally proceed.
                 -- The fix is: DO NOT PROCEED if waiting, regardless of queue.
                 return 
             end
        elseif #sys_state.pending_chunks == 0 then
            -- Normal IDLE exit if no chunks
            return
        end
    end
    
    -- IDLE: Find next chunk to process from queue
    if state.phase == SnapshotPhase.IDLE then
        local chunk_x, chunk_y = dequeue_next_pending_chunk()
        if chunk_x and chunk_y then
            local tracker = M.get_chunk_tracker()
            -- Double-check chunk still needs snapshotting
            if tracker:chunk_needs_snapshot(chunk_x, chunk_y) then
                state.chunk_x = chunk_x
                state.chunk_y = chunk_y
                state.phase = SnapshotPhase.FIND_ENTITIES
                
                -- No UDP notification needed - only COMPLETE state matters for external systems
                
                if DEBUG then
                    game.print(string.format("[FLOW] Tick %d: IDLE → FIND_ENTITIES for chunk (%d,%d), queue=%d pending",
                        tick_start, chunk_x, chunk_y, sys_state.stats.chunks_pending))
                end
            else
                if DEBUG then
                    game.print(string.format("[FLOW] Tick %d: Chunk (%d,%d) already snapshotted, skipping", tick_start, chunk_x, chunk_y))
                end
            end
        else
            -- No pending chunks in queue
            -- Check if we should transition to MAINTENANCE phase
            if get_system_phase() == SystemPhase.INITIAL_SNAPSHOTTING then
                -- Bootstrap waiting: Don't immediately transition to MAINTENANCE
                -- Scenarios (like freeplay) call force.chart() which is asynchronous
                -- on_chunk_charted events fire AFTER the chart() call returns
                -- Wait for bootstrap_wait_ticks to allow charting to complete
                sys_state.current_wait_tick = sys_state.current_wait_tick + 1
                
                if sys_state.current_wait_tick >= sys_state.bootstrap_wait_ticks then
                    -- Waited long enough, transition to MAINTENANCE
                    if DEBUG then
                        game.print(string.format("[Snapshot System] Bootstrap wait complete (%d ticks). Pending chunks: %d. Transitioning to MAINTENANCE.",
                            sys_state.current_wait_tick, #sys_state.pending_chunks))
                    end
                    transition_to_maintenance()
                elseif DEBUG and sys_state.current_wait_tick % 60 == 0 then
                    -- Log every second during bootstrap wait
                    game.print(string.format("[Snapshot System] Bootstrap waiting... %d/%d ticks, %d pending chunks",
                        sys_state.current_wait_tick, sys_state.bootstrap_wait_ticks, #sys_state.pending_chunks))
                end
            end
            -- Only send IDLE state when transitioning from active state (handled in phase_complete)
        end
        return
    end
    
    -- FIND_ENTITIES: Gather all data (one tick)
    if state.phase == SnapshotPhase.FIND_ENTITIES then
        if DEBUG then
            game.print(string.format("[DEBUG Map._on_tick_snapshot_chunks] FIND_ENTITIES phase for chunk (%d, %d)", 
                state.chunk_x, state.chunk_y))
        end
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

--- Initialize Map storage (only call in on_init or on_configuration_changed!)
--- IMPORTANT: This modifies storage, so it CANNOT be called in on_load()
function M.init_storage()
    -- Initialize ChunkTracker storage
    ChunkTracker:init_storage()

    -- Initialize system state storage
    init_system_state_storage()
end

--- Initialize Map module (safe to call in on_load)
--- Rebuilds module-level tables from existing storage
--- Does NOT modify storage
function M.init()
    -- Build disk_write_snapshot table after events are initialized
    -- This only sets module-level tables, not storage
    M.disk_write_snapshot = M._build_disk_write_snapshot()
end

--- Get the ChunkTracker singleton instance
--- @return ChunkTracker|nil
function M.get_chunk_tracker()
    return ChunkTracker:get()
end


-- ============================================================================
-- EVENT-DRIVEN RESOURCE SNAPSHOTTING
-- ============================================================================

--- Handle chunk charted event (by players)
--- Behavior depends on orchestration mode:
---   AUTO: Mark chunk as needing snapshot immediately
---   DEFERRED: Track chunk but don't queue until trigger_initial_snapshot() called
---   SELECTIVE: Just track chunk, snapshotting only via explicit snapshot_area() calls
--- @param event table - on_chunk_charted event
function M._on_chunk_charted(event)
    local chunk_x = event.position.x
    local chunk_y = event.position.y
    local tracker = M.get_chunk_tracker()
    local surface = game.surfaces[1]

    -- Count tracked force entities in this chunk (player + all agent forces)
    local chunk_area = {
        left_top = { x = chunk_x * 32, y = chunk_y * 32 },
        right_bottom = { x = (chunk_x + 1) * 32, y = (chunk_y + 1) * 32 }
    }
    local tracked_forces = forces.get_tracked_forces()
    local entity_count = surface.count_entities_filtered {
        area = chunk_area,
        force = tracked_forces
    }

    -- Update chunk tracker with entity count
    -- ChunkTracker IS our cache - no need for separate storage.charted_chunks_cache
    local chunk_entry = tracker:_get_chunk_entry(chunk_x, chunk_y)
    chunk_entry.has_tracked_entities = (entity_count > 0)
    chunk_entry.tracked_entity_count = entity_count

    -- Check if chunk needs snapshotting (not already snapshotted)
    local needs_snapshot = tracker:chunk_needs_snapshot(chunk_x, chunk_y)

    -- Handle based on orchestration mode
    local mode = get_orchestration_mode()
    if mode == OrchestrationMode.AUTO then
        -- AUTO: Queue for immediate snapshotting
        tracker:mark_chunk_needs_snapshot(chunk_x, chunk_y)
    elseif mode == OrchestrationMode.DEFERRED then
        -- DEFERRED: Track in deferred list, don't queue yet
        local sys_state = get_system_state()
        local chunk_key = chunk_x .. "," .. chunk_y
        if not sys_state.deferred_chunks[chunk_key] then
            sys_state.deferred_chunks[chunk_key] = { x = chunk_x, y = chunk_y }
        end
    end
    -- SELECTIVE: Don't auto-queue, only snapshot via explicit snapshot_area() calls

    -- Send chunk_charted payload (always, regardless of mode)
    local chunk = { x = chunk_x, y = chunk_y }
    local payload = udp_payloads.chunk_charted(chunk, game.tick, "player", needs_snapshot)
    payload.orchestration_mode = mode
    udp_payloads.send_event(payload)
end

--- Handle agent chunk charted event
--- Behavior depends on orchestration mode (same as _on_chunk_charted)
--- Note: Agents also mark chunks directly in charting.lua, but this handles the event for consistency
--- @param event table - Agent.on_chunk_charted event with {chunk_x, chunk_y}
function M._on_agent_chunk_charted(event)
    local chunk_x = event.chunk_x
    local chunk_y = event.chunk_y
    local tracker = M.get_chunk_tracker()
    local surface = game.surfaces[1]

    -- Count tracked force entities in this chunk (player + all agent forces)
    local chunk_area = {
        left_top = { x = chunk_x * 32, y = chunk_y * 32 },
        right_bottom = { x = (chunk_x + 1) * 32, y = (chunk_y + 1) * 32 }
    }
    local tracked_forces = forces.get_tracked_forces()
    local entity_count = surface.count_entities_filtered {
        area = chunk_area,
        force = tracked_forces
    }

    -- Update chunk tracker with entity count
    -- ChunkTracker IS our cache - no need for separate storage.charted_chunks_cache
    local chunk_entry = tracker:_get_chunk_entry(chunk_x, chunk_y)
    chunk_entry.has_tracked_entities = (entity_count > 0)
    chunk_entry.tracked_entity_count = entity_count

    -- Check if chunk needs snapshotting (not already snapshotted)
    local needs_snapshot = tracker:chunk_needs_snapshot(chunk_x, chunk_y)

    -- Handle based on orchestration mode
    local mode = get_orchestration_mode()
    if mode == OrchestrationMode.AUTO then
        -- AUTO: Queue for immediate snapshotting
        tracker:mark_chunk_needs_snapshot(chunk_x, chunk_y)
    elseif mode == OrchestrationMode.DEFERRED then
        -- DEFERRED: Track in deferred list, don't queue yet
        local sys_state = get_system_state()
        local chunk_key = chunk_x .. "," .. chunk_y
        if not sys_state.deferred_chunks[chunk_key] then
            sys_state.deferred_chunks[chunk_key] = { x = chunk_x, y = chunk_y }
        end
    end
    -- SELECTIVE: Don't auto-queue, only snapshot via explicit snapshot_area() calls

    -- Send chunk_charted payload (always, regardless of mode)
    local chunk = { x = chunk_x, y = chunk_y }
    local agent_id = event.agent_id or "unknown"
    local payload = udp_payloads.chunk_charted(chunk, game.tick, "agent", needs_snapshot)
    payload.agent_id = agent_id  -- Include agent_id if available
    payload.orchestration_mode = mode
    udp_payloads.send_event(payload)
end

return M