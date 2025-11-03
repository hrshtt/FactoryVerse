local GameState = require("core.game_state.GameState")

--- @param params table
--- @return boolean
local function validate_agent(params)
    if params.agent_id then
        local game_state = GameState:new()
        local agent = game_state.agent:get_agent(params.agent_id)
        if not agent then
            error("Agent '" .. tostring(params.agent_id) .. "' not found")
        end
        -- if agent.state ~= "idle" then
        --     error("Agent '" .. tostring(params.agent_id) .. "' is not idle")
        -- end
    end
    return true
end

return { validate_agent }
