--- @class GameStateModule
--- @field name string
--- @field game_state GameState
--- @field admin_api table<string, function>
--- @field on_demand_snapshots table<string, function>
--- @field disk_write_snapshots table<string, function>
--- @field event_based_snapshots table<string, function>
local GameStateModule = {}

function GameStateModule:new(name, game_state)
    local instance = {
        name = name,
        game_state = game_state,
    }
    setmetatable(instance, self)
    return instance
end

return GameStateModule