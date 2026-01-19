--- Geometry Utilities
--- Provides spatial calculations for placement hints
---
--- Position semantics: {x, y} where x increases eastward, y increases southward
--- Direction values: 0=North, 4=East, 8=South, 12=West

local M = {}

-- ============================================================================
-- DIRECTION CONSTANTS
-- ============================================================================

M.DIRECTIONS = {
    NORTH = defines.direction.north,  -- 0
    EAST = defines.direction.east,    -- 4
    SOUTH = defines.direction.south,  -- 8
    WEST = defines.direction.west,    -- 12
}

M.CARDINAL_DIRECTIONS = {
    defines.direction.north,
    defines.direction.east,
    defines.direction.south,
    defines.direction.west,
}

M.DIRECTION_NAMES = {
    [defines.direction.north] = "north",
    [defines.direction.east] = "east",
    [defines.direction.south] = "south",
    [defines.direction.west] = "west",
}

-- Direction vectors: unit vector for each cardinal direction
M.DIRECTION_VECTORS = {
    [defines.direction.north] = {x = 0, y = -1},
    [defines.direction.east] = {x = 1, y = 0},
    [defines.direction.south] = {x = 0, y = 1},
    [defines.direction.west] = {x = -1, y = 0},
}

-- ============================================================================
-- POSITION UTILITIES
-- ============================================================================

--- Calculate distance between two positions
--- @param pos1 table Position {x, y}
--- @param pos2 table Position {x, y}
--- @return number Euclidean distance
function M.distance(pos1, pos2)
    local dx = pos2.x - pos1.x
    local dy = pos2.y - pos1.y
    return math.sqrt(dx * dx + dy * dy)
end

--- Calculate Manhattan distance between two positions
--- @param pos1 table Position {x, y}
--- @param pos2 table Position {x, y}
--- @return number Manhattan distance
function M.manhattan_distance(pos1, pos2)
    return math.abs(pos2.x - pos1.x) + math.abs(pos2.y - pos1.y)
end

--- Snap position to tile center (e.g., 10.3 -> 10.5)
--- @param position table Position {x, y}
--- @return table Snapped position {x, y}
function M.snap_to_tile_center(position)
    return {
        x = math.floor(position.x) + 0.5,
        y = math.floor(position.y) + 0.5,
    }
end

--- Snap position to tile corner (e.g., 10.3 -> 10.0)
--- @param position table Position {x, y}
--- @return table Snapped position {x, y}
function M.snap_to_tile_corner(position)
    return {
        x = math.floor(position.x),
        y = math.floor(position.y),
    }
end

--- Add offset to position
--- @param position table Position {x, y}
--- @param offset table Offset {x, y}
--- @return table New position {x, y}
function M.add_offset(position, offset)
    return {
        x = position.x + offset.x,
        y = position.y + offset.y,
    }
end

-- ============================================================================
-- DIRECTION UTILITIES
-- ============================================================================

--- Get the opposite direction
--- @param direction number Direction value
--- @return number Opposite direction
function M.opposite_direction(direction)
    return (direction + 8) % 16
end

--- Rotate direction clockwise by 90 degrees
--- @param direction number Direction value
--- @return number Rotated direction
function M.rotate_clockwise(direction)
    return (direction + 4) % 16
end

--- Rotate direction counter-clockwise by 90 degrees
--- @param direction number Direction value
--- @return number Rotated direction
function M.rotate_counter_clockwise(direction)
    return (direction + 12) % 16
end

--- Rotate a vector by a direction (relative to north)
--- @param vector table Vector {x, y}
--- @param direction number Direction to rotate to
--- @return table Rotated vector {x, y}
function M.rotate_vector(vector, direction)
    -- Normalize direction to cardinal
    local dir = direction % 16

    if dir == defines.direction.north or dir == 0 then
        -- No rotation
        return {x = vector.x, y = vector.y}
    elseif dir == defines.direction.east or dir == 4 then
        -- 90° clockwise: (x, y) -> (-y, x)
        return {x = -vector.y, y = vector.x}
    elseif dir == defines.direction.south or dir == 8 then
        -- 180°: (x, y) -> (-x, -y)
        return {x = -vector.x, y = -vector.y}
    elseif dir == defines.direction.west or dir == 12 then
        -- 270° clockwise: (x, y) -> (y, -x)
        return {x = vector.y, y = -vector.x}
    end

    -- Fallback for non-cardinal directions (shouldn't happen in practice)
    return {x = vector.x, y = vector.y}
end

--- Apply a vector offset to a position, rotated by direction
--- @param position table Base position {x, y}
--- @param vector table Offset vector {x, y}
--- @param direction number Direction to rotate vector
--- @return table New position {x, y}
function M.apply_rotated_vector(position, vector, direction)
    local rotated = M.rotate_vector(vector, direction)
    return M.add_offset(position, rotated)
end

-- ============================================================================
-- BOUNDING BOX UTILITIES
-- ============================================================================

--- Get width and height from a bounding box
--- @param bbox table Bounding box {left_top: {x,y}, right_bottom: {x,y}}
--- @return number, number width, height
function M.bbox_dimensions(bbox)
    local width = bbox.right_bottom.x - bbox.left_top.x
    local height = bbox.right_bottom.y - bbox.left_top.y
    return width, height
end

--- Get center of a bounding box
--- @param bbox table Bounding box {left_top: {x,y}, right_bottom: {x,y}}
--- @return table Center position {x, y}
function M.bbox_center(bbox)
    return {
        x = (bbox.left_top.x + bbox.right_bottom.x) / 2,
        y = (bbox.left_top.y + bbox.right_bottom.y) / 2,
    }
end

--- Check if two bounding boxes overlap (AABB collision)
--- @param bbox1 table First bounding box
--- @param bbox2 table Second bounding box
--- @return boolean True if boxes overlap
function M.bbox_overlap(bbox1, bbox2)
    -- No overlap if one is completely left/right/above/below the other
    if bbox1.right_bottom.x <= bbox2.left_top.x then return false end
    if bbox1.left_top.x >= bbox2.right_bottom.x then return false end
    if bbox1.right_bottom.y <= bbox2.left_top.y then return false end
    if bbox1.left_top.y >= bbox2.right_bottom.y then return false end
    return true
end

--- Check if a position is inside a bounding box
--- @param position table Position {x, y}
--- @param bbox table Bounding box
--- @return boolean True if position is inside
function M.position_in_bbox(position, bbox)
    return position.x >= bbox.left_top.x
        and position.x <= bbox.right_bottom.x
        and position.y >= bbox.left_top.y
        and position.y <= bbox.right_bottom.y
end

--- Create a bounding box centered at position with given half-size
--- @param position table Center position {x, y}
--- @param half_width number Half width
--- @param half_height number Half height
--- @return table Bounding box {left_top, right_bottom}
function M.bbox_from_center(position, half_width, half_height)
    return {
        left_top = {
            x = position.x - half_width,
            y = position.y - half_height,
        },
        right_bottom = {
            x = position.x + half_width,
            y = position.y + half_height,
        },
    }
end

--- Expand a bounding box by a margin
--- @param bbox table Bounding box
--- @param margin number Margin to add on all sides
--- @return table Expanded bounding box
function M.bbox_expand(bbox, margin)
    return {
        left_top = {
            x = bbox.left_top.x - margin,
            y = bbox.left_top.y - margin,
        },
        right_bottom = {
            x = bbox.right_bottom.x + margin,
            y = bbox.right_bottom.y + margin,
        },
    }
end

-- ============================================================================
-- ENTITY FOOTPRINT
-- ============================================================================

--- Get the tiles covered by an entity's footprint
--- @param entity_name string Entity prototype name
--- @param position table Entity center position {x, y}
--- @param direction number|nil Entity direction
--- @return table {tiles: array, bounding_box: table, center: position}
function M.get_entity_footprint(entity_name, position, direction)
    local proto = prototypes.entity[entity_name]
    if not proto then
        return {
            error = "Unknown entity prototype: " .. tostring(entity_name),
            tiles = {},
        }
    end

    -- Get collision box from prototype
    local cbox = proto.collision_box
    local width = cbox.right_bottom.x - cbox.left_top.x
    local height = cbox.right_bottom.y - cbox.left_top.y

    -- Swap width/height for east/west facing asymmetric entities
    if direction and (direction == defines.direction.east or direction == defines.direction.west) then
        if width ~= height then
            width, height = height, width
        end
    end

    -- Calculate tile bounds
    local half_w = width / 2
    local half_h = height / 2

    local min_x = math.floor(position.x - half_w)
    local max_x = math.floor(position.x + half_w - 0.001)  -- -0.001 to handle exact boundaries
    local min_y = math.floor(position.y - half_h)
    local max_y = math.floor(position.y + half_h - 0.001)

    -- Collect tiles
    local tiles = {}
    for x = min_x, max_x do
        for y = min_y, max_y do
            table.insert(tiles, {x = x, y = y})
        end
    end

    return {
        tiles = tiles,
        bounding_box = M.bbox_from_center(position, half_w, half_h),
        center = position,
        tile_width = proto.tile_width,
        tile_height = proto.tile_height,
    }
end

-- ============================================================================
-- PERPENDICULAR OFFSET CALCULATION
-- ============================================================================

--- Calculate perpendicular offset (alignment quality) for a position relative to a source
--- Lower values = better alignment
--- @param source_position table Source entity position
--- @param source_direction number Source entity direction
--- @param target_position table Target position to evaluate
--- @return number Perpendicular offset (0.0 = perfect alignment)
function M.perpendicular_offset(source_position, source_direction, target_position)
    -- For north/south facing, measure horizontal (X) offset
    -- For east/west facing, measure vertical (Y) offset
    if source_direction == defines.direction.north or source_direction == defines.direction.south then
        return math.abs(target_position.x - source_position.x)
    elseif source_direction == defines.direction.east or source_direction == defines.direction.west then
        return math.abs(target_position.y - source_position.y)
    end
    return 0.0
end

-- ============================================================================
-- AREA ITERATION
-- ============================================================================

--- Generate all tile positions in an area
--- @param area table Area {left_top: {x,y}, right_bottom: {x,y}}
--- @return function Iterator that yields {x, y} positions
function M.iter_area_tiles(area)
    local min_x = math.floor(area.left_top.x)
    local max_x = math.floor(area.right_bottom.x)
    local min_y = math.floor(area.left_top.y)
    local max_y = math.floor(area.right_bottom.y)

    local x = min_x - 1
    local y = min_y

    return function()
        x = x + 1
        if x > max_x then
            x = min_x
            y = y + 1
        end
        if y > max_y then
            return nil
        end
        return {x = x, y = y}
    end
end

--- Get all tile positions in an area as an array
--- @param area table Area {left_top: {x,y}, right_bottom: {x,y}}
--- @return table Array of {x, y} positions
function M.get_area_tiles(area)
    local tiles = {}
    for pos in M.iter_area_tiles(area) do
        table.insert(tiles, pos)
    end
    return tiles
end

return M
