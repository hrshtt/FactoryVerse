--- factorio_verse/core/game_state/AgentGameState.lua
--- AgentGameState sub-module for managing agent-related functionality.

local GameStateError = require("core.Error")
local utils = require("utils")

--- @param h number
--- @param s number
--- @param v number
--- @return table
local function hsv_to_rgb(h, s, v)
    local r, g, b
    local i = math.floor(h * 6)
    local f = h * 6 - i
    local p = v * (1 - s)
    local q = v * (1 - f * s)
    local t = v * (1 - (1 - f) * s)
    
    i = i % 6
    
    if i == 0 then r, g, b = v, t, p
    elseif i == 1 then r, g, b = q, v, p
    elseif i == 2 then r, g, b = p, v, t
    elseif i == 3 then r, g, b = p, q, v
    elseif i == 4 then r, g, b = t, p, v
    elseif i == 5 then r, g, b = v, p, q
    end
    
    return {r = r, g = g, b = b, a = 1.0}
end

--- @param index number
--- @param total_agents number
--- @return table
local function generate_agent_color(index, total_agents)
    local hue = (index - 1) / total_agents
    local saturation = 1.0
    local value = 1.0
    return hsv_to_rgb(hue, saturation, value)
end

--- @class AgentGameState
--- @field game_state GameState
--- @field agent_id number
--- @field agent_inventory_type string
--- Methods: player()
local AgentGameState = {}
AgentGameState.__index = AgentGameState

local agent_inventory_type = defines.inventory.character_main

function AgentGameState:new(game_state, agent_id)
    local instance = {
        game_state = game_state,
        agent_id = agent_id or 1
    }
    
    setmetatable(instance, self)
    return instance
end

-- Lazy getter for player
function AgentGameState:player()
    if not self._player then
        local g = self.game_state:get_game()
        if g and g.players[self.agent_id] then
            self._player = g.players[self.agent_id]
        end
    end
    return self._player
end

function AgentGameState:force_destroy_agents()

    -- Destroy all character entities on the surface, excluding those controlled by connected players
    for _, entity in pairs(self.game_state:get_surface().find_entities_filtered{ name = "character" }) do
        if entity and entity.valid then
            local associated_player = entity.associated_player
            -- Only destroy if not controlled by a connected player
            if not (associated_player and associated_player.connected) then
                entity.destroy()
            end
        end
    end
    -- Clear the agent_characters table
    storage.agent_characters = {}
end


--- @param agent_id number
--- @param position table
--- @return LuaEntity?
function AgentGameState:create_agent(agent_id, position, color)
    if not position then
        position = {x = 0, y = (agent_id - 1) * 2}
    end
    
    local surface = self.game_state:get_surface()
    local g = self.game_state:get_game()
    local char = surface.create_entity{
        name = "character",
        position = position,
        force = g.forces.player,
        color = color
    }
    utils.chart_native_start_area(surface, g.forces.player, position)
    return char
end

--- @param agent_id number
--- @return LuaEntity
function AgentGameState:get_agent(agent_id)
    agent_id = agent_id or self.agent_id
    if not storage.agent_characters then
        storage.agent_characters = {}
        return nil
    end
    return storage.agent_characters[agent_id]
end

--- @param num_agents number
--- @param destroy_existing boolean|nil
--- @return boolean
function AgentGameState:create_agent_characters(num_agents, destroy_existing)
    if not storage.agent_characters then
        storage.agent_characters = {}
    end
    if destroy_existing and storage.agent_characters then
        for _, char in pairs(storage.agent_characters) do
            if char and char.valid then
                char.destroy()
            end
        end
        storage.agent_characters = {}
    end
    
    for i = 1, num_agents do
        log("Creating agent character " .. i .. " of " .. num_agents)
        position = {x = 0, y = (i - 1) * 2}
        local char = self:create_agent(i, position, generate_agent_color(i, num_agents))
        storage.agent_characters[i] = char
    end
    return true
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
    return self.game_state.entities_state:get_entities_in_area(area, filter)
end

--- @param agent_id number
--- @return table|GameStateError
function AgentGameState:get_inventory_contents(agent_id)
    local agent = self:get_agent(agent_id)
    if not agent then
        return GameStateError:new("Agent not found", {agent_id = agent_id})
    end
    return self.game_state.inventory_state:get_inventory_contents(agent, agent_inventory_type)
end

function AgentGameState:check_item_in_inventory(agent_id, item_name)
    local agent = self:get_agent(agent_id)
    if not agent then
        return GameStateError:new("Agent not found", {agent_id = agent_id})
    end

    return self.game_state.inventory_state:check_item_in_inventory(agent, item_name, agent_inventory_type)
end

function AgentGameState:to_json()
    local player = self:player()
    return {
        agent_id = self.agent_id,
        player_position = player and player.position or nil,
        player_force = player and player.force.name or nil
    }
end

return AgentGameState
