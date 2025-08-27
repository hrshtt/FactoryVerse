--- factorio_verse/core/game_state/AgentGameState.lua
--- AgentGameState sub-module for managing agent-related functionality.

local GameStateError = require("factorio_verse.core.Error")

--- @class AgentGameState
--- @field game_state GameState
--- @field agent_id number
--- @field player table
local AgentGameState = {}
AgentGameState.__index = AgentGameState

local agent_inventory_type = defines.inventory.character_main

function AgentGameState:new(game_state, agent_id)
    local instance = {
        game_state = game_state,
        agent_id = agent_id or 1,
        player = nil
    }
    
    if game and game.players[agent_id] then
        instance.player = game.players[agent_id]
    end
    
    setmetatable(instance, self)
    return instance
end

function AgentGameState:create_agent(agent_id, position)
    if not position then
        position = {x = 0, y = (agent_id - 1) * 2}
    end
    
    local surface = self.game_state.game.surfaces[1]
    if not surface then
        return nil, GameStateError:new("No surface available for agent creation")
    end
    
    local char = surface.create_entity{
        name = "character",
        position = position,
        force = game.forces.player
    }
    return char
end

--- @param agent_id number
--- @return LuaEntity
function AgentGameState:get_agent(agent_id)
    agent_id = agent_id or self.agent_id
    return global.agent_characters[agent_id]
end

--- @param agent_id number
--- @param radius number
--- @param filter string
--- @return table<LuaEntity>|GameStateError
function AgentGameState:get_surrounding_entities(agent_id, radius, filter)
    local agent = self:get_agent(agent_id)
    if not agent then
        return GameStateError:new("Agent not found", {agent_id = agent_id})
    end

    local area = {
        {agent.position.x - radius, agent.position.y - radius},
        {agent.position.x + radius, agent.position.y + radius}
    }
    return self.game_state.entities:get_entities_in_area(area, filter)
end

--- @param agent_id number
--- @return table|GameStateError
function AgentGameState:get_inventory_contents(agent_id)
    local agent = self:get_agent(agent_id)
    if not agent then
        return GameStateError:new("Agent not found", {agent_id = agent_id})
    end
    return self.game_state.inventory:get_inventory_contents(agent, agent_inventory_type)
end

function AgentGameState:check_item_in_inventory(agent_id, item_name)
    local agent = self:get_agent(agent_id)
    if not agent then
        return GameStateError:new("Agent not found", {agent_id = agent_id})
    end

    return self.game_state.inventory:check_item_in_inventory(agent, item_name, agent_inventory_type)
end

function AgentGameState:set_players_to_spectator()
    -- Remove connected player characters and make them viewers only
    for _, player in pairs(game.connected_players) do
        player.set_controller({type = defines.controllers.spectator})
    end
end

function AgentGameState:to_json()
    return {
        agent_id = self.agent_id,
        player_position = self.player and self.player.position or nil,
        player_force = self.player and self.player.force.name or nil
    }
end

return AgentGameState
