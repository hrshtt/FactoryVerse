-- ============================================================================
-- TEST GROUND SCENARIO - Control Script
-- ============================================================================
-- Purpose: Provide a deterministic 512x512 testing environment with:
--   - Lab tile floor (no obstacles, perfect for testing)
--   - Programmatic resource/entity placement
--   - Known, reproducible map state
--   - Remote interfaces for test control
--   - Force re-snapshotting capability
--
-- Design Philosophy:
--   - Tests should be able to set up their own map state
--   - No random generation - everything is explicit
--   - Helpers for common patterns (resource patches, entity grids)
--   - Metadata tracking for validation
-- ============================================================================

-- ============================================================================
-- CONSTANTS
-- ============================================================================

local TEST_AREA_SIZE = 512  -- 512x512 tile area
local TEST_AREA_HALF = TEST_AREA_SIZE / 2
local CHUNK_SIZE = 32

-- Test area bounds (centered at origin)
local TEST_BOUNDS = {
    left_top = {x = -TEST_AREA_HALF, y = -TEST_AREA_HALF},
    right_bottom = {x = TEST_AREA_HALF, y = TEST_AREA_HALF}
}

-- ============================================================================
-- STATE TRACKING
-- ============================================================================

--- Global state for test scenario
--- Tracks all programmatically placed resources and entities for validation
local TestState = {
    resources = {},  -- {name, position, amount, patch_id}
    entities = {},   -- {name, position, entity_id, direction}
    metadata = {
        scenario_version = "1.0.0",
        test_area_size = TEST_AREA_SIZE,
        test_bounds = TEST_BOUNDS,
    }
}

-- ============================================================================
-- INITIALIZATION
-- ============================================================================

--- Initialize test ground on scenario start
local function init_test_ground()
    local surface = game.surfaces[1]
    if not surface then
        game.print("ERROR: No surface found!")
        return
    end
    
    -- Clear test area of all entities
    local entities = surface.find_entities(TEST_BOUNDS)
    for _, entity in pairs(entities) do
        -- Don't destroy player characters
        if entity.type ~= "character" then
            entity.destroy()
        end
    end
    
    -- Set all tiles to lab-dark-1 (development tile - no obstacles)
    local tiles = {}
    for y = TEST_BOUNDS.left_top.y, TEST_BOUNDS.right_bottom.y - 1 do
        for x = TEST_BOUNDS.left_top.x, TEST_BOUNDS.right_bottom.x - 1 do
            table.insert(tiles, {name = "lab-dark-1", position = {x, y}})
        end
    end
    
    surface.set_tiles(tiles)
    
    game.print("✅ Test ground initialized: " .. TEST_AREA_SIZE .. "x" .. TEST_AREA_SIZE .. " lab tiles")
    game.print("   Bounds: (" .. TEST_BOUNDS.left_top.x .. "," .. TEST_BOUNDS.left_top.y .. ") to (" .. 
               TEST_BOUNDS.right_bottom.x .. "," .. TEST_BOUNDS.right_bottom.y .. ")")
end

-- ============================================================================
-- RESOURCE PLACEMENT HELPERS
-- ============================================================================

--- Place a square resource patch
--- @param resource_name string Resource name (e.g., "iron-ore", "copper-ore")
--- @param center_x number Center X position
--- @param center_y number Center Y position
--- @param size number Side length of square patch
--- @param amount number Amount per tile
--- @return table Metadata about placed patch
local function place_resource_patch(resource_name, center_x, center_y, size, amount)
    local surface = game.surfaces[1]
    if not surface then
        return {success = false, error = "No surface"}
    end
    
    local half_size = size / 2
    local placed_count = 0
    local patch_id = "patch_" .. resource_name .. "_" .. center_x .. "_" .. center_y
    
    for y = center_y - half_size, center_y + half_size - 1 do
        for x = center_x - half_size, center_x + half_size - 1 do
            local entity = surface.create_entity{
                name = resource_name,
                amount = amount,
                position = {x, y}
            }
            if entity then
                placed_count = placed_count + 1
                -- Track in state
                table.insert(TestState.resources, {
                    name = resource_name,
                    position = {x = x, y = y},
                    amount = amount,
                    patch_id = patch_id
                })
            end
        end
    end
    
    return {
        success = true,
        patch_id = patch_id,
        resource_name = resource_name,
        center = {x = center_x, y = center_y},
        size = size,
        amount_per_tile = amount,
        total_tiles = placed_count,
        total_amount = placed_count * amount
    }
end

--- Place a circular resource patch
--- @param resource_name string Resource name
--- @param center_x number Center X position
--- @param center_y number Center Y position
--- @param radius number Radius of circle
--- @param amount number Amount per tile
--- @return table Metadata about placed patch
local function place_resource_patch_circle(resource_name, center_x, center_y, radius, amount)
    local surface = game.surfaces[1]
    if not surface then
        return {success = false, error = "No surface"}
    end
    
    local placed_count = 0
    local patch_id = "patch_circle_" .. resource_name .. "_" .. center_x .. "_" .. center_y
    local radius_squared = radius * radius
    
    for y = center_y - radius, center_y + radius do
        for x = center_x - radius, center_x + radius do
            local dx = x - center_x
            local dy = y - center_y
            local dist_squared = dx * dx + dy * dy
            
            if dist_squared <= radius_squared then
                local entity = surface.create_entity{
                    name = resource_name,
                    amount = amount,
                    position = {x, y}
                }
                if entity then
                    placed_count = placed_count + 1
                    table.insert(TestState.resources, {
                        name = resource_name,
                        position = {x = x, y = y},
                        amount = amount,
                        patch_id = patch_id
                    })
                end
            end
        end
    end
    
    return {
        success = true,
        patch_id = patch_id,
        resource_name = resource_name,
        center = {x = center_x, y = center_y},
        radius = radius,
        amount_per_tile = amount,
        total_tiles = placed_count,
        total_amount = placed_count * amount
    }
end

-- ============================================================================
-- ENTITY PLACEMENT HELPERS
-- ============================================================================

--- Place an entity at a position
--- @param entity_name string Entity name
--- @param position table {x, y}
--- @param direction number|nil Direction (0-7)
--- @param force string|nil Force name (default "player")
--- @return table Result with entity reference and metadata
local function place_entity(entity_name, position, direction, force)
    local surface = game.surfaces[1]
    if not surface then
        return {success = false, error = "No surface"}
    end
    
    local entity = surface.create_entity{
        name = entity_name,
        position = position,
        direction = direction,
        force = force or "player"
    }
    
    if not entity then
        return {success = false, error = "Failed to place entity"}
    end
    
    -- Track in state
    local metadata = {
        name = entity_name,
        position = {x = entity.position.x, y = entity.position.y},
        entity_id = entity.unit_number,
        direction = direction,
        force = force or "player"
    }
    table.insert(TestState.entities, metadata)
    
    return {
        success = true,
        metadata = metadata
    }
end

--- Place entities in a grid pattern
--- @param entity_name string Entity name
--- @param start_x number Starting X position
--- @param start_y number Starting Y position
--- @param rows number Number of rows
--- @param cols number Number of columns
--- @param spacing_x number Horizontal spacing
--- @param spacing_y number Vertical spacing
--- @return table Results with all placed entities
local function place_entity_grid(entity_name, start_x, start_y, rows, cols, spacing_x, spacing_y)
    local results = {
        success = true,
        entities = {},
        count = 0
    }
    
    for row = 0, rows - 1 do
        for col = 0, cols - 1 do
            local x = start_x + (col * spacing_x)
            local y = start_y + (row * spacing_y)
            
            local result = place_entity(entity_name, {x = x, y = y})
            if result.success then
                table.insert(results.entities, result.entity)
                results.count = results.count + 1
            end
        end
    end
    
    return results
end

-- ============================================================================
-- AREA MANAGEMENT
-- ============================================================================

--- Clear all entities in a bounding box
--- @param bounds table {left_top = {x, y}, right_bottom = {x, y}}
--- @param preserve_characters boolean Preserve player characters
--- @return table Result with count of cleared entities
local function clear_area(bounds, preserve_characters)
    local surface = game.surfaces[1]
    if not surface then
        return {success = false, error = "No surface"}
    end
    
    local entities = surface.find_entities(bounds)
    local cleared_count = 0
    
    for _, entity in pairs(entities) do
        if not (preserve_characters and entity.type == "character") then
            entity.destroy()
            cleared_count = cleared_count + 1
        end
    end
    
    -- Clear tracked state for this area
    local function is_in_bounds(pos)
        return pos.x >= bounds.left_top.x and pos.x < bounds.right_bottom.x and
               pos.y >= bounds.left_top.y and pos.y < bounds.right_bottom.y
    end
    
    -- Filter resources
    local new_resources = {}
    for _, res in ipairs(TestState.resources) do
        if not is_in_bounds(res.position) then
            table.insert(new_resources, res)
        end
    end
    TestState.resources = new_resources
    
    -- Filter entities
    local new_entities = {}
    for _, ent in ipairs(TestState.entities) do
        if not is_in_bounds(ent.position) then
            table.insert(new_entities, ent)
        end
    end
    TestState.entities = new_entities
    
    return {
        success = true,
        cleared_count = cleared_count
    }
end

--- Reset test area to clean state (lab tiles, no entities)
local function reset_test_area()
    clear_area(TEST_BOUNDS, true)
    init_test_ground()
    
    return {
        success = true,
        message = "Test area reset to clean state"
    }
end

-- ============================================================================
-- SNAPSHOT CONTROL
-- ============================================================================

--- Force re-snapshot of specified chunks
--- @param chunk_coords table|nil Array of {x, y} chunk coordinates, or nil for all charted chunks
--- @return table Result with snapshot status
local function force_resnapshot(chunk_coords)
    -- Check if fv_snapshot mod is loaded
    if not remote.interfaces["map"] then
        return {
            success = false,
            error = "fv_snapshot mod not loaded (no 'map' remote interface)"
        }
    end
    
    local chunks_to_snapshot = {}
    
    if chunk_coords then
        -- Specific chunks provided
        chunks_to_snapshot = chunk_coords
    else
        -- Snapshot all chunks in test area
        local min_chunk_x = math.floor(TEST_BOUNDS.left_top.x / CHUNK_SIZE)
        local max_chunk_x = math.floor(TEST_BOUNDS.right_bottom.x / CHUNK_SIZE)
        local min_chunk_y = math.floor(TEST_BOUNDS.left_top.y / CHUNK_SIZE)
        local max_chunk_y = math.floor(TEST_BOUNDS.right_bottom.y / CHUNK_SIZE)
        
        for chunk_y = min_chunk_y, max_chunk_y do
            for chunk_x = min_chunk_x, max_chunk_x do
                table.insert(chunks_to_snapshot, {x = chunk_x, y = chunk_y})
            end
        end
    end
    
    -- Enqueue chunks for snapshotting
    local enqueued_count = 0
    for _, chunk in ipairs(chunks_to_snapshot) do
        -- Call remote interface to enqueue chunk
        -- Note: This assumes the map module exposes enqueue_chunk_for_snapshot
        -- We'll need to add this to the remote interface
        local success = pcall(function()
            remote.call("map", "enqueue_chunk_for_snapshot", chunk.x, chunk.y, 10)  -- High priority
        end)
        
        if success then
            enqueued_count = enqueued_count + 1
        end
    end
    
    return {
        success = true,
        chunks_enqueued = enqueued_count,
        total_chunks = #chunks_to_snapshot
    }
end

-- ============================================================================
-- METADATA & VALIDATION
-- ============================================================================

--- Get test scenario metadata
--- @return table Metadata including resources, entities, bounds
local function get_test_metadata()
    return {
        metadata = TestState.metadata,
        resources = TestState.resources,
        entities = TestState.entities,
        resource_count = #TestState.resources,
        entity_count = #TestState.entities,
        test_bounds = TEST_BOUNDS
    }
end

--- Validate that a resource exists at a position
--- @param resource_name string Resource name
--- @param position table {x, y}
--- @return table Validation result
local function validate_resource_at(resource_name, position)
    local surface = game.surfaces[1]
    if not surface then
        return {valid = false, error = "No surface"}
    end
    
    -- Search in a small area around the position (resources are on tile grid)
    local search_radius = 0.5
    local entities = surface.find_entities_filtered{
        area = {
            {position.x - search_radius, position.y - search_radius},
            {position.x + search_radius, position.y + search_radius}
        },
        type = "resource",
        name = resource_name
    }
    
    if #entities == 0 then
        return {
            valid = false,
            expected = resource_name,
            found = nil
        }
    end
    
    local entity = entities[1]
    return {
        valid = true,
        expected = resource_name,
        found = entity.name,
        amount = entity.amount
    }
end

--- Validate that an entity exists at a position
--- @param entity_name string Entity name
--- @param position table {x, y}
--- @return table Validation result
local function validate_entity_at(entity_name, position)
    local surface = game.surfaces[1]
    if not surface then
        return {valid = false, error = "No surface"}
    end
    
    -- Search in a small area around the position
    local search_radius = 0.5
    local entities = surface.find_entities_filtered{
        area = {
            {position.x - search_radius, position.y - search_radius},
            {position.x + search_radius, position.y + search_radius}
        },
        name = entity_name
    }
    
    if #entities == 0 then
        return {
            valid = false,
            expected = entity_name,
            found = nil
        }
    end
    
    local entity = entities[1]
    return {
        valid = true,
        expected = entity_name,
        found = entity.name,
        entity_id = entity.unit_number,
        direction = entity.direction
    }
end

-- ============================================================================
-- REMOTE INTERFACE
-- ============================================================================

-- Clean up existing interface if it exists (for hot-reload support)
if remote.interfaces["test_ground"] then
    remote.remove_interface("test_ground")
end

remote.add_interface("test_ground", {
    -- Resource placement
    place_resource_patch = place_resource_patch,
    place_resource_patch_circle = place_resource_patch_circle,
    
    -- Entity placement
    place_entity = place_entity,
    place_entity_grid = place_entity_grid,
    
    -- Area management
    clear_area = clear_area,
    reset_test_area = reset_test_area,
    
    -- Snapshot control
    force_resnapshot = force_resnapshot,
    
    -- Metadata & validation
    get_test_metadata = get_test_metadata,
    validate_resource_at = validate_resource_at,
    validate_entity_at = validate_entity_at,
    
    -- Utility
    get_test_bounds = function() return TEST_BOUNDS end,
    get_test_area_size = function() return TEST_AREA_SIZE end
})

-- ============================================================================
-- EVENT HANDLERS
-- ============================================================================

script.on_init(function()
    game.print("🧪 Test Ground Scenario Initialized")
    init_test_ground()
    
    -- Enable always day for better visibility
    game.surfaces[1].always_day = true
    
    -- Reveal test area for player force
    local radius = TEST_AREA_HALF + 100  -- Reveal slightly more than test area
    game.forces["player"].chart(game.surfaces[1], {
        {-radius, -radius},
        {radius, radius}
    })
    
    game.print("✅ Test area revealed and set to permanent daylight")
end)

script.on_configuration_changed(function()
    game.print("🔄 Test Ground Scenario Configuration Changed")
    init_test_ground()
end)
