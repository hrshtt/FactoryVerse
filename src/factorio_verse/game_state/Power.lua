--- factorio_verse/core/game_state/PowerGameState.lua
--- PowerGameState sub-module for managing power-related functionality.
--- Static module - no instantiation required.

-- Module-level local references for global lookups (performance optimization)
-- (This module currently doesn't use many globals, but kept for consistency)

local GameStateError = require("types.Error")

local M = {}

function M.get_power_production()
    -- Placeholder for power production logic
    return 0
end

function M.get_power_consumption()
    -- Placeholder for power consumption logic
    return 0
end

function M.get_power_networks()
    -- Placeholder for power network analysis
    return {}
end

function M.inspect_power()
    rcon.print(helpers.table_to_json({
        production = M.get_power_production(),
        consumption = M.get_power_consumption(),
        networks = M.get_power_networks()
    }))
end

M.admin_api = {
    inspect_power = M.inspect_power,
}

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
        nth_tick = {}
    }
end

--- Register remote interface for power admin methods
--- @return table Remote interface table
function M.register_remote_interface()
    return M.admin_api
end

return M
