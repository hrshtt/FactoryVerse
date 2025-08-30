local M = {}

--- Sort a list of coordinates in-place by distance to an origin.
--- Coordinates can be tables like {x=..., y=...} or arrays {x, y}.
--- @param coords table
--- @param origin table|nil  -- table with x and y; defaults to {x=0,y=0}
--- @return table coords     -- the same table reference, sorted
function M.sort_coordinates_by_distance(coords, origin)
    log("Sorting coordinates by distance")
    if type(coords) ~= "table" then return coords end
    origin = origin or { x = 0, y = 0 }
    local ox = origin.x or origin[1] or 0
    local oy = origin.y or origin[2] or 0

    local function get_xy(point)
        if type(point) ~= "table" then return 0, 0 end
        local px = point.x or point[1] or 0
        local py = point.y or point[2] or 0
        return px, py
    end

    table.sort(coords, function(a, b)
        local ax, ay = get_xy(a)
        local bx, by = get_xy(b)
        local da = (ax - ox) * (ax - ox) + (ay - oy) * (ay - oy)
        local db = (bx - ox) * (bx - ox) + (by - oy) * (by - oy)
        return da < db
    end)

    return coords
end



return M