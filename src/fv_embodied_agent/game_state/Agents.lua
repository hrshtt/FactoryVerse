--- factorio_verse/core/game_state/AgentGameState.lua
--- AgentGameState sub-module for managing agent-related functionality.
--- Static module - no instantiation required.
--- Uses new Agent class with metatable registration for OOP-based state management.

local Agent = require("Agent")
local udp = require("utils.udp")
local utils = require("utils.utils")
local ParamSpec = require("utils.ParamSpec")
local custom_events = require("utils.custom_events")
local M = {}

-- ============================================================================
-- DEBUG FLAG
-- ============================================================================
M.DEBUG = false


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

--- Create a new agent instance using Agent class (internal helper)
--- @param agent_id number
--- @param color table|nil RGB color {r, g, b}
--- @param force_name string|nil Optional force name (if nil, uses agent-{agent_id})
--- @param spawn_position table|nil Optional spawn position {x, y}
--- @param udp_port number|nil Optional UDP port for agent-specific payloads (defaults to 34202)
--- @return Agent Agent instance
function M._create_agent_instance(agent_id, color, force_name, spawn_position, udp_port)
    -- Use Agent:new() which handles all initialization
    local agent = Agent:new(agent_id, color, force_name, spawn_position, udp_port)
    
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

--- Create a single agent
--- @param udp_port number|nil UDP port for agent-specific payloads (defaults to 34202)
--- @param destroy_existing boolean|nil If true, destroy existing agents
--- @param set_unique_forces boolean|nil Default false - use player force; if true, agent gets unique force
--- @param default_common_force string|nil Force name to use if set_unique_forces=false (default: "player")
--- @param initial_inventory table|nil Initial inventory items {item_name = count, ...}
--- @return table Created agent info {agent_id, force_name, interface_name}
function M.create_agent(udp_port, destroy_existing, set_unique_forces, default_common_force, initial_inventory)
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

    -- Create single agent with ID 1
    local agent_id = 1
    log("Creating agent " .. agent_id)
    
    local position = { x = 0, y = 0 }
    local force_name = nil
    if use_unique_forces then
        force_name = nil  -- Will auto-generate agent-{agent_id}
    else
        force_name = default_common_force or "player"
    end
    
    local color = generate_agent_color(1, 1)
    local agent = M._create_agent_instance(agent_id, color, force_name, position, udp_port)
    
    -- Add initial inventory items if provided
    if initial_inventory and type(initial_inventory) == "table" and next(initial_inventory) ~= nil then
        if agent.character and agent.character.valid then
            local inventory = agent.character.get_main_inventory()
            if inventory then
                for item_name, count in pairs(initial_inventory) do
                    inventory.insert({name = item_name, count = count})
                end
            end
        end
    end
    
    return {
        agent_id = agent.agent_id,
        force_name = agent.force_name,
        interface_name = "agent_" .. agent.agent_id,
        udp_port = agent.udp_port,
    }
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
--- Converts agent message queue format to consistent action payload format
--- Iterates over all categories and sends all messages with category in metadata
--- @param agent Agent Agent instance
local function process_agent_messages(agent)
    local message_queue = agent:get_queued_messages()
    if not message_queue or next(message_queue) == nil then
        -- Queue is empty, no UDP to send
        return
    end
    
    if M.DEBUG then
        local total_messages = 0
        for category, messages in pairs(message_queue) do
            if messages then
                total_messages = total_messages + #messages
            end
        end
        if total_messages > 0 then
            game.print(string.format("[DEBUG process_agent_messages] Agent %d: Processing %d messages from queue", 
                agent.agent_id, total_messages))
        end
    end
    
    -- Iterate over all categories
    for category, messages in pairs(message_queue) do
        if messages and type(messages) == "table" then
            -- Send all messages in this category
            for _, message in ipairs(messages) do
                -- Clean up message for result field (remove redundant fields)
                local result = {}
                for k, v in pairs(message) do
                    if k ~= "action" and k ~= "agent_id" and k ~= "tick" and 
                       k ~= "action_id" and k ~= "success" and k ~= "cancelled" and k ~= "status" then
                        result[k] = v
                    end
                end
                
                -- Create action payload using consistent schema
                local action_id = message.action_id or string.format("%s_%d_%d", message.action or "unknown", game.tick, agent.agent_id)
                local status = message.status  -- REQUIRED: explicit state machine status
                local payload = udp.create_action_payload(
                    action_id,
                    agent.agent_id,
                    message.action or "unknown",
                    status,
                    message.tick,
                    next(result) ~= nil and result or nil,  -- Only include if non-empty
                    message.success,
                    message.cancelled,
                    category
                )
                
                -- Send UDP notification using agent-specific port
                local agent_udp_port = (agent and agent.udp_port) or udp.UDP_PORT
                udp.send_udp_notification(payload, agent_udp_port)
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
    
    -- Early exit: Check if there are any agents at all
    local has_agents = false
    for _ in pairs(storage.agents) do
        has_agents = true
        break
    end
    if not has_agents then
        return
    end
    
    local agent_count = 0
    local message_count = 0
    
    -- Process each agent
    for agent_id, agent in pairs(storage.agents) do
        -- Skip if not a valid Agent instance
        if not agent or type(agent.process) ~= "function" then
            goto continue
        end
        
        agent_count = agent_count + 1
        
        -- Process agent state machine updates
        -- This updates walking, mining, crafting, placement state machines
        -- and enqueues completion messages
        agent:process(event)
        
        -- Process and send UDP messages from agent's message queue
        local agent_message_count = 0
        if agent.message_queue then
            for category, messages in pairs(agent.message_queue) do
                if messages then
                    agent_message_count = agent_message_count + #messages
                    message_count = message_count + #messages
                end
            end
        end
        process_agent_messages(agent)
        
        -- Only log when agent actually sends messages (not on every tick)
        if M.DEBUG and agent_message_count > 0 then
            game.print(string.format("[DEBUG Agents.on_tick] Agent %d sent %d messages", agent_id, agent_message_count))
        end
        
        ::continue::
    end
    
    -- Only log summary when messages were sent (not on every idle tick)
    if M.DEBUG and message_count > 0 then
        game.print(string.format("[DEBUG Agents.on_tick] Tick %d: processed %d agents, %d total messages", 
            game.tick, agent_count, message_count))
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

--- List all agents with their details
--- @return table[] Array of agent entries with id, force, udp_port, interface_name, entity_valid, position, agent_tag, and agent_color
function M.list_agents()
    local agents_list = {}
    
    if not storage.agents then
        return agents_list
    end
    
    for agent_id, agent in pairs(storage.agents) do
        if agent then
            local agent_id_value = agent.agent_id or agent_id
            local entry = {
                id = agent_id_value,
                force = agent.force_name,
                udp_port = agent.udp_port,
                interface_name = "agent_" .. agent_id_value,
                entity_valid = false,
            }
            
            -- Check if character entity is valid and get position, tag, and color
            if agent.character and agent.character.valid then
                entry.entity_valid = true
                local pos = agent.character.position
                if pos then
                    entry.position = { x = pos.x, y = pos.y }
                end
                
                -- Get character name tag
                if agent.character.name_tag then
                    entry.agent_tag = agent.character.name_tag
                end
                
                -- Get character color
                if agent.character.color then
                    local color = agent.character.color
                    entry.agent_color = { r = color.r, g = color.g, b = color.b, a = color.a or 1.0 }
                end
            end
            
            table.insert(agents_list, entry)
        end
    end
    
    -- Sort by agent ID for consistent ordering
    table.sort(agents_list, function(a, b)
        return (a.id or 0) < (b.id or 0)
    end)
    
    return agents_list
end


-- ============================================================================
-- ADMIN API AND SNAPSHOTS
-- ============================================================================

--- Specifications for admin API methods
M.AdminApiSpecs = {
    create_agent = {
        _param_order = {"udp_port", "destroy_existing", "set_unique_forces", "default_common_force", "initial_inventory"},
        udp_port = {type = "number", required = false},
        destroy_existing = {type = "boolean", required = false},
        set_unique_forces = {type = "boolean", required = false},
        default_common_force = {type = "string", required = false},
        initial_inventory = {type = "table", required = false},
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
    list_agents = {
        _param_order = {},
    },
    reset_research = {
        _param_order = {"force_name"},
        force_name = {type = "string", required = true},
    },
    inspect_research = {
        _param_order = {"force_name"},
        force_name = {type = "string", required = true},
    },
}

-- ============================================================================
-- RESEARCH METHODS (Agent-centric, uses force_name)
-- ============================================================================

--- Reset research for a force (agent-centric: uses force_name)
--- @param force_name string Force name
--- @return table Result
function M.reset_research(force_name)
    if not force_name or type(force_name) ~= "string" then
        return { error = "force_name (string) is required" }
    end
    
    local force = game.forces[force_name]
    if not force then
        return { error = "Force '" .. force_name .. "' not found" }
    end
    
    force.cancel_current_research()
    force.reset_technology_effects()
    force.reset_technologies()
    
    return { success = true, force_name = force_name }
end

--- Inspect research for a force (agent-centric: uses force_name)
--- @param force_name string Force name
--- @return table Research information
function M.inspect_research(force_name)
    if not force_name or type(force_name) ~= "string" then
        return { error = "force_name (string) is required" }
    end
    
    local force = game.forces[force_name]
    if not force then
        return { error = "Force '" .. force_name .. "' not found" }
    end
    
    local current_research = force.research_queue
    local current_research_name = nil
    if current_research and #current_research > 0 then
        current_research_name = current_research[1].name
    end
    
    return {
        force_name = force_name,
        current_research = current_research_name,
        queue_length = current_research and #current_research or 0,
    }
end

-- ============================================================================
-- TESTING API (only exposed when admin API is enabled)
-- ============================================================================

--- Add items to agent inventory
--- @param agent_id number
--- @param items table {item_name = count, ...}
--- @return table {success, items_added}
function M.add_items(agent_id, items)
    local agent = M.get_agent(agent_id)
    if not agent or not agent.character or not agent.character.valid then
        error("Agent not found or invalid")
    end
    
    local inventory = agent.character.get_main_inventory()
    if not inventory then
        error("Agent has no inventory")
    end
    
    local items_added = {}
    for item_name, count in pairs(items) do
        local inserted = inventory.insert({name = item_name, count = count})
        items_added[item_name] = inserted
    end
    
    return {
        success = true,
        items_added = items_added,
        tick = game.tick
    }
end

--- Clear agent inventory
--- @param agent_id number
--- @return table {success, items_removed}
function M.clear_inventory(agent_id)
    local agent = M.get_agent(agent_id)
    if not agent or not agent.character or not agent.character.valid then
        error("Agent not found or invalid")
    end
    
    local inventory = agent.character.get_main_inventory()
    if not inventory then
        error("Agent has no inventory")
    end
    
    local items_removed = inventory.get_contents()
    inventory.clear()
    
    return {
        success = true,
        items_removed = items_removed,
        tick = game.tick
    }
end

--- Unlock technology for agent's force
--- @param agent_id number
--- @param tech_name string
--- @return table {success, technology, unlocked_recipes}
function M.unlock_technology(agent_id, tech_name)
    local agent = M.get_agent(agent_id)
    if not agent then
        error("Agent not found")
    end
    
    local force = game.forces[agent.force_name]
    if not force then
        error("Agent force not found")
    end
    
    local tech = force.technologies[tech_name]
    if not tech then
        error("Technology '" .. tech_name .. "' not found")
    end
    
    tech.researched = true
    
    -- Get unlocked recipes
    local unlocked_recipes = {}
    if tech.prototype.effects then
        for _, effect in pairs(tech.prototype.effects) do
            if effect.type == "unlock-recipe" then
                table.insert(unlocked_recipes, effect.recipe)
            end
        end
    end
    
    return {
        success = true,
        technology = tech_name,
        unlocked_recipes = unlocked_recipes,
        tick = game.tick
    }
end

--- Set agent crafting speed multiplier
--- @param agent_id number
--- @param multiplier number Speed multiplier (1.0 = normal, 2.0 = 2x speed)
--- @return table {success, speed}
function M.set_crafting_speed(agent_id, multiplier)
    local agent = M.get_agent(agent_id)
    if not agent or not agent.character or not agent.character.valid then
        error("Agent not found or invalid")
    end
    
    -- character_crafting_speed_modifier is a bonus, so 1.0 = normal speed
    -- To get 2x speed, we need modifier = 1.0 (100% bonus)
    agent.character.character_crafting_speed_modifier = multiplier - 1.0
    
    return {
        success = true,
        speed = multiplier,
        modifier = multiplier - 1.0,
        tick = game.tick
    }
end

--- Get comprehensive agent state for testing assertions
--- @param agent_id number
--- @return table Agent state
function M.get_agent_state(agent_id)
    local agent = M.get_agent(agent_id)
    if not agent or not agent.character or not agent.character.valid then
        error("Agent not found or invalid")
    end
    
    local inventory = agent.character.get_main_inventory()
    local force = game.forces[agent.force_name]
    
    return {
        agent_id = agent_id,
        position = {x = agent.character.position.x, y = agent.character.position.y},
        force = agent.force_name,
        inventory = inventory and inventory.get_contents() or {},
        crafting_speed_modifier = agent.character.character_crafting_speed_modifier,
        current_research = force.current_research and force.current_research.name or nil,
        tick = game.tick
    }
end

M.admin_api = {
    create_agent = M.create_agent,
    destroy_agents = M.destroy_agents,
    update_agent_friends = M.update_agent_friends,
    update_agent_enemies = M.update_agent_enemies,
    list_agent_forces = M.list_agent_forces,
    list_agents = M.list_agents,
    reset_research = M.reset_research,
    inspect_research = M.inspect_research,
}

M.testing_api = {
    add_items = M.add_items,
    clear_inventory = M.clear_inventory,
    unlock_technology = M.unlock_technology,
    set_crafting_speed = M.set_crafting_speed,
    get_agent_state = M.get_agent_state,
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
                    if M.DEBUG then
                        game.print("path request for " .. event.id .. " failed")
                    end
                end
                if not (storage.agents and event.id) then return end

                local path_id = event.id
                for _, agent in pairs(storage.agents) do
                    if agent.walking.path_id == path_id then
                        if not event.path then
                            if M.DEBUG then
                                game.print("path request for " .. event.id .. " failed")
                            end
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
-- CUSTOM EVENT EXPORTS
-- ============================================================================

--- Export custom events for use by fv_snapshot
--- These events are raised by agent actions and listened to by fv_snapshot
M.custom_events = custom_events

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
