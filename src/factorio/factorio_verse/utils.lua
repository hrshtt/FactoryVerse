local M = {}


function M.chart_native_start_area(surface, force, position)
    local radius_tiles = 150  -- Hacky but accepted vanilla feel
    force.chart(surface, {
      { x = position.x - radius_tiles, y = position.y - radius_tiles },
      { x = position.x + radius_tiles, y = position.y + radius_tiles }
    })
    surface.request_to_generate_chunks(position, math.ceil(radius_tiles / 32))
    surface.force_generate_chunk_requests()
end

function M.players_to_spectators()
    for _, player in pairs(game.connected_players) do
        player.set_controller({type = defines.controllers.spectator})
    end
end

local CHUNK = 32
local VISION_CHUNK_RADIUS = 1  -- 1 => 3x3 like a player-ish feel; try 2 for 5x5

local function chunk_pos(pos)
  return { x = math.floor(pos.x / CHUNK), y = math.floor(pos.y / CHUNK) }
end

local function chunk_bounds(cx, cy, radius)
  local left   = (cx - radius) * CHUNK
  local top    = (cy - radius) * CHUNK
  local right  = (cx + radius + 1) * CHUNK
  local bottom = (cy + radius + 1) * CHUNK
  return { left_top = {x = left, y = top}, right_bottom = {x = right, y = bottom} }
end

function M.chart_scanners()
  if not storage.agent_characters then return end
  for _, agent in pairs(storage.agent_characters) do
    if agent and agent.valid then
      local cp = chunk_pos(agent.position)

      -- Only do work if any chunk in the vision square isn’t charted yet.
      local needs_chart = false
      for dx = -VISION_CHUNK_RADIUS, VISION_CHUNK_RADIUS do
        for dy = -VISION_CHUNK_RADIUS, VISION_CHUNK_RADIUS do
          if not agent.force.is_chunk_charted(agent.surface, {x = cp.x + dx, y = cp.y + dy}) then
            needs_chart = true
            break
          end
        end
        if needs_chart then break end
      end

      if needs_chart then
        local area = chunk_bounds(cp.x, cp.y, VISION_CHUNK_RADIUS)
        agent.force.chart(agent.surface, area) -- authoritative chart

        -- Mirror to any spectator forces so clients in spectator mode see it live.
        for _, pc in pairs(game.connected_players) do
          if pc.controller_type == defines.controllers.spectator or pc.spectator then
            pc.force.chart(agent.surface, area)
          end
        end

        -- Optional: ensure smooth edges if you’re racing ahead
        agent.surface.request_to_generate_chunks(agent.position, VISION_CHUNK_RADIUS + 1)
        agent.surface.force_generate_chunk_requests()
      end
    end
  end
end


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
        -- Use integer arithmetic for distance calculation to avoid floating-point precision loss
        local dx_a, dy_a = ax - ox, ay - oy
        local dx_b, dy_b = bx - ox, by - oy
        local da = dx_a * dx_a + dy_a * dy_a
        local db = dx_b * dx_b + dy_b * dy_b
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

-- Enum helpers ----------------------------------------------------------------

--- Reverse-lookup a name from a Factorio defines.* enum table
--- @param enum_table table
--- @param value any
--- @return string|nil
function M.enum_value_to_name(enum_table, value)
    if type(enum_table) ~= "table" then return nil end
    for k, v in pairs(enum_table) do
        if v == value then return k end
    end
    return nil
end

--- Convert defines.direction value to its lowercase name (e.g., "north-east")
--- @param dir number|nil
--- @return string|nil
function M.direction_to_name(dir)
    if dir == nil then return nil end
    local name = M.enum_value_to_name(defines.direction or {}, dir)
    if not name then return nil end
    return string.lower(string.gsub(name, "_", "-"))
end

--- Convert LuaEntity.status (defines.entity_status) to name
--- @param status any
--- @return string|nil
function M.entity_status_to_name(status)
    local name = M.enum_value_to_name(defines.entity_status or {}, status)
    if not name then return nil end
    return string.lower(string.gsub(name, "_", "-"))
end

--- Map orientation [0,1) to 8-way compass name
--- @param orientation number|nil
--- @return string|nil
function M.orientation_to_name(orientation)
    if type(orientation) ~= "number" then return nil end
    local names = {
        "north", "north-east", "east", "south-east",
        "south", "south-west", "west", "north-west"
    }
    local idx = math.floor(orientation * 8 + 0.5) % 8
    return names[idx + 1]
end

return M