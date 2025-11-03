local M = {}


--- @param h number
--- @param s number
--- @param v number
--- @return table
function M.hsv_to_rgb(h, s, v)
    local r, g, b
    local i = math.floor(h * 6)
    local f = h * 6 - i
    local p = v * (1 - s)
    local q = v * (1 - f * s)
    local t = v * (1 - (1 - f) * s)

    i = i % 6

    if i == 0 then
        r, g, b = v, t, p
    elseif i == 1 then
        r, g, b = q, v, p
    elseif i == 2 then
        r, g, b = p, v, t
    elseif i == 3 then
        r, g, b = p, q, v
    elseif i == 4 then
        r, g, b = t, p, v
    elseif i == 5 then
        r, g, b = v, p, q
    end

    return { r = r, g = g, b = b, a = 1.0 }
end


function M.min_position(a, b)
    return {
        x = math.floor(math.min(a.x, b.x)),
        y = math.floor(math.min(a.y, b.y))
    }
end

function M.chart_native_start_area(surface, force, position, game_state)
    local radius_tiles = 150 -- Hacky but accepted vanilla feel
    local area = {
        { x = position.x - radius_tiles, y = position.y - radius_tiles },
        { x = position.x + radius_tiles, y = position.y + radius_tiles }
    }
    force.chart(surface, area)
    
    -- Register charted area for headless server fallback (if game_state provided)
    if game_state then
        game_state.map:register_charted_area({
            left_top = { x = area[1].x, y = area[1].y },
            right_bottom = { x = area[2].x, y = area[2].y }
        })
    end
    
    -- Don't force generate chunks synchronously - this causes crashes when called from RCON
    -- Chunks will be generated naturally by the engine over time
    -- surface.request_to_generate_chunks(position, math.ceil(radius_tiles / 32))
    -- surface.force_generate_chunk_requests()
end

function M.players_to_spectators()
    for _, player in pairs(game.connected_players) do
        player.set_controller({ type = defines.controllers.spectator })
    end
end

local CHUNK = 32
local VISION_CHUNK_RADIUS = 1 -- 1 => 3x3 like a player-ish feel; try 2 for 5x5

local function chunk_pos(pos)
    return { x = math.floor(pos.x / CHUNK), y = math.floor(pos.y / CHUNK) }
end

local function chunk_bounds(cx, cy, radius)
    local left   = (cx - radius) * CHUNK
    local top    = (cy - radius) * CHUNK
    local right  = (cx + radius + 1) * CHUNK
    local bottom = (cy + radius + 1) * CHUNK
    return { left_top = { x = left, y = top }, right_bottom = { x = right, y = bottom } }
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

--- Alias for entity_status_to_name (for backward compatibility)
--- @param status any
--- @return string|nil
function M.status_to_name(status)
    return M.entity_status_to_name(status)
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

function M.triple_print(print_str)
    game.print(print_str)
    log(print_str)
    rcon.print(print_str)
end

-- SCHEMA-DRIVEN FLATTENING UTILITIES -----------------------------------------

function M.blueprint_to_table(blueprint_string)
    local version=string.sub(blueprint_string,1,1)
    local body=string.sub(blueprint_string,2)
    local json_str=helpers.decode_string(body)
    if not json_str then return nil end
    local output=helpers.json_to_table(json_str)
    if not output then return nil end
    return output
end

--- Converts a Lua table describing blueprint data into a valid Factorio blueprint string.
--- Factorio expects blueprint strings in the format: "<version><base64-encoded json>"
--- See: https://lua-api.factorio.com/latest/LuaBlueprint.html and https://wiki.factorio.com/Blueprint_string_format
--- @param blueprint_table table - The table representing the blueprint (should contain "blueprint" or "blueprint_book" as the root key)
--- @return string|nil - The blueprint string, or nil on error
function M.table_to_blueprint(blueprint_table)
    -- Validate: The top-level key must be "blueprint" or "blueprint_book"
    if type(blueprint_table) ~= "table" or (not blueprint_table.blueprint and not blueprint_table.blueprint_book) then
        return nil
    end

    -- Encode table to JSON string (Factorio supports pretty-printed and minified)
    local ok, json_str = pcall(helpers.table_to_json, blueprint_table)
    if not ok or not json_str then
        return nil
    end

    -- Base64 encode (Factorio expects a URL-safe base64 (A-Za-z0-9-_) with no padding, standard output is usually fine)
    local ok2, encoded = pcall(helpers.encode_string, json_str)
    if not ok2 or not encoded then
        return nil
    end

    -- Prepend version ("0" or "1". Factorio 1.1+ uses "1" for blueprints and blueprint books.)
    local version = "1"
    return version .. encoded
end

return M
