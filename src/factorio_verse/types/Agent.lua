--- Agent table structure stored in storage.agents[agent_id]
--- @class Agent
--- @field entity LuaEntity Character entity for the agent
--- @field force_name string Force name (access force via entity.force)
--- @field labels AgentLabels Rendering labels for the agent
--- @field walking_state AgentWalkingState|nil Agent state information
--- @field mining_state AgentMiningState|nil Agent state information
--- @field crafting_state AgentCraftingState|nil Agent state information
--- @field placement_state AgentPlacementState|nil Agent state information
--- @field charted_chunks AgentChartedChunks|nil Agent state information
--- @field agent_id number Agent ID
--- @field _create function Create a new agent table structure
--- @field exists function Whether the agent exists
--- @field get_entity function Get the entity for the agent
--- @field destroy function Destroy the agent

--- @class AgentLabels : table
--- @field main_tag LuaRenderObject Main name tag rendering object
--- @field map_marker LuaRenderObject Map marker rendering object
--- @field map_tag LuaRenderObject Map tag rendering object

--- @class AgentWalkingState : table
--- @field walking_intents table|nil Walking intent state
--- @field walking_progress table|nil Walking progress tracking

--- @class AgentMiningState : table
--- @field mining_progress table|nil Mining progress tracking
--- @field mining_results table|nil Mining results state

--- @class AgentCraftingState : table
--- @field crafting_progress table|nil Crafting progress tracking

--- @class AgentPlacementState : table
--- @field place_in_line_progress table|nil Place in line progress tracking

--- List of charted chunk {x:number, y:number} coordinates
--- @class AgentChartedChunks : table[]

local utils = require("utils.utils")

local Agent = {}

--- Create a new agent table structure
--- @param agent_id number
--- @param color table|nil
--- @param force_name string|nil
--- @param spawn_position table|nil
--- @return Agent
function Agent:new(agent_id, color, force_name, spawn_position)

    local instance = {
        agent_id = agent_id,
    }

    setmetatable(instance, self)

    local agents = storage.agents or {}
    if agents[agent_id] then
        return instance
    end
    
    agents[agent_id] = self:_create(color, force_name, spawn_position)
    return instance
end

--- Create or get a force by name, setting default friendly relationships
--- @param force_name string Force name
--- @return LuaForce
function Agent:create_or_get_force(force_name)
    if not force_name or force_name == "" then
        error("Force name cannot be empty")
    end

    local force = game.forces[force_name]
    if not force then
        force = game.create_force(force_name)

        -- Set default friendly relationships with player force and all existing agent forces
        local player_force = game.forces.player
        if player_force then
            force.set_friend(player_force, true)
            player_force.set_friend(force, true)
        end

        -- Set friendly with all existing agent forces
        if storage.agents then
            for _, agent_table in pairs(storage.agents) do
                if agent_table and agent_table.force_name and agent_table.force_name ~= force_name then
                    local existing_force = game.forces[agent_table.force_name]
                    if existing_force then
                        force.set_friend(existing_force, true)
                        existing_force.set_friend(force, true)
                    end
                end
            end
        end
    end

    return force
end

--- @param color table|nil
--- @param force_name string|nil Optional force name (if nil, uses agent-{agent_id})
--- @param spawn_position table|nil Optional spawn position (if nil, uses force spawn position)
--- @return Agent
function Agent:_create(color, force_name, spawn_position)
    -- Determine force name
    local final_force_name = force_name
    if not final_force_name then
        final_force_name = "agent-" .. tostring(self.agent_id)
    end

    -- Create or get force
    local force = self:create_or_get_force(final_force_name)
    local name_tag = "Agent-" .. tostring(self.agent_id)

    local surface = game.surfaces[1]
    -- Find non-colliding position for character placement

    local spawn_position = spawn_position or force.get_spawn_position(surface)
    local safe_position = surface.find_non_colliding_position("character", spawn_position, 10, 2)

    local char_entity = surface.create_entity {
        name = "character",
        position = safe_position or spawn_position,
        force = force
    }

    if not char_entity or not char_entity.valid then
        error("Failed to create character for agent " .. tostring(self.agent_id))
    end
    if color then
        char_entity.color = color
    end


    char_entity.name_tag = name_tag
    -- Render name tag for regular gameplay visibility (name_tag only works in editor mode)
    local map_tag = rendering.draw_text {
        text = name_tag,
        target = char_entity,
        surface = char_entity.surface,
        color = { r = 1, g = 1, b = 1, a = 1 },
        scale = 1.2,
        font = "default-game",
        alignment = "center",
        vertical_alignment = "middle"
    }
    -- Create circle marker on map
    local mini_map_marker = rendering.draw_circle {
        color = char_entity.color,
        radius = 2.5,
        filled = true,
        target = char_entity,
        surface = char_entity.surface,
        render_mode = "chart",
        scale_with_zoom = true
    }
    -- Create text label on map
    local mini_map_tag = rendering.draw_text {
        text = name_tag,
        surface = char_entity.surface,
        target = char_entity,
        color = { r = 1, g = 1, b = 1 },
        scale = 1,
        alignment = "left",
        vertical_alignment = "middle",
        render_mode = "chart",
        scale_with_zoom = true
    }

    --- @type Agent
    local agent = {
        entity = char_entity,
        force_name = final_force_name,
        labels = {
            main_tag = map_tag,
            map_marker = mini_map_marker,
            map_tag = mini_map_tag
        },
    }
    return agent
end

--- Check if agent exists
--- @param raise_error boolean|nil Default false
--- @return boolean
function Agent:exists(raise_error)
    local exists = storage.agents ~= nil and storage.agents[self.agent_id] ~= nil
    if raise_error and not exists then
        error("Agent " .. tostring(self.agent_id) .. " not found")
    end
    return exists
end

--- Get agent table
--- @return Agent|nil
function Agent:get_agent()
    if not self:exists(true) then return end
    return storage.agents[self.agent_id]
end

--- Get the entity for an agent
--- @return LuaEntity|nil
function Agent:get_entity()
    if not self:exists(true) then return end
    return self:get_agent().entity
end

function Agent:destroy(remove_force)
    remove_force = remove_force or false
    local agent = self:get_agent()
    if not agent then error("Agent " .. tostring(self.agent_id) .. " not found") end
    agent.entity.destroy()
    if agent.labels.main_tag then
        agent.labels.main_tag.destroy()
    end
    if agent.labels.map_marker then
        agent.labels.map_marker.destroy()
    end
    if agent.labels.map_tag then
        agent.labels.map_tag.destroy()
    end
    local agent_force = game.forces[agent.force_name]
    if agent_force and remove_force then
        game.merge_forces(agent_force, game.forces.player)
    end
    storage.agents[self.agent_id] = nil
    return true
end

function Agent:merge_force(destination_force)
    if not self:exists(true) then return end
    local agent = self:get_agent()
    if not game.forces[destination_force] then
        error("Force " .. tostring(destination_force) .. " not found")
    end
    game.merge_forces(agent.force_name, destination_force)
    return true
end


-- Hard exclusivity policy: only one activity active at a time for stability
-- Stop all walking-related activities (intents and immediate walking state)
function Agent:stop_walking(agent_id)
    -- Clear sustained intents
    if storage.walk_intents then
        storage.walk_intents[agent_id] = nil
    end
    -- Stop walking immediately on the entity
    local entity = self:get_entity()
    if entity and entity.valid then
        local current_dir = (entity.walking_state and entity.walking_state.direction) or defines.direction.north
        entity.walking_state = { walking = false, direction = current_dir }
    end
end

-- Start or stop walking for this tick. Enforces exclusivity with mining when starting.
function Agent:set_walking(direction, walking)
    local entity = self:get_entity()
    if not (entity and entity.valid) then return end
    -- If starting to walk, stop mining per exclusivity policy
    if walking then
        if entity.mining_state and entity.mining_state.mining then
            entity.mining_state = { mining = false }
        end
    end
    -- Apply walking state
    local dir = direction or (entity.walking_state and entity.walking_state.direction) or defines.direction.north
    entity.walking_state = { walking = (walking ~= false), direction = dir }
end

-- Sustain walking for a number of ticks; immediately applies for current tick as well
function Agent:sustain_walking(direction, ticks)
    if not ticks or ticks <= 0 then return end
    storage.walk_intents = storage.walk_intents or {}
    -- Access game.tick directly when function runs (available during runtime)
    local end_tick = (game and game.tick or 0) + ticks
    storage.walk_intents[self.agent_id] = {
        direction = direction,
        end_tick = end_tick,
        walking = true
    }
    -- Immediate apply this tick
    self:set_walking(direction, true)
end

-- Clear any sustained walking intent for the agent, without changing walk_to jobs
function Agent:clear_walking_intent()
    if not self:exists(true) then return end
    if storage.walk_intents then
        storage.walk_intents[self.agent_id] = nil
    end
end

--- Cancel any active walk_to jobs for the agent (without touching walking intents)
function Agent:cancel_walk_to(agent_id)
    if not self:exists(true) then return end
    if self.walking then
        self.walking:cancel_walk_to(self.agent_id)
    end
end

-- Start/stop mining on the entity; when starting, enforce exclusivity by stopping walking
-- target may be a position {x,y} or an entity with .position
function Agent:set_mining(mining, target)
    local entity = self:get_entity()
    if not (entity and entity.valid) then return end
    if mining then
        -- Exclusivity: stop any walking and walk_to jobs
        self:stop_walking()
        local pos = target and (target.position or target) or nil
        if pos then
            entity.mining_state = { mining = true, position = { x = pos.x, y = pos.y } }
        else
            entity.mining_state = { mining = true }
        end
        -- Set selected entity if target is an entity (required for zombie characters)
        if target and target.valid == true then
            entity.selected = target
        end
    else
        entity.mining_state = { mining = false }
    end
end


return Agent
