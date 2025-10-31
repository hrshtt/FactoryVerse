--- factorio_verse/core/game_state/AgentGameState.lua
--- AgentGameState sub-module for managing agent-related functionality.

local GameStateError = require("core.Error")
local utils = require("utils")
local MapDiscovery = require("core.MapDiscovery")

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

    if i == 0 then
        r, g, b = v, t, p
    elseif i == 1 then
        r, g, b = q, v, p
    elseif i == 2 then
        r, g, b = p, v, t
    elseif i == 3 then
        r, g, b = p, q, v
    elseif i == 4 then
        r, g, b = t, p, v
    elseif i == 5 then
        r, g, b = v, p, q
    end

    return { r = r, g = g, b = b, a = 1.0 }
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

--- @param game_state GameState
--- @return AgentGameState
function AgentGameState:new(game_state)
    local instance = {
        game_state = game_state,
        -- agent_id = agent_id or 1
    }

    setmetatable(instance, self)
    return instance
end

-- Lazy getter for player
function AgentGameState:player()
    if not self._player then
        local g = game
        if g and g.players[self.agent_id] then
            self._player = g.players[self.agent_id]
        end
    end
    return self._player
end

function AgentGameState:force_destroy_agents()
    -- Destroy all character entities on the surface, excluding those controlled by connected players
    for _, entity in pairs(game.surfaces[1].find_entities_filtered { name = "character" }) do
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
        position = { x = 0, y = (agent_id - 1) * 2 }
    end

    local surface = game.surfaces[1]
    local char = surface.create_entity {
        name = "character",
        position = position,
        force = game.forces.player,
        color = color
    }
    -- Chart the starting area (safe now - doesn't force sync chunk generation)
    utils.chart_native_start_area(surface, g.forces.player, position, self.game_state)
    -- Initialize map discovery for ongoing discovery
    MapDiscovery.initialize(surface, g.forces.player, position)
    return char
end

--- @param agent_id number
--- @return LuaEntity|nil
function AgentGameState:get_agent(agent_id)
    agent_id = agent_id or self.agent_id
    if not storage.agent_characters then
        storage.agent_characters = {}
        return nil
    end
    local agent = storage.agent_characters[agent_id]
    -- Clean up invalid references (can happen when loading saves)
    if agent and not agent.valid then
        storage.agent_characters[agent_id] = nil
        return nil
    end
    return agent
end

--- @param num_agents number
--- @param destroy_existing boolean|nil
--- @return table agents created
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

    local created_agents = {}
    for i = 1, num_agents do
        log("Creating agent character " .. i .. " of " .. num_agents)
        position = { x = 0, y = (i - 1) * 2 }
        local char = self:create_agent(i, position, generate_agent_color(i, num_agents))
        storage.agent_characters[i] = char
        table.insert(created_agents, char)
    end
    return created_agents
end

--- @param agent_id number
--- @param radius number
--- @param filter string
--- @return table<LuaEntity>|GameStateError
function AgentGameState:get_surrounding_entities(agent_id, radius, filter)
    local agent = self:get_agent(agent_id)
    if not agent then
        return GameStateError:new("Agent not found", { agent_id = agent_id })
    end

    local area = {
        { agent.position.x - radius, agent.position.y - radius },
        { agent.position.x + radius, agent.position.y + radius }
    }
    return self.game_state:entities():get_entities_in_area(area, filter)
end

--- @param agent_id number
--- @return table|GameStateError
function AgentGameState:get_inventory_contents(agent_id)
    local agent = self:get_agent(agent_id)
    if not agent then
        return GameStateError:new("Agent not found", { agent_id = agent_id })
    end
    return self.game_state:inventory():get_inventory_contents(agent, agent_inventory_type)
end

function AgentGameState:check_item_in_inventory(agent_id, item_name)
    local agent = self:get_agent(agent_id)
    if not agent then
        return GameStateError:new("Agent not found", { agent_id = agent_id })
    end

    return self.game_state:inventory():check_item_in_inventory(agent, item_name, agent_inventory_type)
end

function AgentGameState:to_json()
    local player = self:player()
    return {
        agent_id = self.agent_id,
        player_position = player and player.position or nil,
        player_force = player and player.force.name or nil
    }
end

-- Internal helper to fetch the agent's LuaEntity (character)
local function _get_control_for_agent(agent_id)
    local agents = storage.agent_characters
    if agents and agents[agent_id] and agents[agent_id].valid then
        return agents[agent_id]
    end
    return nil
end

-- Hard exclusivity policy: only one activity active at a time for stability
-- Stop all walking-related activities (intents and immediate walking state)
function AgentGameState:stop_walking(agent_id)
    agent_id = agent_id or self.agent_id
    -- Clear sustained intents
    if storage.walk_intents then
        storage.walk_intents[agent_id] = nil
    end
    -- Stop walking immediately on the entity
    local control = _get_control_for_agent(agent_id)
    if control and control.valid then
        local current_dir = (control.walking_state and control.walking_state.direction) or defines.direction.north
        control.walking_state = { walking = false, direction = current_dir }
    end
end

-- Start or stop walking for this tick. Enforces exclusivity with mining when starting.
function AgentGameState:set_walking(agent_id, direction, walking)
    agent_id = agent_id or self.agent_id
    local control = _get_control_for_agent(agent_id)
    if not (control and control.valid) then return end
    -- If starting to walk, stop mining per exclusivity policy
    if walking then
        if control.mining_state and control.mining_state.mining then
            control.mining_state = { mining = false }
        end
    end
    -- Apply walking state
    local dir = direction or (control.walking_state and control.walking_state.direction) or defines.direction.north
    control.walking_state = { walking = (walking ~= false), direction = dir }
end

-- Sustain walking for a number of ticks; immediately applies for current tick as well
function AgentGameState:sustain_walking(agent_id, direction, ticks)
    agent_id = agent_id or self.agent_id
    if not ticks or ticks <= 0 then return end
    storage.walk_intents = storage.walk_intents or {}
    local end_tick = (game and game.tick or 0) + ticks
    storage.walk_intents[agent_id] = {
        direction = direction,
        end_tick = end_tick,
        walking = true
    }
    -- Immediate apply this tick
    self:set_walking(agent_id, direction, true)
end

-- Clear any sustained walking intent for the agent, without changing walk_to jobs
function AgentGameState:clear_walking_intent(agent_id)
    agent_id = agent_id or self.agent_id
    if storage.walk_intents then
        storage.walk_intents[agent_id] = nil
    end
end

-- Cancel any active walk_to jobs for the agent (without touching walking intents)
function AgentGameState:cancel_walk_to(agent_id)
    agent_id = agent_id or self.agent_id
    if not storage.walk_to_jobs then return end
    for id, job in pairs(storage.walk_to_jobs) do
        if job and job.agent_id == agent_id then
            storage.walk_to_jobs[id] = nil
        end
    end
end

-- Start/stop mining on the entity; when starting, enforce exclusivity by stopping walking
-- target may be a position {x,y} or an entity with .position
function AgentGameState:set_mining(agent_id, mining, target)
    agent_id = agent_id or self.agent_id
    local control = _get_control_for_agent(agent_id)
    if not (control and control.valid) then return end
    if mining then
        -- Exclusivity: stop any walking and walk_to jobs
        self:stop_walking(agent_id)
        local pos = target and (target.position or target) or nil
        -- When a specific entity is provided, prefer explicit target entity
        local ent = (target and target.valid == true and target) or nil
        if pos then
            control.mining_state = { mining = true, position = { x = pos.x, y = pos.y }, entity = ent }
        else
            control.mining_state = { mining = true, entity = ent }
        end
    else
        control.mining_state = { mining = false }
    end
end

-- Transient selection handling ------------------------------------------------
function AgentGameState:set_selected(agent_id, selected)
    agent_id = agent_id or self.agent_id
    storage.agent_selection = storage.agent_selection or {}
    storage.agent_selection[agent_id] = selected
end

function AgentGameState:get_selected(agent_id)
    agent_id = agent_id or self.agent_id
    return storage.agent_selection and storage.agent_selection[agent_id] or nil
end

function AgentGameState:clear_selected(agent_id)
    agent_id = agent_id or self.agent_id
    if storage.agent_selection then
        storage.agent_selection[agent_id] = nil
    end
end

return AgentGameState
