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

--- Disjoint Set Union (DSU) data structure for efficient connected component tracking
--- Used in connected component labeling algorithms
M.DSU = {}
M.DSU.__index = M.DSU

function M.DSU:new()
    return setmetatable({
        parent = {},
        size = {}
    }, self)
end

function M.DSU:find(x)
    local p = self.parent[x]
    if not p then
        self.parent[x] = x
        self.size[x] = 1
        return x
    end
    if p ~= x then 
        self.parent[x] = self:find(p) -- path compression
    end
    return self.parent[x]
end

function M.DSU:union(a, b)
    a = self:find(a)
    b = self:find(b)
    if a == b then return a end
    
    -- union by size
    if (self.size[a] or 1) < (self.size[b] or 1) then 
        a, b = b, a 
    end
    self.parent[b] = a
    self.size[a] = (self.size[a] or 1) + (self.size[b] or 1)
    return a
end

--- Utility functions for chunk coordinate operations
function M.chunk_key(cx, cy) 
    return cx .. ":" .. cy 
end

function M.floor(v) 
    return math.floor(v) 
end

--- Extract x,y coordinates from various Factorio position objects
--- @param obj table - position object (LuaTile, LuaEntity, or {x,y} table)
--- @return number|nil, number|nil - x, y coordinates or nil if invalid
function M.extract_position(obj)
    if not obj then return nil end
    
    if obj.position then
        local px, py = obj.position.x, obj.position.y
        if px and py then return M.floor(px), M.floor(py) end
    end
    
    local px = obj.x or obj[1]
    local py = obj.y or obj[2]
    if px and py then return M.floor(px), M.floor(py) end
    
    return nil
end

--- Check if two ranges overlap
--- @param a1 number - start of range A
--- @param a2 number - end of range A  
--- @param b1 number - start of range B
--- @param b2 number - end of range B
--- @return boolean - true if ranges overlap
function M.ranges_overlap(a1, a2, b1, b2)
    return not (a2 < b1 or b2 < a1)
end

return M