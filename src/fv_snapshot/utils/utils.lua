local M = {}

M.direction = {
    [defines.direction.north] = defines.direction.north,
    n = defines.direction.north,
    north = defines.direction.north,
    up = defines.direction.north,

    [defines.direction.south] = defines.direction.south,
    s = defines.direction.south,
    south = defines.direction.south,
    down = defines.direction.south,

    [defines.direction.east] = defines.direction.east,
    e = defines.direction.east,
    east = defines.direction.east,
    right = defines.direction.east,

    [defines.direction.west] = defines.direction.west,
    w = defines.direction.west,
    west = defines.direction.west,
    left = defines.direction.west,

    [defines.direction.northeast] = defines.direction.northeast,
    ne = defines.direction.northeast,
    northeast = defines.direction.northeast,

    [defines.direction.northwest] = defines.direction.northwest,
    nw = defines.direction.northwest,
    northwest = defines.direction.northwest,

    [defines.direction.southeast] = defines.direction.southeast,
    se = defines.direction.southeast,
    southeast = defines.direction.southeast,

    [defines.direction.southwest] = defines.direction.southwest,
    sw = defines.direction.southwest,
    southwest = defines.direction.southwest,
}

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

--- Returns chunk coordinates from a position object using Factorio's logic (same as LuaSurface::get_chunk_position)
--- See: https://lua-api.factorio.com/latest/LuaSurface.html#LuaSurface.get_chunk_position
--- @param position table - Position with x/y or [1]/[2]
--- @return table - {x: number, y: number} chunk coordinates
function M.to_chunk_coordinates(position)
    -- position may be {x=..., y=...} or {1=..., 2=...}, prefer .x/.y
    local x = position.x or position[1]
    local y = position.y or position[2]
    local chunk_x = math.floor(x / 32)
    local chunk_y = math.floor(y / 32)
    return { x = chunk_x, y = chunk_y }
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

--- Generate a unique key for an entity based on its name and position
--- @param entity_name string - Entity prototype name
--- @param pos_x number - X coordinate
--- @param pos_y number - Y coordinate
--- @return string - Key in format "entity_name..position.x..position.y"
function M.entity_key(entity_name, pos_x, pos_y)
    return string.format("%s:%s,%s", entity_name, pos_x, pos_y)
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

--- @param status any
--- @return string|nil
function M.status_to_name(status)
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

-- PARAMETER VALIDATION UTILITIES ------------------------------------------------

--- Validate and normalize position structure {x: number, y: number}
--- @param pos table|nil Position to validate
--- @return table|nil Normalized position {x: number, y: number} or nil if invalid
function M.validate_position(pos)
    if pos == nil then return nil end
    if type(pos) ~= "table" then return nil end
    local x = pos.x
    local y = pos.y
    if type(x) ~= "number" or type(y) ~= "number" then
        return nil
    end
    -- Return normalized position (ensure numbers, optionally floor)
    return { x = x, y = y }
end

--- Validate and normalize direction (string alias or number enum)
--- @param dir string|number|nil Direction to validate
--- @return number|nil Normalized defines.direction enum (0-7) or nil if invalid
function M.validate_direction(dir)
    if dir == nil then return nil end

    -- If it's already a number, check if it's a valid direction enum (0-7)
    if type(dir) == "number" then
        if dir >= 0 and dir <= 7 then
            return dir
        end
        return nil
    end

    -- If it's a string, try to look it up in Direction
    if type(dir) == "string" then
        local key = string.lower(dir)
        local normalized = M.direction[key]
        if normalized ~= nil then
            -- defines.direction enum values are numbers 0-7, but type system sees them as specific types
            -- Return as-is since they are actually numbers
            return normalized
        end
        return nil
    end

    return nil
end

--- Validate orientation value [0, 1)
--- @param orientation number|nil Orientation to validate
--- @return number|nil Normalized orientation [0, 1) or nil if invalid
function M.validate_orientation(orientation)
    if orientation == nil then return nil end
    if type(orientation) ~= "number" then return nil end

    -- Orientation is in range [0, 1) - wrap if needed
    if orientation < 0 or orientation >= 1 then
        -- Allow slight overflow (1.0) and wrap it
        if orientation >= 1.0 and orientation < 1.0001 then
            return 0.0
        end
        return nil
    end

    return orientation
end

--- Validate entity prototype name exists
--- @param entity_name string|nil Entity prototype name to validate
--- @return boolean True if entity prototype exists, false otherwise
function M.validate_entity_name(entity_name)
    if entity_name == nil then return false end
    if type(entity_name) ~= "string" or entity_name == "" then return false end

    -- Check if entity prototype exists in prototypes.entity
    if prototypes and prototypes.entity then
        local proto = prototypes.entity[entity_name]
        return proto ~= nil
    end

    -- Fallback: if prototypes is not available, just check it's a non-empty string
    -- (This allows validation to work in contexts where prototypes isn't loaded)
    return true
end

--- Validate recipe name exists for agent's force
--- Note: Recipes are per-force (LuaForce.recipes), so we validate against the agent's force
--- @param recipe_name string|nil Recipe name to validate
--- @param agent_id number|nil Optional agent_id to get the agent's force
--- @return boolean True if recipe exists in agent's force, false otherwise
function M.validate_recipe(recipe_name, agent_id)
    if recipe_name == nil then return false end
    if type(recipe_name) ~= "string" or recipe_name == "" then return false end

    -- If agent_id is provided, validate against the agent's force
    if agent_id ~= nil and type(agent_id) == "number" then
        -- Get agent's force from storage
        if storage and storage.agent_forces then
            local force_name = storage.agent_forces[agent_id]
            if force_name and game and game.forces then
                local force = game.forces[force_name]
                if force and force.recipes then
                    local recipe = force.recipes[recipe_name]
                    return recipe ~= nil
                end
            end
        end

        -- Fallback: try to get agent entity and use its force
        if storage and storage.agents then
            local agent = storage.agents[agent_id]
            if agent and agent.valid and agent.force then
                local recipe = agent.force.recipes[recipe_name]
                return recipe ~= nil
            end
        end
    end

    -- Fallback: if agent_id not available or validation failed, just check it's a non-empty string
    -- (This allows validation to work in contexts where game/agent isn't available)
    return true
end

--- Validate technology name exists for agent's force
--- Note: Technologies are per-force (LuaForce.technologies), so we validate against the agent's force
--- @param technology_name string|nil Technology name to validate
--- @param agent_id number|nil Optional agent_id to get the agent's force
--- @return boolean True if technology exists in agent's force, false otherwise
function M.validate_technology(technology_name, agent_id)
    if technology_name == nil then return false end
    if type(technology_name) ~= "string" or technology_name == "" then return false end

    -- If agent_id is provided, validate against the agent's force
    if agent_id ~= nil and type(agent_id) == "number" then
        -- Get agent's force from storage
        if storage and storage.agent_forces then
            local force_name = storage.agent_forces[agent_id]
            if force_name and game and game.forces then
                local force = game.forces[force_name]
                if force and force.technologies then
                    local technology = force.technologies[technology_name]
                    return technology ~= nil
                end
            end
        end

        -- Fallback: try to get agent entity and use its force
        if storage and storage.agents then
            local agent = storage.agents[agent_id]
            if agent and agent.valid and agent.force then
                local technology = agent.force.technologies[technology_name]
                return technology ~= nil
            end
        end
    end

    -- Fallback: if agent_id not available or validation failed, just check it's a non-empty string
    -- (This allows validation to work in contexts where game/agent isn't available)
    return true
end

function M.triple_print(print_str)
    game.print(print_str)
    log(print_str)
    rcon.print(print_str)
end

-- SCHEMA-DRIVEN FLATTENING UTILITIES -----------------------------------------

function M.blueprint_to_table(blueprint_string)
    local version = string.sub(blueprint_string, 1, 1)
    local body = string.sub(blueprint_string, 2)
    local json_str = helpers.decode_string(body)
    if not json_str then return nil end
    local output = helpers.json_to_table(json_str)
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
