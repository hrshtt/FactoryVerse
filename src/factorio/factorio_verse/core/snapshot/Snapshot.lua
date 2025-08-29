local GameState = require "core.game_state.GameState":new()

local Snapshot = {}

function Snapshot.new()
    return {
        game_state = GameState,
    }
end

function Snapshot.create_snapshot()
    return {
        game_state = GameState,
    }
end

return Snapshot