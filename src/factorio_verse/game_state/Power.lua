--- factorio_verse/core/game_state/PowerGameState.lua
--- PowerGameState sub-module for managing power-related functionality.
--- Static module - no instantiation required.

-- Module-level local references for global lookups (performance optimization)
-- (This module currently doesn't use many globals, but kept for consistency)

local GameStateError = require("utils.Error")

local snapshot = require("utils.snapshot")

local M = {}

function M.get_global_power_statistics()
    local surface = game.surfaces[1]
    if not surface.global_electric_network_statistics then
        surface.create_global_electric_network()
    end

    stats = surface.global_electric_network_statistics

    -- Placeholder for power production logic
    return {input = stats.input_counts, output = stats.output_counts, storage = stats.storage_counts}
end

function M._on_nth_tick_global_power_snapshot()
    local stats = M.get_global_power_statistics()
    if not stats then return end

    -- Append a snapshot entry in JSONL format
    local entry = {
        tick = game.tick,
        statistics = stats
    }
    local json_line = helpers.table_to_json(entry) .. "\n"
    helpers.write_file(
        snapshot.SNAPSHOT_BASE_DIR .. "/global_power_statistics.jsonl",
        json_line,
        true -- append
        -- for_player omitted (server/global)
    )
end

M.power_api = {}

--- Get on_tick handlers
--- @return table Array of handler functions
function M.get_on_tick_handlers()
    return {}
end

--- Get events (defined events and nth_tick)
--- @return table {defined_events = {}, nth_tick = {}}
function M.get_events()
    return {
        defined_events = {},
        nth_tick = {[300] = M._on_nth_tick_global_power_snapshot}
    }
end

--- Register remote interface for power admin methods
--- @return table Remote interface table
function M.register_remote_interface()
    return M.power_api
end

return M
