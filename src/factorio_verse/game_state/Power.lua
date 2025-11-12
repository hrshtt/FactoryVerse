--- factorio_verse/core/game_state/PowerGameState.lua
--- PowerGameState sub-module for managing power-related functionality.

-- Module-level local references for global lookups (performance optimization)
-- (This module currently doesn't use many globals, but kept for consistency)

local GameStateError = require("types.Error")

--- @class PowerGameState
--- @field parent GameState
--- @field on_demand_snapshots table
--- @field admin_api table
local M = {}
M.__index = M

function M:new(parent)
    local instance = {
        parent = parent
    }
    
    setmetatable(instance, self)
    return instance
end

function M:get_power_production()
    -- Placeholder for power production logic
    return 0
end

function M:get_power_consumption()
    -- Placeholder for power consumption logic
    return 0
end

function M:get_power_networks()
    -- Placeholder for power network analysis
    return {}
end

function M:inspect_power()
    rcon.print(helpers.table_to_json({
        production = self:get_power_production(),
        consumption = self:get_power_consumption(),
        networks = self:get_power_networks()
    }))
end

M.on_demand_snapshots = { inspect_power = M.inspect_power }
M.admin_api = {
    inspect_power = M.inspect_power,
}

return M
