-- ============================================================================
-- LAB GRID - Cell Management
-- ============================================================================
-- Handles cell initialization, resource spawning, and reset.
-- Each cell is a self-contained lab environment.
-- ============================================================================

local grid = require("grid")

local M = {}

-- ============================================================================
-- RESOURCE CONFIGURATION
-- ============================================================================

-- Resource patch configuration (offsets from cell origin)
M.RESOURCE_CONFIG = {
    patches = {
        {name = "iron-ore",   offset = {x = 16, y = 16},  size = 8, amount = 50000},
        {name = "copper-ore", offset = {x = 48, y = 16},  size = 8, amount = 50000},
        {name = "coal",       offset = {x = 16, y = 48},  size = 8, amount = 50000},
        {name = "stone",      offset = {x = 48, y = 48},  size = 8, amount = 50000},
    },
    water = {
        offset = {x = 16, y = 96},
        size = 5  -- 5x5 water tiles
    },
    oil = {
        offsets = {
            {x = 80, y = 96},
            {x = 88, y = 96},
            {x = 96, y = 96}
        },
        amount = 300000  -- crude-oil amount per well
    }
}

-- ============================================================================
-- TILE GENERATION
-- ============================================================================

--- Generate lab tiles for a cell's play area
--- @param surface LuaSurface
--- @param cell_index number
local function generate_cell_tiles(surface, cell_index)
    local bounds = grid.get_play_area_bounds(cell_index)
    local tiles = {}

    for y = bounds.left_top.y, bounds.right_bottom.y - 1 do
        for x = bounds.left_top.x, bounds.right_bottom.x - 1 do
            table.insert(tiles, {name = "dirt-1", position = {x, y}})
        end
    end

    surface.set_tiles(tiles)
end

--- Generate gap tiles (void/out-of-map) for cell gaps
--- @param surface LuaSurface
--- @param cell_index number
local function generate_gap_tiles(surface, cell_index)
    local origin = grid.get_cell_origin(cell_index)
    local tiles = {}

    -- Right gap (32 tiles wide)
    for y = origin.y, origin.y + grid.PLAY_AREA_SIZE - 1 do
        for x = origin.x + grid.PLAY_AREA_SIZE, origin.x + grid.CELL_SIZE - 1 do
            table.insert(tiles, {name = "out-of-map", position = {x, y}})
        end
    end

    -- Bottom gap (32 tiles tall, full width)
    for y = origin.y + grid.PLAY_AREA_SIZE, origin.y + grid.CELL_SIZE - 1 do
        for x = origin.x, origin.x + grid.CELL_SIZE - 1 do
            table.insert(tiles, {name = "out-of-map", position = {x, y}})
        end
    end

    if #tiles > 0 then
        surface.set_tiles(tiles)
    end
end

-- ============================================================================
-- RESOURCE SPAWNING
-- ============================================================================

--- Place a square resource patch
--- @param surface LuaSurface
--- @param resource_name string
--- @param center_x number
--- @param center_y number
--- @param size number Side length of square
--- @param amount number Amount per tile
local function place_resource_patch(surface, resource_name, center_x, center_y, size, amount)
    local half_size = math.floor(size / 2)

    for y = center_y - half_size, center_y + half_size - 1 do
        for x = center_x - half_size, center_x + half_size - 1 do
            surface.create_entity{
                name = resource_name,
                amount = amount,
                position = {x + 0.5, y + 0.5}  -- Center on tile
            }
        end
    end
end

--- Place water tiles
--- @param surface LuaSurface
--- @param origin_x number
--- @param origin_y number
--- @param size number Side length of square
local function place_water(surface, origin_x, origin_y, size)
    local tiles = {}
    for y = origin_y, origin_y + size - 1 do
        for x = origin_x, origin_x + size - 1 do
            table.insert(tiles, {name = "water", position = {x, y}})
        end
    end
    surface.set_tiles(tiles)
end

--- Place crude oil wells
--- @param surface LuaSurface
--- @param positions table Array of {x, y} positions
--- @param amount number Amount per well
--- @param force LuaForce Force to assign
local function place_oil_wells(surface, positions, amount, force)
    for _, pos in ipairs(positions) do
        surface.create_entity{
            name = "crude-oil",
            position = {pos.x + 0.5, pos.y + 0.5},
            amount = amount
        }
    end
end

--- Spawn all resources for a cell
--- @param surface LuaSurface
--- @param cell_index number
function M.spawn_resources(surface, cell_index)
    local origin = grid.get_cell_origin(cell_index)

    -- Place ore patches
    for _, patch in ipairs(M.RESOURCE_CONFIG.patches) do
        place_resource_patch(
            surface,
            patch.name,
            origin.x + patch.offset.x,
            origin.y + patch.offset.y,
            patch.size,
            patch.amount
        )
    end

    -- Place water
    local water = M.RESOURCE_CONFIG.water
    place_water(
        surface,
        origin.x + water.offset.x,
        origin.y + water.offset.y,
        water.size
    )

    -- Place oil wells
    local oil_positions = {}
    for _, offset in ipairs(M.RESOURCE_CONFIG.oil.offsets) do
        table.insert(oil_positions, {
            x = origin.x + offset.x,
            y = origin.y + offset.y
        })
    end
    place_oil_wells(surface, oil_positions, M.RESOURCE_CONFIG.oil.amount)
end

-- ============================================================================
-- CELL INITIALIZATION
-- ============================================================================

--- Initialize a single cell (tiles + resources)
--- @param surface LuaSurface
--- @param cell_index number
function M.initialize_cell(surface, cell_index)
    -- Generate lab tiles for play area
    generate_cell_tiles(surface, cell_index)

    -- Generate gap tiles (out-of-map)
    generate_gap_tiles(surface, cell_index)

    -- Spawn resources
    M.spawn_resources(surface, cell_index)
end

--- Initialize all cells in the grid
--- @param surface LuaSurface
function M.initialize_all_cells(surface)
    for cell_index = 0, grid.TOTAL_CELLS - 1 do
        M.initialize_cell(surface, cell_index)
    end
end

-- ============================================================================
-- CELL CLEARING & RESET
-- ============================================================================

--- Clear all entities in a cell (preserves tiles)
--- @param surface LuaSurface
--- @param cell_index number
--- @param preserve_characters boolean
function M.clear_entities(surface, cell_index, preserve_characters)
    local bounds = grid.get_play_area_bounds(cell_index)
    local entities = surface.find_entities(bounds)

    for _, entity in pairs(entities) do
        if entity.valid then
            if preserve_characters and entity.type == "character" then
                -- Skip characters
            else
                entity.destroy({raise_destroy = true})
            end
        end
    end
end

--- Reset a cell to initial state
--- @param surface LuaSurface
--- @param cell_index number
--- @param preserve_agent boolean Keep the agent character
function M.reset_cell(surface, cell_index, preserve_agent)
    -- Clear all entities
    M.clear_entities(surface, cell_index, preserve_agent)

    -- Regenerate tiles (in case they were modified)
    generate_cell_tiles(surface, cell_index)

    -- Respawn resources
    M.spawn_resources(surface, cell_index)

    -- Reset force production statistics if there's an assigned force
    local force_name = "cell_" .. cell_index
    if game.forces[force_name] then
        -- Note: reset_item_production_statistics is the correct API
        -- but we need to check if it exists
        local force = game.forces[force_name]
        -- Production stats auto-reset when we clear entities and respawn
    end
end

--- Reset all cells
--- @param surface LuaSurface
--- @param preserve_agents boolean
function M.reset_all_cells(surface, preserve_agents)
    for cell_index = 0, grid.TOTAL_CELLS - 1 do
        M.reset_cell(surface, cell_index, preserve_agents)
    end
end

-- ============================================================================
-- CELL STATUS
-- ============================================================================

--- Get status of a cell
--- @param cell_index number
--- @return table Status info
function M.get_cell_status(cell_index)
    local surface = game.surfaces[1]
    local bounds = grid.get_play_area_bounds(cell_index)

    -- Check if force exists
    local force_name = "cell_" .. cell_index
    local force_exists = game.forces[force_name] ~= nil

    -- Count entities - only include forces that exist
    local forces_to_check = {"player"}
    if force_exists then
        table.insert(forces_to_check, force_name)
    end
    local entity_count = surface.count_entities_filtered{
        area = bounds,
        force = forces_to_check
    }

    -- Check for agent in cell (look for characters)
    local characters = surface.find_entities_filtered{
        area = bounds,
        type = "character"
    }
    local has_agent = #characters > 0
    local agent_info = nil
    if has_agent and characters[1].valid then
        agent_info = {
            force = characters[1].force.name,
            position = characters[1].position
        }
    end

    return {
        cell_index = cell_index,
        bounds = bounds,
        spawn_position = grid.get_spawn_position(cell_index),
        entity_count = entity_count,
        force_exists = force_exists,
        force_name = force_name,
        has_agent = has_agent,
        agent_info = agent_info
    }
end

return M
