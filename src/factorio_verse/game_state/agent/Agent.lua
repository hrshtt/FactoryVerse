--- factorio_verse/core/game_state/AgentGameState.lua
--- AgentGameState sub-module for managing agent-related functionality.
--- Core agent management: lifecycle, force management, queries, and control interfaces.
--- Walking and mining logic are delegated to agent/walking.lua and agent/mining.lua.

-- Module-level local references for global lookups (performance optimization)
-- Note: Do not capture 'game' at module level - it may be nil during on_load
-- Access 'game' directly in functions where it's guaranteed to be available
local pairs = pairs
local ipairs = ipairs

local GameStateError = require("core.Error")
local utils = require("utils")
local MapDiscovery = require("core.MapDiscovery")

-- Agent activity modules
local Walking = require("game_state.agent.walking")
local Mining = require("game_state.agent.mining")

--- @param index number
--- @param total_agents number
--- @return table
local function generate_agent_color(index, total_agents)
    local hue = (index - 1) / total_agents
    local saturation = 1.0
    local value = 1.0
    return utils.hsv_to_rgb(hue, saturation, value)
end

--- @class AgentGameState : GameStateModule
--- @field entities EntitiesGameState
--- @field inventory InventoryGameState
--- @field walking WalkingModule
--- @field mining MiningModule
local M = {}
M.__index = M

local agent_inventory_type = defines.inventory.character_main

--- @param game_state GameState
--- @return AgentGameState
function M:new(game_state)
    local instance = {
        game_state = game_state,
        -- Cache frequently-used sibling modules (constructor-level caching for performance)
        entities = game_state.entities,
        inventory = game_state.inventory,
    }

    setmetatable(instance, self)
    
    -- Initialize storage tables for activity state machines
    storage.walk_to_jobs = storage.walk_to_jobs or {}
    storage.mine_resource_jobs = storage.mine_resource_jobs or {}
    storage.walk_intents = storage.walk_intents or {}
    storage.agent_forces = storage.agent_forces or {}
    
    -- Initialize activity modules with control interface
    instance.walking = Walking
    instance.walking:init(instance)  -- Pass self as agent_control interface
    
    instance.mining = Mining
    instance.mining:init(instance, instance.walking)  -- Pass self and walking module
    
    return instance
end

-- ============================================================================
-- AGENT LIFECYCLE MANAGEMENT
-- ============================================================================

function M:force_destroy_agents()
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
    storage.agent_forces = {}
end

--- Create or get a force by name, setting default friendly relationships
--- @param force_name string Force name
--- @return LuaForce
function M:create_or_get_force(force_name)
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
        if storage.agent_forces then
            for _, existing_force_name in pairs(storage.agent_forces) do
                local existing_force = game.forces[existing_force_name]
                if existing_force and existing_force.name ~= force_name then
                    force.set_friend(existing_force, true)
                    existing_force.set_friend(force, true)
                end
            end
        end
    end
    
    return force
end

--- @param agent_id number
--- @param position table
--- @param color table|nil
--- @param force_name string|nil Optional force name (if nil, uses agent-{agent_id})
--- @return LuaEntity? character
--- @return string force_name
function M:create_agent(agent_id, position, color, force_name)
    if not position then
        position = { x = 0, y = (agent_id - 1) * 2 }
    end
    
    -- Determine force name
    local final_force_name = force_name
    if not final_force_name then
        final_force_name = "agent-" .. tostring(agent_id)
    end
    
    -- Create or get force
    local force = self:create_or_get_force(final_force_name)
    
    -- Store force mapping
    storage.agent_forces = storage.agent_forces or {}
    storage.agent_forces[agent_id] = final_force_name

    local surface = game.surfaces[1]
    local char = surface.create_entity {
        name = "character",
        position = position,
        force = force,
        color = color
    }
    -- Chart the starting area (safe now - doesn't force sync chunk generation)
    utils.chart_native_start_area(surface, force, position, self.game_state)
    -- Initialize map discovery for ongoing discovery
    MapDiscovery.initialize(surface, force, position)
    return char, final_force_name
end

--- @param agent_id number
--- @return LuaEntity|nil
function M:get_agent(agent_id)
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
--- @param set_unique_forces boolean|nil Default true - each agent gets unique force
--- @param default_common_force string|nil Force name to use if set_unique_forces=false
--- @return table agents created (array of {character, force_name})
function M:create_agent_characters(num_agents, destroy_existing, set_unique_forces, default_common_force)
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
        storage.agent_forces = {}
    end
    
    -- Determine force strategy
    local use_unique_forces = set_unique_forces ~= false  -- Default true
    
    if not use_unique_forces then
        -- Use common force
        local common_force_name = default_common_force or "agent_force"
        
        -- Verify force exists if provided
        if default_common_force then
            if not game.forces[common_force_name] then
                error("Force '" .. common_force_name .. "' does not exist")
            end
        else
            -- Create default force if it doesn't exist
            self:create_or_get_force(common_force_name)
        end
    end

    local created_agents = {}
    for i = 1, num_agents do
        log("Creating agent character " .. i .. " of " .. num_agents)
        position = { x = 0, y = (i - 1) * 2 }
        
        local force_name = nil
        if use_unique_forces then
            force_name = nil  -- Will auto-generate agent-{agent_id}
        else
            force_name = default_common_force or "agent_force"
        end
        
        local char, final_force_name = self:create_agent(i, position, generate_agent_color(i, num_agents), force_name)
        storage.agent_characters[i] = char
        table.insert(created_agents, {character = char, force_name = final_force_name})
    end
    return created_agents
end

-- ============================================================================
-- AGENT QUERIES
-- ============================================================================

--- @param agent_id number
--- @return table|GameStateError
function M:get_inventory_contents(agent_id)
    local agent = self:get_agent(agent_id)
    if not agent then
        return GameStateError:new("Agent not found", { agent_id = agent_id })
    end
    return self.inventory:get_inventory_contents(agent, agent_inventory_type)
end

function M:check_item_in_inventory(agent_id, item_name)
    local agent = self:get_agent(agent_id)
    if not agent then
        return GameStateError:new("Agent not found", { agent_id = agent_id })
    end

    return self.inventory:check_item_in_inventory(agent, item_name, agent_inventory_type)
end

-- ============================================================================
-- AGENT CONTROL INTERFACE (used by walking and mining modules)
-- ============================================================================

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
function M:stop_walking(agent_id)
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
function M:set_walking(agent_id, direction, walking)
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
function M:sustain_walking(agent_id, direction, ticks)
    if not ticks or ticks <= 0 then return end
    storage.walk_intents = storage.walk_intents or {}
    -- Access game.tick directly when function runs (available during runtime)
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
function M:clear_walking_intent(agent_id)
    if storage.walk_intents then
        storage.walk_intents[agent_id] = nil
    end
end

--- Cancel any active walk_to jobs for the agent (without touching walking intents)
function M:cancel_walk_to(agent_id)
    if self.walking then
        self.walking:cancel_walk_to(agent_id)
    end
end

-- Start/stop mining on the entity; when starting, enforce exclusivity by stopping walking
-- target may be a position {x,y} or an entity with .position
function M:set_mining(agent_id, mining, target)
    local control = _get_control_for_agent(agent_id)
    if not (control and control.valid) then return end
    if mining then
        -- Exclusivity: stop any walking and walk_to jobs
        self:stop_walking(agent_id)
        local pos = target and (target.position or target) or nil
        if pos then
            control.mining_state = { mining = true, position = { x = pos.x, y = pos.y } }
        else
            control.mining_state = { mining = true }
        end
        -- Set selected entity if target is an entity (required for zombie characters)
        if target and target.valid == true then
            control.selected = target
        end
    else
        control.mining_state = { mining = false }
    end
end

-- ============================================================================
-- JOB MANAGEMENT API (delegates to activity modules)
-- ============================================================================

--- Start a walk-to job for an agent
--- @param agent_id number
--- @param goal {x:number, y:number}
--- @param options table|nil Options: arrive_radius, lookahead, replan_on_stuck, max_replans, prefer_cardinal, diag_band, snap_axis_eps
--- @return number|nil job_id
function M:start_walk_to_job(agent_id, goal, options)
    return self.walking:start_walk_to_job(agent_id, goal, options)
end

--- Start a mining job for an agent
--- @param agent_id number
--- @param target {x:number, y:number}
--- @param resource_name string
--- @param max_count number
--- @param options table|nil Options: walk_if_unreachable, debug
--- @return boolean success
function M:start_mining_job(agent_id, target, resource_name, max_count, options)
    return self.mining:start_mining_job(agent_id, target, resource_name, max_count, options)
end

-- ============================================================================
-- EVENT HANDLERS
-- ============================================================================

--- Get activity event handlers (aggregates from walking and mining modules)
--- @return table Event handlers keyed by event ID
function M:get_activity_events()
    local walking_events = self.walking:get_event_handlers(self)
    local mining_events = self.mining:get_event_handlers()
    
    -- Merge event handlers (both walking and mining use on_tick)
    local merged = {}
    
    -- Merge on_tick handlers
    if walking_events[defines.events.on_tick] and mining_events[defines.events.on_tick] then
        merged[defines.events.on_tick] = function(event)
            walking_events[defines.events.on_tick](event)
            mining_events[defines.events.on_tick](event)
        end
    elseif walking_events[defines.events.on_tick] then
        merged[defines.events.on_tick] = walking_events[defines.events.on_tick]
    elseif mining_events[defines.events.on_tick] then
        merged[defines.events.on_tick] = mining_events[defines.events.on_tick]
    end
    
    -- Copy other events
    for event_id, handler in pairs(walking_events) do
        if event_id ~= defines.events.on_tick then
            merged[event_id] = handler
        end
    end
    for event_id, handler in pairs(mining_events) do
        if event_id ~= defines.events.on_tick then
            merged[event_id] = handler
        end
    end
    
    return merged
end

-- ============================================================================
-- FORCE MANAGEMENT
-- ============================================================================

--- Update friendly relationships for an agent's force
--- @param agent_id number
--- @param force_names table<string> Array of force names to set as friendly
function M:update_agent_friends(agent_id, force_names)
    if not storage.agent_forces then
        error("Agent " .. tostring(agent_id) .. " has no force assigned")
    end
    local agent_force_name = storage.agent_forces[agent_id]
    if not agent_force_name then
        error("Agent " .. tostring(agent_id) .. " has no force assigned")
    end
    
    local agent_force = game.forces[agent_force_name]
    if not agent_force then
        error("Agent force '" .. agent_force_name .. "' does not exist")
    end
    
    for _, force_name in ipairs(force_names or {}) do
        local other_force = game.forces[force_name]
        if other_force then
            agent_force.set_friend(other_force, true)
            other_force.set_friend(agent_force, true)
        end
    end
end

--- Update enemy relationships for an agent's force
--- @param agent_id number
--- @param force_names table<string> Array of force names to set as enemy
function M:update_agent_enemies(agent_id, force_names)
    if not storage.agent_forces then
        error("Agent " .. tostring(agent_id) .. " has no force assigned")
    end
    local agent_force_name = storage.agent_forces[agent_id]
    if not agent_force_name then
        error("Agent " .. tostring(agent_id) .. " has no force assigned")
    end
    
    local agent_force = game.forces[agent_force_name]
    if not agent_force then
        error("Agent force '" .. agent_force_name .. "' does not exist")
    end
    
    for _, force_name in ipairs(force_names or {}) do
        local other_force = game.forces[force_name]
        if other_force then
            agent_force.set_cease_fire(other_force, false)
            agent_force.set_friend(other_force, false)
            other_force.set_cease_fire(agent_force, false)
            other_force.set_friend(agent_force, false)
        end
    end
end

--- Destroy an agent with optional force cleanup
--- @param agent_id number
--- @param destroy_force boolean|nil If true, destroy force (errors if other agents use it)
function M:destroy_agent(agent_id, destroy_force)
    local agent = self:get_agent(agent_id)
    if not agent then
        error("Agent " .. tostring(agent_id) .. " not found")
    end
    
    -- Destroy character
    if agent.valid then
        agent.destroy()
    end
    
    -- Cleanup storage
    if storage.agent_characters then
        storage.agent_characters[agent_id] = nil
    end
    
    -- Handle force cleanup
    if destroy_force then
        local agent_force_name = storage.agent_forces and storage.agent_forces[agent_id]
        if agent_force_name then
            -- Check if other agents use this force
            local other_agents_using_force = false
            for other_id, force_name in pairs(storage.agent_forces) do
                if other_id ~= agent_id and force_name == agent_force_name then
                    other_agents_using_force = true
                    break
                end
            end
            
            if other_agents_using_force then
                error("Cannot destroy force '" .. agent_force_name .. "': other agents still use it")
            end
            
            -- Destroy force (Note: Forces cannot be deleted in Factorio API, so we just remove from tracking)
            -- The force will remain in game but won't be tracked by our system
            if game.forces[agent_force_name] then
                -- Forces are permanent in Factorio - cannot be deleted
                -- We just remove from our tracking
            end
            
            -- Cleanup force mapping
            storage.agent_forces[agent_id] = nil
        end
    else
        -- Just remove from mapping, keep force alive
        if storage.agent_forces then
            storage.agent_forces[agent_id] = nil
        end
    end
end

--- List all agent-to-force mappings
--- @return table<number, string> Mapping of agent_id -> force_name
function M:list_agent_forces()
    return storage.agent_forces or {}
end

-- ============================================================================
-- SELECTION MANAGEMENT
-- ============================================================================

function M:set_selected(agent_id, selected)
    storage.agent_selection = storage.agent_selection or {}
    storage.agent_selection[agent_id] = selected
end

function M:get_selected(agent_id)
    return storage.agent_selection and storage.agent_selection[agent_id] or nil
end

function M:clear_selected(agent_id)
    if storage.agent_selection then
        storage.agent_selection[agent_id] = nil
    end
end

-- ============================================================================
-- ADMIN API AND SNAPSHOTS
-- ============================================================================

--- Inspect agent details
--- @param agent_id number - agent ID (required)
--- @param attach_inventory boolean - whether to include inventory (default false)
--- @return table - {agent_id, tick, position {x, y}, inventory?} or {error, agent_id, tick}
local function inspect_agent(agent_id, attach_inventory)
    attach_inventory = attach_inventory or false
    
    local agent = M:get_agent(agent_id)
    if not agent or not agent.valid then
        return {
            error = "Agent not found or invalid",
            agent_id = agent_id,
            tick = game.tick or 0
        }
    end

    local position = agent.position
    if not position then
        return {
            error = "Agent has no position",
            agent_id = agent_id,
            tick = game.tick or 0
        }
    end

    local result = {
        agent_id = agent_id,
        tick = game.tick or 0,
        position = { x = position.x, y = position.y }
    }

    -- Get agent inventory only if requested
    if attach_inventory then
        local inventory = {}
        local main_inventory = agent.get_main_inventory and agent:get_main_inventory()
        if main_inventory then
            local contents = main_inventory.get_contents()
            if contents and next(contents) ~= nil then
                inventory = contents
            end
        end
        result.inventory = inventory
    end

    return result
end

--- Destroy multiple agents with optional force cleanup
--- @param agent_ids table<number> Array of agent IDs to destroy
--- @param destroy_forces boolean|nil If true, destroy forces (errors if other agents use them)
function M:destroy_agents(agent_ids, destroy_forces)
    local destroyed = {}
    local errors = {}
    
    for _, agent_id in ipairs(agent_ids or {}) do
        local ok, err = pcall(function()
            self:destroy_agent(agent_id, destroy_forces)
        end)
        if ok then
            table.insert(destroyed, agent_id)
        else
            table.insert(errors, {agent_id = agent_id, error = tostring(err)})
        end
    end
    
    return {
        destroyed = destroyed,
        errors = errors
    }
end

M.admin_api = {
    inspect_agent = inspect_agent,
    create_agents = M.create_agent_characters,
    destroy_agents = M.destroy_agents,
    update_agent_friends = M.update_agent_friends,
    update_agent_enemies = M.update_agent_enemies,
    list_agent_forces = M.list_agent_forces,
}

M.on_demand_snapshots = { inspect_agent = inspect_agent }

return M

