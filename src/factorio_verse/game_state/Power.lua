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

M.on_demand_snapshots = { inspect_power = M.inspect_power }
M.admin_api = {
    inspect_power = M.inspect_power,
}

return M
