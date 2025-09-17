--- factorio_verse/core/game_state/EntitiesGameState.lua
--- EntitiesGameState sub-module for managing entity-related functionality.

local GameStateError = require("core.Error")

--- @class ResearchGameState
--- @field parent GameState
local ResearchGameState = {}
ResearchGameState.__index = ResearchGameState

--- @param parent GameState
--- @return ResearchGameState
function ResearchGameState:new(parent)
    local instance = {
        parent = parent
    }

    setmetatable(instance, self)
    return instance
end

function ResearchGameState:save_research(agent_id, research_id)
    local player = storage.agent_characters[agent_id]
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

function ResearchGameState:get_entity_at_position(position)
    local surface = self.parent:get_surface()
    if not surface then
        return nil, GameStateError:new("No surface available")
    end

    local entities = surface.find_entities_filtered {
        position = position
    }
    return entities[1]
end

function ResearchGameState:can_place_entity(entity_name, position)
    local surface = self.parent:get_surface()
    if not surface then
        return false, GameStateError:new("No surface available")
    end

    return surface.can_place_entity {
        name = entity_name,
        position = position
    }
end

function ResearchGameState:to_json()
    return {
        -- Placeholder for entities data
    }
end

return ResearchGameState
