-- ============================================================================
-- LAB GRID - Grid Layout Calculations
-- ============================================================================
-- Defines the grid layout constants and cell position calculations.
-- All dimensions are chunk-aligned for optimal Factorio performance.
-- ============================================================================

local M = {}

-- ============================================================================
-- CONSTANTS (Chunk-Aligned)
-- ============================================================================

M.CHUNK_SIZE = 32                      -- Factorio chunk size in tiles

-- Cell dimensions
M.PLAY_AREA_CHUNKS = 4                 -- 4x4 chunks per play area
M.GAP_CHUNKS = 1                       -- 1 chunk gap between cells
M.CELL_CHUNKS = M.PLAY_AREA_CHUNKS + M.GAP_CHUNKS  -- 5x5 chunks per cell

-- Derived tile dimensions
M.PLAY_AREA_SIZE = M.PLAY_AREA_CHUNKS * M.CHUNK_SIZE  -- 128 tiles
M.GAP_SIZE = M.GAP_CHUNKS * M.CHUNK_SIZE              -- 32 tiles
M.CELL_SIZE = M.CELL_CHUNKS * M.CHUNK_SIZE            -- 160 tiles

-- Grid dimensions
M.GRID_SIZE = 8                        -- 8x8 grid = 64 cells
M.TOTAL_CELLS = M.GRID_SIZE * M.GRID_SIZE  -- 64 cells
M.MAP_SIZE = M.GRID_SIZE * M.CELL_SIZE     -- 1280 tiles (40 chunks)

-- Map bounds (origin at 0,0)
M.MAP_BOUNDS = {
    left_top = {x = 0, y = 0},
    right_bottom = {x = M.MAP_SIZE, y = M.MAP_SIZE}
}

-- ============================================================================
-- CELL POSITION CALCULATIONS
-- ============================================================================

--- Convert cell index to grid coordinates
--- @param cell_index number Cell index (0-63)
--- @return number, number cell_x, cell_y grid coordinates
function M.cell_index_to_grid(cell_index)
    local cell_x = cell_index % M.GRID_SIZE
    local cell_y = math.floor(cell_index / M.GRID_SIZE)
    return cell_x, cell_y
end

--- Convert grid coordinates to cell index
--- @param cell_x number Grid X coordinate (0-7)
--- @param cell_y number Grid Y coordinate (0-7)
--- @return number cell_index
function M.grid_to_cell_index(cell_x, cell_y)
    return cell_y * M.GRID_SIZE + cell_x
end

--- Get the origin (top-left corner) of a cell in tile coordinates
--- @param cell_index number Cell index (0-63)
--- @return table {x, y} origin position in tiles
function M.get_cell_origin(cell_index)
    local cell_x, cell_y = M.cell_index_to_grid(cell_index)
    return {
        x = cell_x * M.CELL_SIZE,
        y = cell_y * M.CELL_SIZE
    }
end

--- Get the play area bounds for a cell (excludes gap)
--- @param cell_index number Cell index (0-63)
--- @return table {left_top, right_bottom} play area bounds
function M.get_play_area_bounds(cell_index)
    local origin = M.get_cell_origin(cell_index)
    return {
        left_top = {
            x = origin.x,
            y = origin.y
        },
        right_bottom = {
            x = origin.x + M.PLAY_AREA_SIZE,
            y = origin.y + M.PLAY_AREA_SIZE
        }
    }
end

--- Get the full cell bounds (including gap on right and bottom)
--- @param cell_index number Cell index (0-63)
--- @return table {left_top, right_bottom} full cell bounds
function M.get_cell_bounds(cell_index)
    local origin = M.get_cell_origin(cell_index)
    return {
        left_top = {
            x = origin.x,
            y = origin.y
        },
        right_bottom = {
            x = origin.x + M.CELL_SIZE,
            y = origin.y + M.CELL_SIZE
        }
    }
end

--- Get the spawn point (center of play area) for a cell
--- @param cell_index number Cell index (0-63)
--- @return table {x, y} spawn position
function M.get_spawn_position(cell_index)
    local origin = M.get_cell_origin(cell_index)
    return {
        x = origin.x + M.PLAY_AREA_SIZE / 2,
        y = origin.y + M.PLAY_AREA_SIZE / 2
    }
end

--- Check if a position is within a cell's play area
--- @param position table {x, y} position to check
--- @param cell_index number Cell index to check against
--- @return boolean true if position is within play area
function M.is_in_play_area(position, cell_index)
    local bounds = M.get_play_area_bounds(cell_index)
    return position.x >= bounds.left_top.x and
           position.x < bounds.right_bottom.x and
           position.y >= bounds.left_top.y and
           position.y < bounds.right_bottom.y
end

--- Get cell index from a world position
--- @param position table {x, y} world position
--- @return number|nil cell_index, or nil if outside grid
function M.get_cell_at_position(position)
    -- Check if within map bounds
    if position.x < 0 or position.x >= M.MAP_SIZE or
       position.y < 0 or position.y >= M.MAP_SIZE then
        return nil
    end

    local cell_x = math.floor(position.x / M.CELL_SIZE)
    local cell_y = math.floor(position.y / M.CELL_SIZE)

    -- Clamp to valid range
    cell_x = math.max(0, math.min(cell_x, M.GRID_SIZE - 1))
    cell_y = math.max(0, math.min(cell_y, M.GRID_SIZE - 1))

    return M.grid_to_cell_index(cell_x, cell_y)
end

--- Get chunk coordinates for a cell's play area
--- @param cell_index number Cell index (0-63)
--- @return table Array of {x, y} chunk coordinates
function M.get_cell_chunks(cell_index)
    local origin = M.get_cell_origin(cell_index)
    local start_chunk_x = math.floor(origin.x / M.CHUNK_SIZE)
    local start_chunk_y = math.floor(origin.y / M.CHUNK_SIZE)

    local chunks = {}
    for cy = 0, M.PLAY_AREA_CHUNKS - 1 do
        for cx = 0, M.PLAY_AREA_CHUNKS - 1 do
            table.insert(chunks, {
                x = start_chunk_x + cx,
                y = start_chunk_y + cy
            })
        end
    end
    return chunks
end

--- Get configuration summary for debugging/display
--- @return table Configuration values
function M.get_config()
    return {
        chunk_size = M.CHUNK_SIZE,
        play_area_chunks = M.PLAY_AREA_CHUNKS,
        gap_chunks = M.GAP_CHUNKS,
        cell_chunks = M.CELL_CHUNKS,
        play_area_size = M.PLAY_AREA_SIZE,
        gap_size = M.GAP_SIZE,
        cell_size = M.CELL_SIZE,
        grid_size = M.GRID_SIZE,
        total_cells = M.TOTAL_CELLS,
        map_size = M.MAP_SIZE
    }
end

return M
