--- factorio_verse/core/game_state/ResourceGameState.lua
--- ResourceGameState sub-module for managing resource-related functionality.
--- Static module - no instantiation required.

-- Module-level local references for global lookups (performance optimization)
local pairs = pairs
local ipairs = ipairs
local table_insert = table.insert
local string_match = string.match
local string_format = string.format
-- Cache helpers functions for performance
local table_to_json = helpers.table_to_json

local GameStateError = require("utils.Error")
local utils = require("utils.utils")
local snapshot = require("utils.snapshot")
local udp_payloads = require("utils.udp_payloads")

local M = {}

-- ============================================================================
-- DEBUG FLAG
-- ============================================================================
M.DEBUG = false  -- Enable for performance analysis

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
    local start_tick = game.tick
    local surface = game.surfaces[1]
    if not surface then
        return { resources = {}, rocks = {}, trees = {}, water = {} }
    end

    -- Pre-allocate result tables
    local gathered_resources = {}
    local gathered_rocks = {}
    local gathered_trees = {}
    local gathered_water = {}
    
    local chunk_area = chunk.area

    -- Resources (including crude oil) - PERFORMANCE: count before find (fast C++ check)
    local resource_count = surface.count_entities_filtered {
        area = chunk_area,
        type = "resource"
    }
    if resource_count > 0 then
        local resource_entities = surface.find_entities_filtered {
            area = chunk_area,
            type = "resource"
        }
        -- Use numeric for loop for hot path
        local entity_count = #resource_entities
        for i = 1, entity_count do
            local entity = resource_entities[i]
            if entity and entity.valid then
                gathered_resources[#gathered_resources + 1] = M.serialize_resource_tile(entity, entity.name)
            end
        end
    end

    -- Rocks - check count first
    local rock_count = surface.count_entities_filtered({ area = chunk_area, type = "simple-entity" })
    if rock_count > 0 then
        local rock_entities = surface.find_entities_filtered({ area = chunk_area, type = "simple-entity" })
        -- Use numeric for loop for hot path
        local entity_count = #rock_entities
        for i = 1, entity_count do
            local entity = rock_entities[i]
            if entity and entity.valid then
                local entity_name = entity.name
                if entity_name and (string_match(entity_name, "rock") or string_match(entity_name, "stone")) then
                    gathered_rocks[#gathered_rocks + 1] = M.serialize_rock(entity, chunk)
                end
            end
        end
    end

    -- Trees - check count first
    local tree_count = surface.count_entities_filtered({ area = chunk_area, type = "tree" })
    if tree_count > 0 then
        local tree_entities = surface.find_entities_filtered({ area = chunk_area, type = "tree" })
        -- Use numeric for loop for hot path
        local entity_count = #tree_entities
        for i = 1, entity_count do
            local entity = tree_entities[i]
            if entity and entity.valid then
                gathered_trees[#gathered_trees + 1] = M.serialize_tree(entity, chunk)
            end
        end
    end

    -- Water tiles - check count first
    -- Use vanilla water tile names (works for all standard Factorio tiles)
    local water_tile_names = { "water", "deepwater", "water-green", "deepwater-green" }

    local water_count = surface.count_tiles_filtered {
        area = chunk_area,
        name = water_tile_names
    }
    if water_count > 0 then
        local tiles = surface.find_tiles_filtered {
            area = chunk_area,
            name = water_tile_names
        }
        -- Use numeric for loop for hot path
        local tiles_count = #tiles
        for i = 1, tiles_count do
            local tile = tiles[i]
            local x, y = utils.extract_position(tile)
            if x and y then
                gathered_water[#gathered_water + 1] = { kind = "water", x = x, y = y, amount = 0 }
            end
        end
    end

    local end_tick = game.tick
    if M.DEBUG then
        local duration = end_tick - start_tick
        local total = #gathered_resources + #gathered_rocks + #gathered_trees + #gathered_water
        game.print(string_format("[PERF Resource] Chunk (%d,%d) gather complete: %d items in %d ticks",
            chunk.x, chunk.y, total, duration))
        if duration > 0 then
            game.print(string_format("[PERF Resource] ⚠️  WARNING: gather took %d ticks - should be instant!", duration))
        end
    end
    
    return {
        resources = gathered_resources,
        rocks = gathered_rocks,
        trees = gathered_trees,
        water = gathered_water
    }
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
    
    -- IDEMPOTENCY CHECK: Prevent duplicate remove events for the same entity
    -- Track recent removals in storage to avoid duplicate events within a short time window
    storage.recent_tree_removals = storage.recent_tree_removals or {}
    local removal_key = string.format("%s@%.2f,%.2f", entity_name, position.x, position.y)
    local recent_removal = storage.recent_tree_removals[removal_key]
    
    -- Check if we've already created a remove operation for this entity recently (within last 100 ticks)
    if recent_removal and (game.tick - recent_removal.tick) < 100 then
        if M.DEBUG then
            game.print(string.format("[DEBUG Resource.create_trees_rocks_update_entry] Tick %d: Skipping duplicate remove for %s at (%.2f, %.2f) - already removed at tick %d", 
                game.tick, entity_name, position.x, position.y, recent_removal.tick))
        end
        log(string.format("[Resource] Skipping duplicate remove operation for %s at (%.2f, %.2f) - already removed at tick %d", 
            entity_name, position.x, position.y, recent_removal.tick))
        return false  -- Skip creating duplicate remove operation
    end
    
    -- Record this removal
    storage.recent_tree_removals[removal_key] = { tick = game.tick }
    
    -- Clean up old entries (older than 1000 ticks) to prevent storage bloat
    if game.tick % 1000 == 0 then  -- Only cleanup periodically
        for key, removal in pairs(storage.recent_tree_removals) do
            if game.tick - removal.tick > 1000 then
                storage.recent_tree_removals[key] = nil
            end
        end
    end
    
    if M.DEBUG then
        game.print(string.format("[DEBUG Resource.create_trees_rocks_update_entry] Tick %d: entity_name=%s, chunk=(%d,%d), position={x=%f, y=%f}", 
            game.tick, entity_name, chunk_x, chunk_y, position.x, position.y))
    end
    
    local operation = snapshot.make_remove_operation(position, entity_name)
    
    if M.DEBUG then
        game.print(string.format("[DEBUG Resource.create_trees_rocks_update_entry] Tick %d: operation created: op=%s, tick=%s", 
            game.tick, tostring(operation.op), tostring(operation.tick)))
    end
    
    snapshot.append_trees_rocks_operation(chunk_x, chunk_y, operation)
    
    if M.DEBUG then
        game.print(string.format("[DEBUG Resource.create_trees_rocks_update_entry] Tick %d: Trees/rocks update entry created for %s at (%d,%d)", 
            game.tick, entity_name, chunk_x, chunk_y))
    end
    
    -- Send UDP notification
    -- CRITICAL: Always send UDP regardless of write success to maintain Factorio determinism
    -- IMPORTANT: Use the SAME sequence number that was written to the file
    local chunk = { x = chunk_x, y = chunk_y }
    local payload = udp_payloads.entity_destroyed(chunk, entity_name, position)
    payload.sequence = operation.sequence  -- Use sequence from file write
    udp_payloads.send_entity_operation(payload)
    
    return true
end

--- Rewrite resource file for a chunk
--- Called when resources are depleted or changed
--- @param chunk_x number
--- @param chunk_y number
--- @param exclude_entity LuaEntity|table|nil Optional entity to exclude from rewrite (e.g., entity being deleted)
function M._rewrite_chunk_resources(chunk_x, chunk_y, exclude_entity)
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

    -- CRITICAL FIX: Exclude the entity being deleted from the gathered list
    -- This prevents the deleted tree from being written back to the init file
    local exclude_position = nil
    local exclude_name = nil
    if exclude_entity then
        -- Handle both real entities and fake entities (with position table)
        if exclude_entity.position then
            local pos = exclude_entity.position
            if type(pos) == "table" and pos.x and pos.y then
                exclude_position = { x = pos.x, y = pos.y }
                exclude_name = exclude_entity.name
            elseif exclude_entity.valid and exclude_entity.position then
                -- Real entity with position object
                exclude_position = { x = exclude_entity.position.x, y = exclude_entity.position.y }
                exclude_name = exclude_entity.name
            end
        end
    end

    -- Remove excluded entity from rocks if present
    if exclude_position and exclude_name then
        for i = #gathered.rocks, 1, -1 do
            local rock = gathered.rocks[i]
            if rock and rock.position then
                local rock_x = rock.position.x
                local rock_y = rock.position.y
                -- Use small epsilon for floating point comparison
                if math.abs(rock_x - exclude_position.x) < 0.01 and 
                   math.abs(rock_y - exclude_position.y) < 0.01 and
                   rock.name == exclude_name then
                    if M.DEBUG then
                        game.print(string.format("[DEBUG Resource._rewrite_chunk_resources] Tick %d: Excluding rock %s at (%.2f, %.2f) from rewrite", 
                            game.tick, exclude_name, exclude_position.x, exclude_position.y))
                    end
                    table.remove(gathered.rocks, i)
                end
            end
        end
    end

    -- Remove excluded entity from trees if present
    if exclude_position and exclude_name then
        for i = #gathered.trees, 1, -1 do
            local tree = gathered.trees[i]
            if tree and tree.position then
                local tree_x = tree.position.x
                local tree_y = tree.position.y
                -- Use small epsilon for floating point comparison
                if math.abs(tree_x - exclude_position.x) < 0.01 and 
                   math.abs(tree_y - exclude_position.y) < 0.01 and
                   tree.name == exclude_name then
                    if M.DEBUG then
                        game.print(string.format("[DEBUG Resource._rewrite_chunk_resources] Tick %d: Excluding tree %s at (%.2f, %.2f) from rewrite", 
                            game.tick, exclude_name, exclude_position.x, exclude_position.y))
                    end
                    table.remove(gathered.trees, i)
                end
            end
        end
    end

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

