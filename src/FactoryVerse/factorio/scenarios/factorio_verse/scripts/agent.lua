local Agent = {}
local errors = require("scripts.errors")


function Agent.get_agent(agent_index)
    local player = game.players[agent_index]
    if not player then
        return errors.agent({}, "Player not found", { agent_index = agent_index })
    end
    return player
end

function Agent.get_inventory(agent_index)
    local player = Agent.get_agent(agent_index)
    if not player then
        return errors.agent({}, "Player not found", { agent_index = agent_index })
    end
    return player.get_inventory(defines.inventory.character_main)
end

return Agent