local ValidatorRegistry = require("core.action.ValidatorRegistry")
local GameState = require("core.game_state.GameState")

local validator_registry = ValidatorRegistry:new()

--- @param params table
--- @return boolean
local function validate_agent(params)
    if params.agent_id then
        local game_state = GameState:new()
        local agent = game_state:agent():get_agent(params.agent_id)
        if not agent then
            error("Agent '" .. tostring(params.agent_id) .. "' not found")
        end
        -- if agent.state ~= "idle" then
        --     error("Agent '" .. tostring(params.agent_id) .. "' is not idle")
        -- end
    end
    return true
end

validator_registry:register("*", validate_agent)

return validator_registry
