--- factorio_verse/core/game_state/ResearchGameState.lua
--- ResearchGameState sub-module for managing research-related functionality.
--- Static module - no instantiation required.

local GameStateError = require("utils.Error")

local M = {}

function M.save_research(agent_id, research_id)
    local player = storage.agents[agent_id]
    local force = player.force

    local research_state = {
        technologies = {},
        current_research = nil,
        research_progress = 0,
        research_queue = {},
        progress = {}
    }

    -- Save all technology states
    -- for name, tech in pairs(force.technologies) do
    --     research_state.technologies[name] = serialize_technology(tech)
    -- end

    -- Save current research and progress
    if force.current_research then
        research_state.current_research = "\"" .. force.current_research.name .. "\""
        research_state.research_progress = force.research_progress

        research_state.progress[force.current_research.name] = force.research_progress or 0
    end

    -- Save research queue if it exists
    if force.research_queue then
        for _, tech in pairs(force.research_queue) do
            table.insert(research_state.research_queue, "\"" .. tech.name .. "\"")
        end
    end
    return research_state
end

function M.reset_research(input)
    local agent_id = input.agent_id
    local player = storage.agents[agent_id]
    local force = player.force
    force.cancel_current_research()
    force.research_queue = {}
    force.research_progress = 0
end

function M.inspect_research(agent_id)
end

M.admin_api = {
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
    return M.admin_api
end

return M
