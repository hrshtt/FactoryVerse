--- factorio_verse/core/game_state/AgentGameState.lua
--- AgentGameState sub-module for managing agent-related functionality.
--- Uses new Agent class with metatable registration for OOP-based state management.

local Agent = require("types.Agent")
local snapshot = require("utils.snapshot")
local utils = require("utils.utils")

--- @class AgentGameState : GameStateModule
local M = {}
M.__index = M

--- @param game_state GameState
--- @return AgentGameState
function M:new(game_state)
    local instance = {
        game_state = game_state,
    }
    setmetatable(instance, self)
    
    -- Initialize storage if needed
    storage.agents = storage.agents or {}
    
    return instance
end

-- ============================================================================
-- AGENT LIFECYCLE MANAGEMENT
-- ============================================================================

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
        
        -- Set default friendly relationships with player force
        local player_force = game.forces.player
        if player_force then
            force.set_friend(player_force, true)
            player_force.set_friend(force, true)
        end
        
        -- Set friendly with all existing agent forces
        if storage.agents then
            for _, agent in pairs(storage.agents) do
                if agent and agent.force_name and agent.force_name ~= force_name then
                    local existing_force = game.forces[agent.force_name]
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

--- Generate color for agent based on index
--- @param index number
--- @param total_agents number
--- @return table RGB color {r, g, b}
local function generate_agent_color(index, total_agents)
    local hue = (index - 1) / total_agents
    local saturation = 1.0
    local value = 1.0
    return utils.hsv_to_rgb(hue, saturation, value)
end

--- Create a new agent using Agent class
--- @param agent_id number
--- @param color table|nil RGB color {r, g, b}
--- @param force_name string|nil Optional force name (if nil, uses agent-{agent_id})
--- @param spawn_position table|nil Optional spawn position {x, y}
--- @return Agent Agent instance
function M:create_agent(agent_id, color, force_name, spawn_position)
    -- Use Agent:new() which handles all initialization
    local agent = Agent:new(agent_id, color, force_name, spawn_position)
    
    -- Chart the starting area
    if agent.entity and agent.entity.valid then
        local surface = agent.entity.surface or game.surfaces[1]
        local position = agent.entity.position
        utils.chart_native_start_area(surface, agent.entity.force, position, self.game_state)
    end
    
    return agent
end

--- Get agent by ID
--- @param agent_id number
--- @return Agent|nil Agent instance or nil if not found
function M:get_agent(agent_id)
    if not storage.agents then
        storage.agents = {}
        return nil
    end
    
    local agent = storage.agents[agent_id]
    
    -- Validate agent entity is still valid
    if agent and agent.entity and not agent.entity.valid then
        -- Agent entity is invalid, but keep the Agent instance
        -- The process() method will skip invalid agents
    end
    
    return agent
end

--- Create multiple agents
--- @param num_agents number Number of agents to create
--- @param destroy_existing boolean|nil If true, destroy existing agents
--- @param set_unique_forces boolean|nil Default true - each agent gets unique force
--- @param default_common_force string|nil Force name to use if set_unique_forces=false
--- @return table Array of created agent info {agent_id, force_name}
function M:create_agents(num_agents, destroy_existing, set_unique_forces, default_common_force)
    if not storage.agents then
        storage.agents = {}
    end
    
    if destroy_existing and storage.agents then
        -- Destroy existing agents
        for agent_id, agent in pairs(storage.agents) do
            if agent and type(agent.destroy) == "function" then
                agent:destroy(false)  -- Don't remove force
            end
        end
        storage.agents = {}
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
        log("Creating agent " .. i .. " of " .. num_agents)
        
        local position = { x = 0, y = (i - 1) * 2 }
        local force_name = nil
        if use_unique_forces then
            force_name = nil  -- Will auto-generate agent-{agent_id}
        else
            force_name = default_common_force or "agent_force"
        end
        
        local color = generate_agent_color(i, num_agents)
        local agent = self:create_agent(i, color, force_name, position)
        
        table.insert(created_agents, {
            agent_id = agent.agent_id,
            force_name = agent.force_name
        })
    end
    
    return created_agents
end

--- Destroy an agent
--- @param agent_id number
--- @param remove_force boolean|nil If true, merge force with player force
function M:destroy_agent(agent_id, remove_force)
    local agent = self:get_agent(agent_id)
    if not agent then
        error("Agent " .. tostring(agent_id) .. " not found")
    end
    
    -- Use Agent:destroy() which handles all cleanup
    agent:destroy(remove_force)
end

--- Destroy multiple agents
--- @param agent_ids table<number> Array of agent IDs to destroy
--- @param remove_forces boolean|nil If true, merge forces with player force
--- @return table {destroyed: number[], errors: table[]}
function M:destroy_agents(agent_ids, remove_forces)
    local destroyed = {}
    local errors = {}
    
    for _, agent_id in ipairs(agent_ids or {}) do
        local ok, err = pcall(function()
            self:destroy_agent(agent_id, remove_forces)
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

-- ============================================================================
-- AGENT STATE PROCESSING (on_tick handler)
-- ============================================================================

--- Process agent message queue and send UDP notifications
--- Converts agent message queue format to snapshot.send_action_completion_udp format
--- Iterates over all categories and sends all messages with category in metadata
--- @param agent Agent Agent instance
local function process_agent_messages(agent)
    local message_queue = agent:get_queued_messages()
    if not message_queue or next(message_queue) == nil then
        return
    end
    
    -- Iterate over all categories
    for category, messages in pairs(message_queue) do
        if messages and type(messages) == "table" then
            -- Send all messages in this category
            for _, message in ipairs(messages) do
                -- Convert agent message format to UDP payload format
                local payload = {
                    action_id = message.action_id or string.format("%s_%d_%d", message.action or "unknown", game.tick, agent.agent_id),
                    agent_id = agent.agent_id,
                    action_type = message.action or "unknown",
                    category = category,  -- Include category in metadata
                    rcon_tick = message.tick or game.tick,
                    completion_tick = game.tick,
                    success = message.success ~= false,  -- Default to true if not specified
                    result = message,
                }
                
                -- Handle cancelled flag if present
                if message.cancelled ~= nil then
                    payload.cancelled = message.cancelled
                end
                
                -- Remove redundant fields from result
                payload.result.action = nil
                payload.result.agent_id = nil
                payload.result.tick = nil
                payload.result.action_id = nil
                payload.result.success = nil
                payload.result.cancelled = nil
                
                -- Send UDP notification
                snapshot.send_action_completion_udp(payload)
            end
        end
    end
    
    -- Clear message queue after processing (flushes all categories)
    agent:clear_message_queue()
end

--- Process all agents on each tick
--- Updates agent state machines and processes message queues
--- @param event table on_tick event
function M:on_tick(event)
    if not storage.agents then
        return
    end
    
    -- Process each agent
    for agent_id, agent in pairs(storage.agents) do
        -- Skip if not a valid Agent instance
        if not agent or type(agent.process) ~= "function" then
            goto continue
        end
        
        -- Process agent state machine updates
        -- This updates walking, mining, crafting, placement state machines
        -- and enqueues completion messages
        agent:process(event)
        
        -- Process and send UDP messages from agent's message queue
        process_agent_messages(agent)
        
        ::continue::
    end
end

--- Get on_tick event handler for agent processing
--- @return function|nil Event handler function
function M:get_on_tick_handler()
    return function(event)
        self:on_tick(event)
    end
end

-- ============================================================================
-- FORCE MANAGEMENT
-- ============================================================================

--- Update friendly relationships for an agent's force
--- @param agent_id number
--- @param force_names table<string> Array of force names to set as friendly
function M:update_agent_friends(agent_id, force_names)
    local agent = self:get_agent(agent_id)
    if not agent then
        error("Agent " .. tostring(agent_id) .. " not found")
    end
    
    if not agent.force_name then
        error("Agent " .. tostring(agent_id) .. " has no force assigned")
    end
    
    local agent_force = game.forces[agent.force_name]
    if not agent_force then
        error("Agent force '" .. agent.force_name .. "' does not exist")
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
    local agent = self:get_agent(agent_id)
    if not agent then
        error("Agent " .. tostring(agent_id) .. " not found")
    end
    
    if not agent.force_name then
        error("Agent " .. tostring(agent_id) .. " has no force assigned")
    end
    
    local agent_force = game.forces[agent.force_name]
    if not agent_force then
        error("Agent force '" .. agent.force_name .. "' does not exist")
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

--- List all agent-to-force mappings
--- @return table<number, string> Mapping of agent_id -> force_name
function M:list_agent_forces()
    local mapping = {}
    if storage.agents then
        for agent_id, agent in pairs(storage.agents) do
            if agent and agent.force_name then
                mapping[agent_id] = agent.force_name
            end
        end
    end
    return mapping
end

-- ============================================================================
-- ADMIN API AND SNAPSHOTS
-- ============================================================================

--- Inspect agent details
--- @param agent_id number Agent ID
--- @param attach_inventory boolean|nil Include inventory
--- @param attach_reachable_entities boolean|nil Include reachable entities
--- @return table Inspection result
function M:inspect_agent(agent_id, attach_inventory, attach_reachable_entities)
    attach_inventory = attach_inventory or false
    attach_reachable_entities = attach_reachable_entities or false
    
    local agent = self:get_agent(agent_id)
    if not agent then
        return {
            error = "Agent not found",
            agent_id = agent_id,
            tick = game.tick or 0
        }
    end

    -- Use Agent:inspect() method
    return agent:inspect(attach_inventory, attach_reachable_entities)
end

--- Specifications for admin API methods
M.AdminApiSpecs = {
    inspect_agent = {
        _param_order = {"agent_id", "attach_inventory", "attach_entities"},
        agent_id = {type = "number", required = true},
        attach_inventory = {type = "boolean", required = false},
        attach_entities = {type = "boolean", required = false},
    },
    create_agents = {
        _param_order = {"num_agents", "destroy_existing", "set_unique_forces", "default_common_force"},
        num_agents = {type = "number", required = true},
        destroy_existing = {type = "boolean", required = false},
        set_unique_forces = {type = "boolean", required = false},
        default_common_force = {type = "string", required = false},
    },
    destroy_agents = {
        _param_order = {"agent_ids", "destroy_forces"},
        agent_ids = {type = "table", required = true},
        destroy_forces = {type = "boolean", required = false},
    },
    update_agent_friends = {
        _param_order = {"agent_id", "force_names"},
        agent_id = {type = "number", required = true},
        force_names = {type = "table", required = true},
    },
    update_agent_enemies = {
        _param_order = {"agent_id", "force_names"},
        agent_id = {type = "number", required = true},
        force_names = {type = "table", required = true},
    },
    list_agent_forces = {
        _param_order = {},
    },
}

M.admin_api = {
    inspect_agent = M.inspect_agent,
    create_agents = M.create_agents,
    destroy_agents = M.destroy_agents,
    update_agent_friends = M.update_agent_friends,
    update_agent_enemies = M.update_agent_enemies,
    list_agent_forces = M.list_agent_forces,
}

M.on_demand_snapshots = {
    inspect_agent = M.inspect_agent,
}

return M
