--- factorio_verse/core/game_state/EntitiesGameState.lua
--- EntitiesGameState sub-module for managing entity-related functionality.

local GameStateError = require("core.Error")

--- @class EntitiesGameState
--- @field game_state GameState
local EntitiesGameState = {}
EntitiesGameState.__index = EntitiesGameState

function EntitiesGameState:new(game_state)
    local instance = {
        game_state = game_state
    }
    
    setmetatable(instance, self)
    return instance
end

--- @param area table
--- @param filter string
--- @return table
function EntitiesGameState:get_entities_in_area(area, filter)
    local surface = self.game_state:get_surface()
    if not surface then
        return {}
    end
    
    local entities = surface.find_entities_filtered{
        area = area,
        type = filter
    }
    return entities
end

function EntitiesGameState:get_entity_at_position(position)
    local surface = self.game_state:get_surface()
    if not surface then
        return GameStateError:new("No surface available")
    end
    
    local entities = surface.find_entities_filtered{
        position = position
    }
    return entities[1]
end

function EntitiesGameState:can_place_entity(entity_name, position)
    local surface = self.game_state:get_surface()
    if not surface then
        return GameStateError:new("No surface available")
    end
    
    return surface.can_place_entity{
        name = entity_name,
        position = position
    }
end

function EntitiesGameState:to_json()
    return {
        -- Placeholder for entities data
    }
end

return EntitiesGameState
