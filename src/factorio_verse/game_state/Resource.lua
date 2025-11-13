--- factorio_verse/core/game_state/ResourceGameState.lua
--- ResourceGameState sub-module for managing resource-related functionality.
--- Static module - no instantiation required.

-- Module-level local references for global lookups (performance optimization)
local pairs = pairs

local GameStateError = require("types.Error")
local utils = require("utils.utils")
local snapshot = require("utils.snapshot")

local M = {}

--- Serialize a single resource tile
--- @param entity LuaEntity - the resource entity
--- @param resource_name string - the resource name
--- @return table - serialized resource data
function M.serialize_resource_tile(entity, resource_name)
    return {
        kind = resource_name,
        x = utils.floor(entity.position.x),
        y = utils.floor(entity.position.y),
        amount = entity.amount or 0
    }
end

--- Serialize a rock entity
--- @param entity LuaEntity - the rock entity
--- @param chunk table - {x, y, area}
--- @return table - serialized rock data
function M.serialize_rock(entity, chunk)
    local size = 1
    if entity.name:match("huge") then
        size = 3
    elseif entity.name:match("big") then
        size = 2
    end

    local resources = {}
    if entity.prototype and entity.prototype.mineable_properties and entity.prototype.mineable_properties.products then
        for _, product in pairs(entity.prototype.mineable_properties.products) do
            table.insert(resources, {
                name = product.name,
                amount = product.amount or product.amount_min or 1,
                probability = product.probability or 1
            })
        end
    end

    return {
        name = entity.name,
        type = entity.type,
        position = entity.position,
        size = size,
        resources = resources,
        chunk = { x = chunk.x, y = chunk.y }
    }
end

--- Serialize a tree entity
--- @param entity LuaEntity - the tree entity
--- @param chunk table - {x, y, area}
--- @return table - serialized tree data
function M.serialize_tree(entity, chunk)
    return {
        name = entity.name,
        position = entity.position,
        bounding_box = {
            min_x = entity.bounding_box.left_top.x,
            min_y = entity.bounding_box.left_top.y,
            max_x = entity.bounding_box.right_bottom.x,
            max_y = entity.bounding_box.right_bottom.y
        },
        chunk = { x = chunk.x, y = chunk.y }
    }
end

-- ============================================================================
-- DISK WRITE SNAPSHOT FUNCTIONALITY
-- ============================================================================

--- Initialize custom events for resource snapshotting
--- Must be called during on_init/on_load
function M.init()
    -- No custom events needed for resources yet
    -- Build disk_write_snapshot table
    M.disk_write_snapshot = M._build_disk_write_snapshot()
end

--- Gather all resources for a specific chunk
--- @param chunk table - {x, y, area}
--- @return table - {resources = {...}, rocks = {...}, trees = {...}, water = {...}}
function M.gather_resources_for_chunk(chunk)
    local surface = game.surfaces[1]
    if not surface then
        return { resources = {}, rocks = {}, trees = {}, water = {} }
    end

    local gathered = {
        resources = {}, -- Mineable resources (iron, copper, coal, crude-oil, etc.)
        rocks = {},     -- Simple entities (rock-huge, rock-big, etc.)
        trees = {},     -- Tree entities
        water = {}      -- Water tiles
    }

    -- Resources (including crude oil)
    local resource_entities = surface.find_entities_filtered {
        area = chunk.area,
        type = "resource"
    }
    for _, entity in ipairs(resource_entities) do
        if entity and entity.valid then
            table.insert(gathered.resources, M.serialize_resource_tile(entity, entity.name))
        end
    end

    -- Rocks
    local rock_entities = surface.find_entities_filtered({ area = chunk.area, type = "simple-entity" })
    for _, entity in ipairs(rock_entities) do
        if entity and entity.valid and entity.name and (entity.name:match("rock") or entity.name:match("stone")) then
            table.insert(gathered.rocks, M.serialize_rock(entity, chunk))
        end
    end

    -- Trees
    local tree_entities = surface.find_entities_filtered({ area = chunk.area, type = "tree" })
    for _, entity in ipairs(tree_entities) do
        if entity and entity.valid then
            table.insert(gathered.trees, M.serialize_tree(entity, chunk))
        end
    end

    -- Water tiles
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

    local tiles = surface.find_tiles_filtered {
        area = chunk.area,
        name = water_tile_names
    }
    for _, tile in ipairs(tiles) do
        local x, y = utils.extract_position(tile)
        if x and y then
            table.insert(gathered.water, { kind = "water", x = x, y = y, amount = 0 })
        end
    end

    return gathered
end

--- Rewrite resource file for a chunk
--- Called when resources are depleted or changed
--- @param chunk_x number
--- @param chunk_y number
function M._rewrite_chunk_resources(chunk_x, chunk_y)
    local chunk = {
        x = chunk_x,
        y = chunk_y,
        area = {
            left_top = { x = chunk_x * 32, y = chunk_y * 32 },
            right_bottom = { x = (chunk_x + 1) * 32, y = (chunk_y + 1) * 32 }
        }
    }

    -- Gather all resources for the chunk
    local gathered = M.gather_resources_for_chunk(chunk)

    -- Write resources.jsonl
    local resources_path = snapshot.resource_file_path(chunk_x, chunk_y, "resources")
    local resources_success = snapshot.write_resource_file(resources_path, gathered.resources)
    
    -- Send UDP notification for resources file update
    if resources_success then
        snapshot.send_file_event_udp(
            "file_updated",
            "resource",
            chunk_x,
            chunk_y,
            nil, -- no position for resource files
            nil, -- no entity_name
            nil, -- no component_type
            resources_path
        )
    end

    -- Write water.jsonl
    local water_path = snapshot.resource_file_path(chunk_x, chunk_y, "water")
    local water_success = snapshot.write_resource_file(water_path, gathered.water)
    
    -- Send UDP notification for water file update
    if water_success then
        snapshot.send_file_event_udp(
            "file_updated",
            "water",
            chunk_x,
            chunk_y,
            nil, -- no position for water files
            nil, -- no entity_name
            nil, -- no component_type
            water_path
        )
    end
end

--- Handle resource depleted event
--- @param event table - Event data with entity field
function M._on_resource_depleted(event)
    local entity = event.entity
    if not entity or not entity.valid then
        return
    end

    -- Get chunk coordinates
    local chunk_coords = utils.to_chunk_coordinates(entity.position)
    if not chunk_coords then
        return
    end

    -- Rewrite the entire chunk's resource files
    M._rewrite_chunk_resources(chunk_coords.x, chunk_coords.y)
end

--- Build disk write snapshot events table
--- Called after init() to populate events
function M._build_disk_write_snapshot()
    return {
        events = {
            [defines.events.on_resource_depleted] = M._on_resource_depleted,
        },
        nth_tick = {}
    }
end

-- Expose disk_write_snapshot property for GameState aggregation
-- This will be populated after init() is called
M.disk_write_snapshot = {}

return M

