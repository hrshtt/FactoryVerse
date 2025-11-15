--- Agent OOP class with metatable registration for save/load persistence
--- @class Agent
--- @field agent_id number Agent ID
--- @field entity LuaEntity Character entity for the agent
--- @field force_name string Force name (access force via entity.force)
--- @field labels AgentLabels Rendering labels for the agent
--- @field walking AgentWalkingState Walking state (jobs, intents)
--- @field mining AgentMiningState Mining state (active job)
--- @field crafting AgentCraftingState Crafting state (in-progress tracking)
--- @field placing AgentPlacementState Placement state (active jobs)
--- @field charted_chunks AgentChartedChunks List of charted chunk coordinates
--- @field message_queue table[] Queue of UDP messages to be sent (processed by game state)

--- @class AgentLabels : table
--- @field main_tag LuaRenderObject Main name tag rendering object
--- @field map_marker LuaRenderObject Map marker rendering object
--- @field map_tag LuaRenderObject Map tag rendering object

--- @class AgentWalkingState : table
--- @field jobs table<number, table> Active walk-to jobs keyed by job_id
--- @field intent table|nil Sustained walking intent {direction, end_tick, walking}
--- @field next_job_id number Next job ID for walk-to jobs

--- @class AgentMiningState : table
--- @field job table|nil Active mining job {resource_name, position, target_count, action_id, ...}

--- @class AgentCraftingState : table
--- @field in_progress table|nil Active crafting tracking {recipe, count, action_id, ...}

--- @class AgentPlacementState : table
--- @field jobs table<number, table> Active placement jobs keyed by job_id
--- @field next_job_id number Next job ID for placement jobs

--- List of charted chunk {x:number, y:number} coordinates
--- @class AgentChartedChunks : table[]

local utils = require("utils.utils")

-- Require action modules at module level (Factorio requirement)
local WalkingActions = require("types.agent.walking")
local MiningActions = require("types.agent.mining")
local CraftingActions = require("types.agent.crafting")
local PlacementActions = require("types.agent.placement")
local EntityOpsActions = require("types.agent.entity_ops")

-- ============================================================================
-- METATABLE REGISTRATION (must be at module load time)
-- ============================================================================

local Agent = {}
Agent.__index = Agent

-- Register metatable for save/load persistence
-- This must happen at module load time, not in on_init/on_load
script.register_metatable('Agent', Agent)

-- Mix in action methods from modules
-- This must happen at module level before Agent:new() can be called
for k, v in pairs(WalkingActions) do
    Agent[k] = v
end
for k, v in pairs(MiningActions) do
    Agent[k] = v
end
for k, v in pairs(CraftingActions) do
    Agent[k] = v
end
for k, v in pairs(PlacementActions) do
    Agent[k] = v
end
for k, v in pairs(EntityOpsActions) do
    Agent[k] = v
end

-- ============================================================================
-- AGENT CREATION
-- ============================================================================

--- Create a new agent instance
--- @param agent_id number
--- @param color table|nil RGB color {r, g, b}
--- @param force_name string|nil Optional force name (if nil, uses agent-{agent_id})
--- @param spawn_position table|nil Optional spawn position {x, y}
--- @return Agent
function Agent:new(agent_id, color, force_name, spawn_position)
    -- Initialize storage if needed
    storage.agents = storage.agents or {}
    
    -- If agent already exists, return it
    if storage.agents[agent_id] then
        return storage.agents[agent_id]
    end
    
    -- Create agent instance with all state consolidated
    local agent = setmetatable({
        agent_id = agent_id,
        entity = nil,  -- Will be set in _create_entity
        force_name = nil,  -- Will be set in _create_entity
        labels = {},
        
        -- Consolidated activity state
        walking = {
            jobs = {},
            intent = nil,
            next_job_id = 1,
        },
        mining = {
            job = nil,
        },
        crafting = {
            in_progress = nil,
        },
        placing = {
            jobs = {},
            next_job_id = 1,
        },
        charted_chunks = {},
        
        -- Message queue for UDP notifications (processed by game state)
        -- Structure: message_queue[category_string] = {message1, message2, ...}
        message_queue = {},
    }, Agent)
    
    -- Create entity and initialize
    agent:_create_entity(color, force_name, spawn_position)
    
    -- Store agent instance
    storage.agents[agent_id] = agent
    
    -- Register per-agent remote interface
    agent:register_remote_interface()
    
    return agent
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

--- Create entity and initialize rendering labels
--- @param color table|nil RGB color {r, g, b}
--- @param force_name string|nil Optional force name
--- @param spawn_position table|nil Optional spawn position {x, y}
function Agent:_create_entity(color, force_name, spawn_position)
    -- Determine force name
    local final_force_name = force_name
    if not final_force_name then
        final_force_name = "agent-" .. tostring(self.agent_id)
    end

    -- Create or get force
    local force = self:create_or_get_force(final_force_name)
    local name_tag = "Agent-" .. tostring(self.agent_id)

    local surface = game.surfaces[1]
    local spawn_pos = spawn_position or force.get_spawn_position(surface)
    local safe_position = surface.find_non_colliding_position("character", spawn_pos, 10, 2)

    -- Create character entity
    local char_entity = surface.create_entity {
        name = "character",
        position = safe_position or spawn_pos,
        force = force
    }

    if not char_entity or not char_entity.valid then
        error("Failed to create character for agent " .. tostring(self.agent_id))
    end
    
    if color then
        char_entity.color = color
    end

    char_entity.name_tag = name_tag
    
    -- Create rendering labels
    local main_tag = rendering.draw_text {
        text = name_tag,
        target = char_entity,
        surface = char_entity.surface,
        color = { r = 1, g = 1, b = 1, a = 1 },
        scale = 1.2,
        font = "default-game",
        alignment = "center",
        vertical_alignment = "middle"
    }
    
    local map_marker = rendering.draw_circle {
        color = char_entity.color,
        radius = 2.5,
        filled = true,
        target = char_entity,
        surface = char_entity.surface,
        render_mode = "chart",
        scale_with_zoom = true
    }
    
    local map_tag = rendering.draw_text {
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

    -- Set agent properties
    self.entity = char_entity
    self.force_name = final_force_name
    self.labels = {
        main_tag = main_tag,
        map_marker = map_marker,
        map_tag = map_tag
    }
end

-- ============================================================================
-- REMOTE INTERFACE REGISTRATION
-- ============================================================================

--- Register per-agent remote interface
--- Interface name: "agent_{agent_id}"
function Agent:register_remote_interface()
    local interface_name = "agent_" .. self.agent_id
    
    -- Remove existing interface if present
    if remote.interfaces[interface_name] then
        remote.remove_interface(interface_name)
    end
    
    -- Create interface with direct method proxies
    local interface = {
        -- Walking
        walk_to = function(position, options)
            return self:walk_to(position, options)
        end,
        cancel_walking = function(job_id)
            return self:cancel_walking(job_id)
        end,
        
        -- Mining
        mine_resource = function(resource_name, position, max_count)
            return self:mine_resource(resource_name, position, max_count)
        end,
        cancel_mining = function()
            return self:cancel_mining()
        end,
        
        -- Crafting
        craft_enqueue = function(recipe_name, count)
            return self:craft_enqueue(recipe_name, count)
        end,
        craft_dequeue = function(recipe_name, count)
            return self:craft_dequeue(recipe_name, count)
        end,
        
        -- Entity operations
        set_entity_recipe = function(entity_name, position, recipe_name)
            return self:set_entity_recipe(entity_name, position, recipe_name)
        end,
        set_entity_filter = function(entity_name, position, inventory_type, filter_index, filter_item)
            return self:set_entity_filter(entity_name, position, inventory_type, filter_index, filter_item)
        end,
        set_inventory_limit = function(entity_name, position, inventory_type, limit)
            return self:set_inventory_limit(entity_name, position, inventory_type, limit)
        end,
        get_inventory_item = function(entity_name, position, inventory_type, item_name, count)
            return self:get_inventory_item(entity_name, position, inventory_type, item_name, count)
        end,
        set_inventory_item = function(entity_name, position, inventory_type, item_name, count)
            return self:set_inventory_item(entity_name, position, inventory_type, item_name, count)
        end,
        
        -- Placement
        place_entity = function(entity_name, position, options)
            return self:place_entity(entity_name, position, options)
        end,
        cancel_placement = function(job_id)
            return self:cancel_placement(job_id)
        end,
        
        -- Teleport
        teleport = function(position)
            return self:teleport(position)
        end,
        
        -- State queries
        inspect = function(attach_inventory, attach_entities)
            return self:inspect(attach_inventory, attach_entities)
        end,
    }
    
    remote.add_interface(interface_name, interface)
end

--- Unregister per-agent remote interface
function Agent:unregister_remote_interface()
    local interface_name = "agent_" .. self.agent_id
    if remote.interfaces[interface_name] then
        remote.remove_interface(interface_name)
    end
end

-- ============================================================================
-- AGENT LIFECYCLE
-- ============================================================================

--- Destroy the agent and clean up all resources
--- @param remove_force boolean|nil If true, merge force with player force
--- @return boolean
function Agent:destroy(remove_force)
    remove_force = remove_force or false
    
    -- Unregister remote interface
    self:unregister_remote_interface()
    
    -- Destroy entity
    if self.entity and self.entity.valid then
        self.entity.destroy()
    end
    
    -- Destroy rendering labels
    if self.labels.main_tag then
        self.labels.main_tag.destroy()
    end
    if self.labels.map_marker then
        self.labels.map_marker.destroy()
    end
    if self.labels.map_tag then
        self.labels.map_tag.destroy()
    end
    
    -- Handle force cleanup
    if remove_force and self.force_name then
        local agent_force = game.forces[self.force_name]
        if agent_force then
        game.merge_forces(agent_force, game.forces.player)
        end
    end
    
    -- Remove from storage
    storage.agents[self.agent_id] = nil
    
    return true
end

--- Merge agent's force with another force
--- @param destination_force string Force name to merge into
--- @return boolean
function Agent:merge_force(destination_force)
    if not game.forces[destination_force] then
        error("Force " .. tostring(destination_force) .. " not found")
    end
    
    if self.force_name then
        game.merge_forces(self.force_name, destination_force)
    end
    
    return true
end

-- ============================================================================
-- ACTION METHODS
-- ============================================================================
-- Action methods are defined in separate modules and mixed in above:
-- - types/agent/walking.lua: walk_to, cancel_walking, stop_walking, set_walking, sustain_walking, clear_walking_intent
-- - types/agent/mining.lua: mine_resource, cancel_mining, set_mining
-- - types/agent/crafting.lua: craft_enqueue, craft_dequeue
-- - types/agent/placement.lua: place_entity, cancel_placement
-- - types/agent/entity_ops.lua: set_entity_recipe, set_entity_filter, set_inventory_limit, get_inventory_item, set_inventory_item, pickup_entity
-- ============================================================================

-- ============================================================================
-- UTILITY METHODS
-- ============================================================================

--- Teleport agent to a position
--- @param position table Position {x, y}
--- @return boolean
function Agent:teleport(position)
    if not (self.entity and self.entity.valid) then
        return false
    end
    
    self.entity.teleport(position)
    return true
end

--- Get agent position
--- @return table|nil Position {x, y}
function Agent:get_position()
    if not (self.entity and self.entity.valid) then
        return nil
    end
    
    local pos = self.entity.position
    return { x = pos.x, y = pos.y }
end

--- Get agent inventory contents
--- @return table|nil Inventory contents {item_name = count, ...}
function Agent:get_inventory()
    if not (self.entity and self.entity.valid) then
        return nil
    end
    
    local main_inventory = self.entity.get_inventory(defines.inventory.character_main)
    if main_inventory then
        return main_inventory.get_contents()
    end
    
    return {}
    end

--- Inspect agent details
--- @param attach_inventory boolean|nil Include inventory
--- @param attach_reachable_entities boolean|nil Include reachable entities
--- @return table Inspection result
function Agent:inspect(attach_inventory, attach_reachable_entities)
    attach_inventory = attach_inventory or false
    attach_reachable_entities = attach_reachable_entities or false
    
    if not (self.entity and self.entity.valid) then
        return {
            error = "Agent not found or invalid",
            agent_id = self.agent_id,
            tick = game.tick or 0
        }
    end
    
    local position = self.entity.position
    local result = {
        agent_id = self.agent_id,
        tick = game.tick or 0,
        position = { x = position.x, y = position.y }
    }
    
    if attach_inventory then
        result.inventory = self:get_inventory()
    end
    
    if attach_reachable_entities then
        -- TODO: Implement reachable entities query
        result.reachable_entities = {}
        result.reachable_resources = {}
        end
    
    return result
end

-- ============================================================================
-- MESSAGE QUEUE MANAGEMENT
-- ============================================================================

--- Enqueue a UDP message to be sent by game state
--- Agent is not aware of UDP sending - only queues messages
--- @param message table UDP message payload (will be sent via snapshot.send_action_completion_udp)
--- @param category string Category for the message (e.g., "walking", "mining", "crafting", "entity_ops")
function Agent:enqueue_message(message, category)
    self.message_queue = self.message_queue or {}
    category = category or "default"
    
    -- Initialize category array if needed
    if not self.message_queue[category] then
        self.message_queue[category] = {}
    end
    
    table.insert(self.message_queue[category], message)
end

--- Clear all messages from the queue (called by game state after processing)
function Agent:clear_message_queue()
    self.message_queue = {}
end

--- Get all queued messages organized by category (called by game state for processing)
--- @return table Structure: {category_string = {message1, message2, ...}, ...}
function Agent:get_queued_messages()
    return self.message_queue or {}
end

-- ============================================================================
-- STATE MACHINE PROCESSING
-- ============================================================================

--- Process agent state machine updates for all activities
--- Aggregates updates from walking, mining, crafting, and placement state machines
--- Called by game state on each tick for each agent
--- State machine logic updates agent state and enqueues completion messages
--- @param event table Event data (typically on_tick event)
function Agent:process(event)
    -- Skip if agent entity is invalid
    if not (self.entity and self.entity.valid) then
        return
    end
    
    local current_tick = game.tick or 0
    
    -- Process walking intent (sustained walking)
    if self.walking.intent then
        if self.walking.intent.end_tick and current_tick >= self.walking.intent.end_tick then
            -- Intent expired, clear it
            self.walking.intent = nil
            self:set_walking(nil, false)
        else
            -- Continue sustained walking
            self:set_walking(self.walking.intent.direction, self.walking.intent.walking ~= false)
        end
end

    -- Process walking jobs (walk-to)
    -- TODO: Implement walk-to job processing with pathfinding
    -- For now, jobs are queued but not processed
    
    -- Process mining job
    if self.mining.job then
        local job = self.mining.job
        
        -- Validate resource entity is still valid
        if job.resource_entity and not job.resource_entity.valid then
            -- Resource depleted or invalid, complete mining
            local item_name = job.item_name
            local current_count = self.entity.get_item_count(item_name)
            local mined_count = current_count - job.initial_count
            
            self:enqueue_message({
                action = "mine_resource",
                agent_id = self.agent_id,
                success = true,
                action_id = job.action_id,
                tick = current_tick,
                resource_name = job.resource_name,
                position = job.resource_position,
                item_name = item_name,
                count = mined_count,
            }, "mining")
            
            self.mining.job = nil
            self:set_mining(false, nil)
        elseif job.mine_till_depleted then
            -- Check if resource is depleted (for trees/rocks)
            if job.resource_entity and job.resource_entity.valid then
                -- Still mining, continue
            else
                -- Resource depleted
                local item_name = job.item_name
                local current_count = self.entity.get_item_count(item_name)
                local mined_count = current_count - job.initial_count
                
                self:enqueue_message({
                    action = "mine_resource",
                    agent_id = self.agent_id,
                    success = true,
                    action_id = job.action_id,
                    tick = current_tick,
                    resource_name = job.resource_name,
                    position = job.resource_position,
                    item_name = item_name,
                    count = mined_count,
                }, "mining")
                
                self.mining.job = nil
                self:set_mining(false, nil)
            end
        elseif job.target_count then
            -- Check if target count reached
            local current_count = self.entity.get_item_count(job.item_name)
            if current_count >= job.target_count then
                -- Target reached
                local mined_count = current_count - job.initial_count
                
                self:enqueue_message({
                    action = "mine_resource",
                    agent_id = self.agent_id,
                    success = true,
                    action_id = job.action_id,
                    tick = current_tick,
                    resource_name = job.resource_name,
                    position = job.resource_position,
                    item_name = job.item_name,
                    count = mined_count,
                }, "mining")
                
                self.mining.job = nil
                self:set_mining(false, nil)
            end
        end
    end
    
    -- Process crafting
    if self.crafting.in_progress then
        local tracking = self.crafting.in_progress
        
        -- Check if crafting queue is empty (crafting completed)
        local queue_size = self.entity.crafting_queue_size or 0
        
        if queue_size == 0 and tracking.start_queue_size > 0 then
            -- Crafting completed
            local products = tracking.products or {}
            local actual_products = {}
            
            -- Calculate actual products crafted
            for item_name, amount_per_craft in pairs(products) do
                local current_count = self.entity.get_item_count(item_name)
                local start_count = tracking.start_products[item_name] or 0
                local delta = current_count - start_count
                if delta > 0 then
                    actual_products[item_name] = delta
                end
            end
            
            -- Estimate count_crafted from product deltas
            local count_crafted = 0
            for item_name, amount_per_craft in pairs(products) do
                local delta = actual_products[item_name] or 0
                if amount_per_craft > 0 then
                    local estimated = math.floor(delta / amount_per_craft)
                    if estimated > count_crafted then
                        count_crafted = estimated
                    end
    end
end

            self:enqueue_message({
                action = "craft_enqueue",
                agent_id = self.agent_id,
                success = true,
                action_id = tracking.action_id,
                tick = current_tick,
                recipe = tracking.recipe,
                count_requested = tracking.count_requested,
                count_queued = tracking.count_queued,
                count_crafted = count_crafted,
                products = actual_products,
            }, "crafting")
            
            self.crafting.in_progress = nil
        elseif tracking.cancelled then
            -- Crafting was cancelled
            self:enqueue_message({
                action = "craft_dequeue",
                agent_id = self.agent_id,
                success = true,
                cancelled = true,
                action_id = tracking.action_id,
                tick = current_tick,
                recipe = tracking.recipe,
                count_cancelled = tracking.count_cancelled or 0,
            }, "crafting")
            
            self.crafting.in_progress = nil
        end
    end
    
    -- Process placement jobs
    -- TODO: Implement placement job processing
    -- For now, jobs are queued but not processed
end

return Agent
