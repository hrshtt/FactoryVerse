local Config = require("core.Config")
local utils = require("utils")

local M = {}
M.__index = M

function M:new(game_state)
    local instance = {
        game_state = game_state
    }
    setmetatable(instance, self)
    return instance
end

function M:get_charted_chunks(sort_by_distance)
    local surface = game.surfaces[1]
    local force = self:get_player_force()
    local charted_chunks = {}
    local generated_count = 0

    if not (surface and force) then
        return charted_chunks
    end

    -- ========================================================================
    -- SOURCE 1: PLAYER-CHARTED CHUNKS (Primary method - most reliable)
    -- ========================================================================
    -- Try to get chunks charted by LuaPlayer characters via force.is_chunk_charted()
    -- This works reliably on:
    --   - Saves where players have explored the map
    --   - Any server with connected LuaPlayer characters
    -- This does NOT work reliably on:
    --   - Headless servers with no connected players (known Factorio limitation)
    --   - force.chart() called but is_chunk_charted() still returns false
    for chunk in surface.get_chunks() do
        generated_count = generated_count + 1
        if force.is_chunk_charted(surface, chunk) then
            table.insert(charted_chunks, { x = chunk.x, y = chunk.y, area = chunk.area })
        end
    end

    -- ========================================================================
    -- SOURCE 2: AGENT-TRACKED CHUNKS (Fallback - headless servers)
    -- ========================================================================
    -- If is_chunk_charted() returned empty, fall back to manually registered areas
    -- This is populated by:
    --   - MapDiscovery:scan_and_discover() (on agent movement)
    --   - MapDiscovery.initialize() (on initial setup)
    -- We explicitly call gs:register_charted_area() because LuaEntity agents
    -- don't auto-chart chunks like LuaPlayer does
    if #charted_chunks == 0 and storage.registered_charted_areas then
        for _, chunk_data in pairs(storage.registered_charted_areas) do
            if chunk_data then
                -- Reconstruct area for registered chunk
                local area = {
                    left_top = { x = chunk_data.x * 32, y = chunk_data.y * 32 },
                    right_bottom = { x = (chunk_data.x + 1) * 32, y = (chunk_data.y + 1) * 32 }
                }
                table.insert(charted_chunks, { x = chunk_data.x, y = chunk_data.y, area = area })
            end
        end
    end

    if sort_by_distance == true then
        utils.sort_coordinates_by_distance(charted_chunks)
    end

    return charted_chunks
end

-- Returns chunk coordinates from a position object using Factorio's logic (same as LuaSurface::get_chunk_position)
-- See: https://lua-api.factorio.com/latest/LuaSurface.html#LuaSurface.get_chunk_position
function M:to_chunk_coordinates(position)
    -- position may be {x=..., y=...} or {1=..., 2=...}, prefer .x/.y
    local x = position.x or position[1]
    local y = position.y or position[2]
    local chunk_x = math.floor(x / 32)
    local chunk_y = math.floor(y / 32)
    return { x = chunk_x, y = chunk_y }
end

--- Prints to rcon (as JSON string) or writes to a file the comprehensive state of the map area.
--- This module SHOULD NOT own all the logic; it is a wrapper around helpers exposed by Entities.lua, Inventory.lua, and Resources.lua.
--- Note: This operation is likely to be very heavy.
--- 
--- POSSIBLE SOLUTION: Blueprint logic (e.g., using LuaSurface.create_blueprint or LuaPlayer.can_place_blueprint) might be leveraged to encode/decode map state,
--- but Factorio has hard and soft limits for blueprints:
---   - A blueprint can have no more than 10,000 entities and 10,000 tiles (hard limit; see LuaBlueprintEntity and LuaTile).
---   - Attempting to create blueprints larger than this will fail or be capped; for reference see https://lua-api.factorio.com/latest/LuaBlueprintEntity.html and relevant forum discussions.
--- For comprehensive map state exceeding blueprint limits, chunked or streamed approaches are required; avoid trying to handle large areas as a single blueprint.
function M:get_map_area_state(bounding_box)
end

--- set the state of the map area, state is a JSON string
function M:set_map_area_state(bounding_box, state)
end

function M:clear_map_area(bounding_box)
end

function M:track_chunk_charting()
end

M.admin_api = {
    get_charted_chunks = M.get_charted_chunks,
    get_map_area_state = M.get_map_area_state,
    set_map_area_state = M.set_map_area_state,
    clear_map_area = M.clear_map_area,
}

M.event_based_snapshot = {
    nth_tick = {
        [60] = function(event)
            M:track_chunk_charting()
        end,
    }
}

return M