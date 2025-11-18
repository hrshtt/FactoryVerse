--- factorio_verse/core/game_state/ResearchGameState.lua
--- ResearchGameState sub-module for managing research-related functionality.
--- Static module - no instantiation required.

local GameStateError = require("utils.Error")

local M = {}

function M.reset_research(agent_id)
    if not storage.agents[agent_id] or not storage.agents[agent_id].entity.valid then
        return {
            error = "Agent not found or invalid",
        }
    end

    local agent = storage.agents[agent_id] ---@type Agent

    local force = agent.entity.force
    force.cancel_current_research()
    force.reset_technology_effects()
    force.reset_technologies()
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
