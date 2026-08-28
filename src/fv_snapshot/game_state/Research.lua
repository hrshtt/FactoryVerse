--- factorio_verse/core/game_state/ResearchGameState.lua
--- ResearchGameState sub-module for managing research-related functionality.
--- Static module - no instantiation required.
---
--- NOTE: fv_embodied_agent has isolated storage. Must use remote.call to access agent data.


local M = {}

--- Reset all research for an agent's force
--- Uses remote.call to access fv_embodied_agent's data (isolated storage)
--- @param agent_id number Agent ID
--- @return table|nil Error table if agent not found
function M.reset_research(agent_id)
    -- Get agent info via remote.call (fv_embodied_agent has isolated storage)
    if not remote.interfaces.agent then
        return { error = "Agent interface not available" }
    end

    local agents = remote.call("agent", "list_agents")
    local agent_info = nil
    if agents then
        for _, info in ipairs(agents) do
            if info.id == agent_id then
                agent_info = info
                break
            end
        end
    end

    if not agent_info then
        return { error = "Agent not found: " .. tostring(agent_id) }
    end

    if not agent_info.entity_valid then
        return { error = "Agent entity is invalid" }
    end

    -- Get the force from the agent's force name
    local force = game.forces[agent_info.force]
    if not force then
        return { error = "Force not found: " .. tostring(agent_info.force) }
    end

    force.cancel_current_research()
    force.reset_technology_effects()
    force.reset_technologies()

    return { success = true, agent_id = agent_id, force = agent_info.force }
end

M.research_api = {
    reset_research = M.reset_research,
    inspect_research = M.inspect_research,
}

--- Get on_tick handlers
--- @return table Array of handler functions
function M.get_on_tick_handlers()
    return {}
end

--- Get events (defined events and nth_tick)
--- @return table {defined_events = {}, nth_tick = {}}
function M.get_events()
    return {
        defined_events = {},
        nth_tick = {}
    }
end

--- Register remote interface for research admin methods
--- @return table Remote interface table
function M.register_remote_interface()
    return M.research_api
end

return M
