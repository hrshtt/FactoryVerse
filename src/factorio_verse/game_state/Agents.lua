--- factorio_verse/core/game_state/AgentGameState.lua
--- AgentGameState sub-module for managing agent-related functionality.
--- Static module - no instantiation required.
--- Uses new Agent class with metatable registration for OOP-based state management.

local Agent = require("Agent")
local snapshot = require("utils.snapshot")
local utils = require("utils.utils")
local Map = require("game_state.Map")
local ParamSpec = require("utils.ParamSpec")
local M = {}


-- ============================================================================
-- AGENT LIFECYCLE MANAGEMENT
-- ============================================================================

--- Create or get a force by name, setting default friendly relationships
--- @param force_name string Force name
--- @return LuaForce
function M.create_or_get_force(force_name)
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
function M.create_agent(agent_id, color, force_name, spawn_position)
    -- Use Agent:new() which handles all initialization
    local agent = Agent:new(agent_id, color, force_name, spawn_position)
    
    return agent
end

--- Get agent by ID
--- @param agent_id number
--- @return Agent|nil Agent instance or nil if not found
function M.get_agent(agent_id)
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
--- @param set_unique_forces boolean|nil Default false - use player force; if true, each agent gets unique force
--- @param default_common_force string|nil Force name to use if set_unique_forces=false (default: "player")
--- @return table Array of created agent info {agent_id, force_name}
function M.create_agents(num_agents, destroy_existing, set_unique_forces, default_common_force)
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
    -- Default to false (use player force) instead of unique forces
    local use_unique_forces = set_unique_forces == true
    
    -- Warn if using unique forces about charting/radar/bots limitations
    if use_unique_forces then
        local warning_msg = "WARNING: Using unique forces for agents. In-engine charting updates will not work for forces without a connected LuaPlayer, for the character, radar and bots."
        game.print(warning_msg)
        log(warning_msg)
    end
    
    if not use_unique_forces then
        -- Use common force (default to "player")
        local common_force_name = default_common_force or "player"
        
        -- Verify force exists if provided
        if default_common_force then
            if not game.forces[common_force_name] then
                error("Force '" .. common_force_name .. "' does not exist")
            end
        else
            -- Player force always exists, no need to create it
            if not game.forces.player then
                error("Player force does not exist")
            end
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
            force_name = default_common_force or "player"
        end
        
        local color = generate_agent_color(i, num_agents)
        local agent = M.create_agent(i, color, force_name, position)
        
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
function M.destroy_agent(agent_id, remove_force)
    local agent = M.get_agent(agent_id)
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
function M.destroy_agents(agent_ids, remove_forces)
    local destroyed = {}
    local errors = {}
    
    for _, agent_id in ipairs(agent_ids or {}) do
        local ok, err = pcall(function()
            M.destroy_agent(agent_id, remove_forces)
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
function M.on_tick(event)
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

        -- game.print(string.format("Processing agent %d", agent_id))
        
        -- Process and send UDP messages from agent's message queue
        process_agent_messages(agent)
        
        ::continue::
        end
    end
    
--- Get on_tick handlers for agent processing
--- @return table Array of handler functions
function M.get_on_tick_handlers()
    return { M.on_tick }
end

-- ============================================================================
-- FORCE MANAGEMENT
-- ============================================================================

--- Update friendly relationships for an agent's force
--- @param agent_id number
--- @param force_names table<string> Array of force names to set as friendly
function M.update_agent_friends(agent_id, force_names)
    local agent = M.get_agent(agent_id)
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
function M.update_agent_enemies(agent_id, force_names)
    local agent = M.get_agent(agent_id)
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
function M.list_agent_forces()
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

function M._on_nth_tick_agent_production_snapshot()
    local agents = M.list_agent_forces()
    for agent_id, force_name in pairs(agents) do
        local agent = M.get_agent(agent_id)
        if agent and agent.entity.valid then
            stats = agent:get_production_statistics()
            if not stats then goto continue end
            -- Append a snapshot entry in JSONL format
            local entry = {
                tick = game.tick,
                statistics = stats
            }
            local json_line = helpers.table_to_json(entry) .. "\n"
            helpers.write_file(
                snapshot.SNAPSHOT_BASE_DIR .. "/" .. agent_id .. "/production_statistics.jsonl",
                json_line,
                true -- append
                -- for_player omitted (server/global)
            )
        end
        ::continue::
    end
end

-- ============================================================================
-- ADMIN API AND SNAPSHOTS
-- ============================================================================

--- Specifications for admin API methods
M.AdminApiSpecs = {
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
    create_agents = M.create_agents,
    destroy_agents = M.destroy_agents,
    update_agent_friends = M.update_agent_friends,
    update_agent_enemies = M.update_agent_enemies,
    list_agent_forces = M.list_agent_forces,
}

-- ============================================================================
-- EVENT HANDLERS
-- ============================================================================

--- Get events (defined events and nth_tick)
--- @return table {defined_events = {}, nth_tick = {}}
function M.get_events()
    return {
        defined_events = {
            [defines.events.on_script_path_request_finished] = function(event)
                if not event.path then
                    game.print("path request for " .. event.id .. " failed")
                end
                if not (storage.agents and event.id) then return end

                local path_id = event.id
                for _, agent in pairs(storage.agents) do
                    if agent.walking.path_id == path_id then
                        if not event.path then
                            game.print("path request for " .. event.id .. " failed")
                            return
                        end
                        agent.walking.path = event.path
                        agent.walking.progress = 1
                        break
                    end
                end
            end
        },
        nth_tick = {}
    }
end

-- ============================================================================
-- REMOTE INTERFACE REGISTRATION
-- ============================================================================

--- Register remote interface for agent admin methods
--- @return table Remote interface table
function M.register_remote_interface()
    
    local interface = {}
    
    -- Register all admin methods with parameter normalization
    for api_name, api_func in pairs(M.admin_api) do
        local spec = M.AdminApiSpecs[api_name]
        interface[api_name] = function(...)
            local normalized_args = ParamSpec:normalize_varargs(spec, ...)
            return api_func(table.unpack(normalized_args))
        end
    end
    
    return interface
end

return M
