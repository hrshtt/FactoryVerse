local GameState = require "core.game_state.GameState"
local utils = require "utils"

--- AgentSnapshot: View module for agent data
--- @class AgentSnapshot
local AgentSnapshot = {}

--- Get agent view data
--- @param agent_id number - agent ID
--- @return table - {agent_id, tick, position_x, position_y, inventory} or {error, agent_id, tick}
function AgentSnapshot.get_agent_view(agent_id)
    local gs = GameState:new()
    local agent = gs:agent_state():get_agent(agent_id)

    if not agent or not agent.valid then
        return {
            error = "Agent not found or invalid",
            agent_id = agent_id,
            tick = game.tick or 0
        }
    end

    local position = agent.position
    if not position then
        return {
            error = "Agent has no position",
            agent_id = agent_id,
            tick = game.tick or 0
        }
    end

    -- Get agent inventory
    local inventory = {}
    local main_inventory = agent.get_main_inventory and agent:get_main_inventory()
    if main_inventory then
        local contents = main_inventory.get_contents()
        if contents and next(contents) ~= nil then
            inventory = contents
        end
    end

    return {
        agent_id = agent_id,
        tick = game.tick or 0,
        position_x = position.x,
        position_y = position.y,
        inventory = inventory
    }
end

return AgentSnapshot
