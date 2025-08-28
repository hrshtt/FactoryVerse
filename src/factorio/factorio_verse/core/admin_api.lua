local GameState = require("core.game_state.GameState")

local M = {}
M.helpers = {}

M.helpers.create_agent_characters = function(num_agents, destroy_existing)
    return GameState:new():agent():create_agent_characters(num_agents, destroy_existing)
end

M.load_helpers = function()
    remote.add_interface("helpers", M.helpers)
end

return M