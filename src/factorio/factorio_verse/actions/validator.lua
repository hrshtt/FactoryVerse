local ValidatorRegistry = require("core.action.ValidatorRegistry")
local game_state = require("core.game_state.GameState"):new()

local validator_registry = ValidatorRegistry:new()

--- @param params table
--- @return boolean
local function validate_direction(params)
    if params.agent_id then
        local agent = game_state.agents[params.agent_id]
        if not agent then
            error("Agent '" .. tostring(params.agent_id) .. "' not found")
        end
        -- if agent.state ~= "idle" then
        --     error("Agent '" .. tostring(params.agent_id) .. "' is not idle")
        -- end
    end
    return true
end

validator_registry:register("agent.walk", validate_direction)

return validator_registry
