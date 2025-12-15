--- factorio_verse/core/game_state/ResourceGameState.lua
--- ResourceGameState sub-module for managing resource-related functionality.
--- Static module - no instantiation required.

-- Module-level local references for global lookups (performance optimization)
local pairs = pairs

local GameStateError = require("utils.Error")
local utils = require("utils.utils")
local snapshot = require("utils.snapshot")
local udp_payloads = require("utils.udp_payloads")

local M = {}

-- ============================================================================
-- DEBUG FLAG
-- ============================================================================
M.DEBUG = false

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
        bounding_box = {
            min_x = entity.selection_box.left_top.x,
            min_y = entity.selection_box.left_top.y,
            max_x = entity.selection_box.right_bottom.x,
            max_y = entity.selection_box.right_bottom.y
        },
        resources = resources,
        chunk = { x = chunk.x, y = chunk.y }
    }
end

--- Serialize a tree entity
--- @param entity LuaEntity - the tree entity
--- @param chunk table - {x, y, area}
--- @return table - serialized tree data
function M.serialize_tree(entity, chunk)
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
        bounding_box = {
            min_x = entity.selection_box.left_top.x,
            min_y = entity.selection_box.left_top.y,
            max_x = entity.selection_box.right_bottom.x,
            max_y = entity.selection_box.right_bottom.y
        },
        resources = resources,
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

    -- Resources (including crude oil) - check count first
    local resource_count = surface.count_entities_filtered {
        area = chunk.area,
        type = "resource"
    }
    if resource_count > 0 then
        local resource_entities = surface.find_entities_filtered {
            area = chunk.area,
            type = "resource"
        }
        for _, entity in ipairs(resource_entities) do
            if entity and entity.valid then
                table.insert(gathered.resources, M.serialize_resource_tile(entity, entity.name))
            end
        end
    end

    -- Rocks - check count first
    local rock_count = surface.count_entities_filtered({ area = chunk.area, type = "simple-entity" })
    if rock_count > 0 then
        local rock_entities = surface.find_entities_filtered({ area = chunk.area, type = "simple-entity" })
        for _, entity in ipairs(rock_entities) do
            if entity and entity.valid and entity.name and (entity.name:match("rock") or entity.name:match("stone")) then
                table.insert(gathered.rocks, M.serialize_rock(entity, chunk))
            end
        end
    end

    -- Trees - check count first
    local tree_count = surface.count_entities_filtered({ area = chunk.area, type = "tree" })
    if tree_count > 0 then
        local tree_entities = surface.find_entities_filtered({ area = chunk.area, type = "tree" })
        for _, entity in ipairs(tree_entities) do
            if entity and entity.valid then
                table.insert(gathered.trees, M.serialize_tree(entity, chunk))
            end
        end
    end

    -- Water tiles - check count first
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
            local x, y = utils.extract_position(tile)
            if x and y then
                table.insert(gathered.water, { kind = "water", x = x, y = y, amount = 0 })
            end
        end
    end

    return gathered
end

--- Create a trees/rocks update entry when a tree or rock is mined
--- @param entity LuaEntity - The mined entity (tree or rock)
--- @param chunk_x number
--- @param chunk_y number
function M.create_trees_rocks_update_entry(entity, chunk_x, chunk_y)
    -- Accept either a real entity or a fake entity with position table
    if not entity then
        if M.DEBUG then
            game.print(string.format("[DEBUG Resource.create_trees_rocks_update_entry] Tick %d: entity is nil", game.tick))
        end
        return false
    end
    
    -- Position can be a Position object (from real entity) or {x, y} table (from fake entity)
    local position = entity.position
    if M.DEBUG then
        game.print(string.format("[DEBUG Resource.create_trees_rocks_update_entry] Tick %d: entity.name=%s, position type=%s, position=%s", 
            game.tick, tostring(entity.name), type(position), 
            position and string.format("{x=%s, y=%s}", tostring(position.x), tostring(position.y)) or "nil"))
    end
    
    if not position or not position.x or not position.y then
        if M.DEBUG then
            game.print(string.format("[DEBUG Resource.create_trees_rocks_update_entry] Tick %d: Position validation failed - position=%s, has_x=%s, has_y=%s", 
                game.tick, tostring(position), tostring(position and position.x ~= nil), tostring(position and position.y ~= nil)))
        end
        return false
    end
    
    local entity_name = entity.name or "unknown"
    local ent_key = utils.entity_key(entity_name, position.x, position.y)
    
    if M.DEBUG then
        game.print(string.format("[DEBUG Resource.create_trees_rocks_update_entry] Tick %d: entity_name=%s, ent_key=%s, chunk=(%d,%d), position={x=%f, y=%f}", 
            game.tick, entity_name, ent_key, chunk_x, chunk_y, position.x, position.y))
    end
    
    local operation = snapshot.make_remove_operation(ent_key, position, entity_name)
    
    if M.DEBUG then
        game.print(string.format("[DEBUG Resource.create_trees_rocks_update_entry] Tick %d: operation created: op=%s, tick=%s, key=%s", 
            game.tick, tostring(operation.op), tostring(operation.tick), tostring(operation.key)))
    end
    
    local success = snapshot.append_trees_rocks_operation(chunk_x, chunk_y, operation)
    
    if M.DEBUG then
        game.print(string.format("[DEBUG Resource.create_trees_rocks_update_entry] Tick %d: Trees/rocks update entry created for %s at (%d,%d), success=%s", 
            game.tick, entity_name, chunk_x, chunk_y, tostring(success)))
    end
    
    -- Send UDP notification
    if success then
        local chunk = { x = chunk_x, y = chunk_y }
        local payload = udp_payloads.entity_destroyed(chunk, ent_key, entity_name, position)
        udp_payloads.send_entity_operation(payload)
    end
    
    return success
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
            -- Full chunk bounding box (see Map.lua for rationale)
            right_bottom = { x = (chunk_x + 1) * 32, y = (chunk_y + 1) * 32 }
        }
    }

    -- Gather all resources for the chunk
    local gathered = M.gather_resources_for_chunk(chunk)

    -- Write tiles.jsonl (resource tiles like ores) only if resources were found
    if #gathered.resources > 0 then
        local tiles_path = snapshot.resource_file_path(chunk_x, chunk_y, "tiles")
        local tiles_success = snapshot.write_resource_file(tiles_path, gathered.resources)
        
        -- Send UDP notification for tiles file write (overwrite operation)
        if tiles_success then
            local chunk = { x = chunk_x, y = chunk_y }
            local payload = udp_payloads.file_written("resource", chunk, tiles_path, game.tick, #gathered.resources)
            udp_payloads.send_file_io(payload)
        end
    end

    -- Write water-tiles.jsonl only if water tiles were found
    if #gathered.water > 0 then
        local water_tiles_path = snapshot.resource_file_path(chunk_x, chunk_y, "water-tiles")
        local water_tiles_success = snapshot.write_resource_file(water_tiles_path, gathered.water)
        
        -- Send UDP notification for water-tiles file write (overwrite operation)
        if water_tiles_success then
            local chunk = { x = chunk_x, y = chunk_y }
            local payload = udp_payloads.file_written("water", chunk, water_tiles_path, game.tick, #gathered.water)
            udp_payloads.send_file_io(payload)
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
    
    if M.DEBUG then
        game.print(string.format("[DEBUG Resource._rewrite_chunk_resources] Tick %d: Chunk (%d,%d) - trees=%d, rocks=%d, total_entities=%d", 
            game.tick, chunk_x, chunk_y, #gathered.trees, #gathered.rocks, #entities))
    end
    
    if #entities > 0 then
        local entities_path = snapshot.resource_file_path(chunk_x, chunk_y, "entities")
        if M.DEBUG then
            game.print(string.format("[DEBUG Resource._rewrite_chunk_resources] Tick %d: Writing %d entities to %s", 
                game.tick, #entities, entities_path))
        end
        local entities_success = snapshot.write_resource_file(entities_path, entities)
        
        if M.DEBUG then
            game.print(string.format("[DEBUG Resource._rewrite_chunk_resources] Tick %d: Write success=%s", 
                game.tick, tostring(entities_success)))
        end
        
        -- Send UDP notification for entities file write (overwrite operation)
        if entities_success then
            local chunk = { x = chunk_x, y = chunk_y }
            local payload = udp_payloads.file_written("trees_rocks", chunk, entities_path, game.tick, #entities)
            udp_payloads.send_file_io(payload)
        end
    else
        if M.DEBUG then
            game.print(string.format("[DEBUG Resource._rewrite_chunk_resources] Tick %d: No entities to write for chunk (%d,%d)", 
                game.tick, chunk_x, chunk_y))
        end
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

-- Expose disk_write_snapshot property
-- This will be populated after init() is called
M.disk_write_snapshot = {}

--- Get on_tick handlers
--- @return table Array of handler functions
function M.get_on_tick_handlers()
    return {}
end

--- Get events (defined events and nth_tick)
--- @return table {defined_events = {event_id -> handler, ...}, nth_tick = {tick_interval -> handler, ...}}
function M.get_events()
    local events = {}
    local nth_tick = {}
    
    if M.disk_write_snapshot then
        if M.disk_write_snapshot.events then
            for event_id, handler in pairs(M.disk_write_snapshot.events) do
                events[event_id] = handler
            end
        end
        if M.disk_write_snapshot.nth_tick then
            for tick_interval, handler in pairs(M.disk_write_snapshot.nth_tick) do
                nth_tick[tick_interval] = handler
            end
        end
    end
    
    return {
        defined_events = events,
        nth_tick = nth_tick
    }
end

--- Register remote interface for resource admin methods
--- @return table Remote interface table
function M.register_remote_interface()
    return {}
end

return M

