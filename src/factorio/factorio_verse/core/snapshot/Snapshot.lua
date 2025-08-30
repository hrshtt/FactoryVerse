local GameState = require "core.game_state.GameState":new()

local Snapshot = {}

Snapshot.game_state = GameState

function Snapshot.new()
    return {
        game_state = Snapshot.game_state,
    }
end

return Snapshot