
--- @class AgentLabels : table
--- @field main_tag LuaRenderObject Main name tag rendering object
--- @field map_marker LuaRenderObject Map marker rendering object
--- @field map_tag LuaRenderObject Map tag rendering object

--- @class AgentWalkingState : table
--- @field path nil|PathfinderWaypoint[]
--- @field path_id nil|number
--- @field progress number Current waypoint index
--- @field action_id string|nil Action ID for completion tracking
--- @field start_tick number|nil Tick when walking started (for time calculation)
--- @field goal table|nil Goal position {x, y} for completion tracking

--- @class AgentMiningState : table
--- @field mode string|nil Mining mode: "incremental" or "deplete"
--- @field action_id string|nil Action ID for tracking
--- @field start_tick number|nil Tick when mining started
--- @field entity_name string|nil Name of entity being mined
--- @field entity_type string|nil Type of entity being mined  
--- @field entity_position table|nil Position of entity being mined
--- @field target_count number|nil Target count (incremental mode only)
--- @field count_progress number|nil Current count (incremental mode only)
--- @field completion_threshold number|nil Progress threshold (incremental mode only)
--- @field last_progress number|nil Previous progress (incremental mode only)
--- @field is_stochastic boolean|nil Whether entity has random products (huge-rock)
--- @field start_inventory table|nil Inventory snapshot (stochastic deplete only)
--- @field expected_products table|nil Expected products for completion message

--- @class AgentCraftingState : table
--- @field in_progress table|nil Active crafting tracking {recipe, count, action_id, ...}

--- @class AgentPlacementState : table
--- @field entities_to_place table[] Entities to place keyed by entity_name
--- @field progress number Current progress of placement
--- @field undo_stack table[] Undo stack for placement jobs
--- @field jobs table[] Active placement jobs
--- @field next_job_id number Next job ID to assign

--- @class AgentReachableState : table
--- @field entities table Position keys for entities within build reach {"x,y" = true, ...}
--- @field resources table Position keys for resources within mining reach {"x,y" = true, ...}
--- @field last_updated_tick number Game tick when cache was last computed
--- @field dirty boolean True if cache needs recomputation

--- Agent class definition, wraps all agent actions and state
--- @class Agent
--- @field agent_id number Agent ID
--- @field character LuaEntity Character entity for the agent
--- @field force_name string Force name (access force via entity.force)
--- @field labels AgentLabels Rendering labels for the agent
--- @field get_production_statistics function Production statistics
--- @field message_queue table[] Queue of UDP messages to be sent (processed by game state)
--- @field on_chunk_charted defines.events Event name for chunk charted event
--- @field walking AgentWalkingState Walking state (jobs, intents)
--- @field mining AgentMiningState Mining state (active job)
--- @field crafting AgentCraftingState Crafting state (in-progress tracking)
--- @field placing AgentPlacementState Placement state (active jobs)
--- @field charted_chunks table[] List of charted chunk coordinates
--- @field walk_to fun(self: Agent, goal: {x: number, y: number}, strict_goal?: boolean, options?: table): table
--- @field stop_walking fun(self: Agent): table
--- @field process_walking fun(self: Agent)
--- @field mine_resource fun(self: Agent, resource_name: string, max_count?: number): table
--- @field stop_mining fun(self: Agent): table
--- @field finalize_mining fun(self: Agent, reason?: string): table
--- @field process_mining fun(self: Agent)
--- @field is_mining_blocking_crafting fun(self: Agent): boolean
--- @field craft_enqueue fun(self: Agent, recipe_name: string, count?: number): table
--- @field craft_dequeue fun(self: Agent, recipe_name: string, count?: number): table
--- @field process_crafting fun(self: Agent)
--- @field place_entity fun(self: Agent, entity_name: string, position: {x: number, y: number}, options?: table): table
--- @field get_placement_cues fun(self: Agent, entity_name: string): table
--- @field set_entity_recipe fun(self: Agent, entity_name: string, position?: {x: number, y: number}, recipe_name?: string): table
--- @field set_entity_filter fun(self: Agent, entity_name: string, position?: {x: number, y: number}, inventory_type: number|string, filter_index?: number, filter_item?: string): table
--- @field set_inventory_limit fun(self: Agent, entity_name: string, position?: {x: number, y: number}, inventory_type: number|string, limit: number): table
--- @field get_inventory_item fun(self: Agent, entity_name: string, position?: {x: number, y: number}, inventory_type: number|string, item_name: string, count: number): table
--- @field set_inventory_item fun(self: Agent, entity_name: string, position?: {x: number, y: number}, inventory_type: number|string, item_name: string, count: number): table
--- @field pickup_entity fun(self: Agent, entity_name: string, position?: {x: number, y: number}): table
--- @field get_technologies fun(self: Agent, only_available?: boolean): table[]
--- @field enqueue_research fun(self: Agent, technology_name: string): table
--- @field cancel_current_research fun(self: Agent): table
--- @field chart_spawn_area fun(self: Agent): boolean
--- @field get_chunks_in_view fun(self: Agent): table[]
--- @field chart_view fun(self: Agent, rechart?: boolean): boolean
--- @field register_remote_interface fun(self: Agent): nil
--- @field unregister_remote_interface fun(self: Agent): nil
--- @field reachable AgentReachableState Reachability cache for DSL reference validation
--- @field mark_reachable_dirty fun(self: Agent): nil
--- @field process_reachable fun(self: Agent): nil
--- @field get_reachable fun(self: Agent): table
local Agent = {}

-- ============================================================================
-- METATABLE REGISTRATION (must be at module load time)
-- ============================================================================

Agent.__index = Agent

Agent.on_chunk_charted = script.generate_event_name()

-- Register metatable for save/load persistence
-- This must happen at module load time, not in on_init/on_load
script.register_metatable('Agent', Agent)

local modules = {
    "walking",
    "mining",
    "crafting",
    "placement",
    "entity_ops",
    "charting",
    "researching",
    "reachability",
    "RemoteInterface",
}

for _, module in ipairs(modules) do
    local module_actions = require("agent_actions." .. module)
    for k, v in pairs(module_actions) do
        Agent[k] = v
    end
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
        entity = nil,     -- Will be set in _create_entity
        force_name = nil, -- Will be set in _create_entity
        labels = {},

        -- Consolidated activity state
        walking = {},
        mining = {
            count_progress = 0,
            target_count = nil,
            start_tick = nil,
        },
        crafting = {
            in_progress = nil,
        },
        placing = {
            jobs = {},
            next_job_id = 1,
        },
        charted_chunks = {},

        -- Reachability cache for DSL reference validation
        -- Updated on walking stop, teleport, and entity build/destroy events
        reachable = {
            entities = {},           -- { ["x,y"] = true, ... } position keys for build-reach entities
            resources = {},          -- { ["x,y"] = true, ... } position keys for mining-reach resources
            last_updated_tick = 0,   -- Tick when reachability was last computed
            dirty = true,            -- True if needs recomputation
        },

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

    agent:chart_spawn_area()

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
    self.character = char_entity
    self.force_name = final_force_name
    self.labels = {
        main_tag = main_tag,
        map_marker = map_marker,
        map_tag = map_tag
    }
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
    if self.character and self.character.valid then
        self.character.destroy()
    end

    -- Destroy rendering labels
    for _, label in pairs(self.labels) do
        if label and label.destroy then
            label.destroy()
        end
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
-- - types/agent/walking.lua: walk_to, stop_walking
-- - types/agent/mining.lua: mine_resource, stop_mining
-- - types/agent/crafting.lua: craft_enqueue, craft_dequeue
-- - types/agent/placement.lua: place_entity, TODO: place_in_line, cancel_place_in_line, undo_place_in_line
-- - types/agent/entity_ops.lua: set_entity_recipe, set_entity_filter, set_inventory_limit, get_inventory_item, set_inventory_item, pickup_entity
-- ============================================================================

-- ============================================================================
-- UTILITY METHODS
-- ============================================================================

--- Teleport agent to a position
--- @param position table Position {x, y}
--- @return boolean
function Agent:teleport(position)
    if not (self.character and self.character.valid) then
        return false
    end

    self.character.teleport(position)
    
    -- Mark reachability cache as dirty after teleport
    self:mark_reachable_dirty()
    
    return true
end

--- Get agent inventory contents
--- @return table|nil Inventory contents {item_name = count, ...}
function Agent:get_inventory_contents()
    if not (self.character and self.character.valid) then
        return nil
    end

    local main_inventory = self.character.get_main_inventory()
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

    if not (self.character and self.character.valid) then
        return {
            error = "Agent not found or invalid",
            agent_id = self.agent_id,
            tick = game.tick or 0
        }
    end

    local position = self.character.position
    if not position then
        return {
            error = "Agent has no position",
            agent_id = self.agent_id,
            tick = game.tick or 0
        }
    end

    local result = {
        agent_id = self.agent_id,
        tick = game.tick or 0,
        position = { x = position.x, y = position.y }
    }

    -- Get agent inventory only if requested
    if attach_inventory then
        local inventory = {}
        local contents = self:get_inventory_contents()
        if contents and next(contents) ~= nil then
            inventory = contents
        end
        result.inventory = inventory
    end

    -- Get entities within reach only if requested
    if attach_reachable_entities then
        local reachable_resources = {}
        local reachable_entities = {}
        local surface = self.character.surface or game.surfaces[1]

        -- Find resources within resource_reach_distance (includes resources, trees, and rocks)
        local resource_reach = self.character.resource_reach_distance
        -- Search for resources, trees, and simple-entities (rocks) separately
        local resources = surface.find_entities_filtered({
            position = position,
            radius = resource_reach,
            type = "resource"
        })

        for _, resource in ipairs(resources) do
            if resource and resource.valid then
                table.insert(reachable_resources, {
                    name = resource.name,
                    position = { x = resource.position.x, y = resource.position.y },
                    type = resource.type
                })
            end
        end

        -- Find trees within resource_reach_distance
        local trees = surface.find_entities_filtered({
            position = position,
            radius = resource_reach,
            type = "tree"
        })

        for _, tree in ipairs(trees) do
            if tree and tree.valid then
                table.insert(reachable_resources, {
                    name = tree.name,
                    position = { x = tree.position.x, y = tree.position.y },
                    type = tree.type,
                    products = tree.prototype.mineable_properties.products
                })
            end
        end

        -- Find simple-entities (rocks) within resource_reach_distance
        local rocks = surface.find_entities_filtered({
            position = position,
            radius = resource_reach,
            type = "simple-entity"
        })

        for _, rock in ipairs(rocks) do
            if rock and rock.valid then
                table.insert(reachable_resources, {
                    name = rock.name,
                    position = { x = rock.position.x, y = rock.position.y },
                    type = rock.type,
                    products = rock.prototype.mineable_properties.products
                })
            end
        end

        -- Find other entities (non-resources, non-trees, non-rocks) within reach_distance
        local build_reach = self.character.reach_distance
        local other_entities = surface.find_entities_filtered({
            position = position,
            radius = build_reach
        })

        for _, entity in ipairs(other_entities) do
            if entity and entity.valid
                and entity.type ~= "resource"
                and entity.type ~= "tree"
                and entity.type ~= "simple-entity"
                and entity ~= self.character then
                -- Exclude tree stumps and other tree-related corpses
                local is_tree_corpse = (entity.type == "corpse" and
                    (string.find(entity.name, "stump") or
                        string.find(entity.name, "tree")))
                if not is_tree_corpse then
                    table.insert(reachable_entities, {
                        name = entity.name,
                        position = { x = entity.position.x, y = entity.position.y },
                        type = entity.type
                    })
                end
                -- TODO: Add inventory to reachable entities using get_contents()
            end
        end

        result.reachable_resources = reachable_resources
        result.reachable_entities = reachable_entities
    end

    return result
end

function Agent:get_production_statistics()
    local stats = self.character.force.get_item_production_statistics(game.surfaces[1]);
    return {
        input = stats.input_counts,
        output = stats.output_counts,
    }
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
-- ACTIVITY STATE QUERY (for testing)
-- ============================================================================

--- Get current activity state for all async actions
--- Used by test scenarios to verify state machine progress
--- @return table Activity state {walking, mining, crafting}
function Agent:get_activity_state()
    local state = {
        walking = {
            active = false,
            path_id = nil,
            progress = 0,
            goal = nil,
            action_id = nil,
        },
        mining = {
            active = false,
            entity_name = nil,
            entity_type = nil,
            count_progress = 0,
            target_count = nil,
            action_id = nil,
        },
        crafting = {
            active = false,
            recipe = nil,
            count = 0,
            queue_length = 0,
            action_id = nil,
        },
    }
    
    -- Walking state
    if self.walking then
        local has_path = self.walking.path and #self.walking.path > 0
        local has_path_request = self.walking.path_id ~= nil
        state.walking.active = has_path or has_path_request
        state.walking.path_id = self.walking.path_id
        state.walking.progress = self.walking.progress or 0
        state.walking.goal = self.walking.goal
        state.walking.action_id = self.walking.action_id
    end
    
    -- Mining state
    if self.mining then
        local is_mining = self.character and self.character.valid and self.character.mining_state.mining
        state.mining.active = is_mining or (self.mining.action_id ~= nil)
        state.mining.entity_name = self.mining.entity_name
        state.mining.entity_type = self.mining.entity_type
        state.mining.count_progress = self.mining.count_progress or 0
        state.mining.target_count = self.mining.target_count
        state.mining.action_id = self.mining.action_id
    end
    
    -- Crafting state
    if self.crafting and self.crafting.in_progress then
        state.crafting.active = true
        state.crafting.recipe = self.crafting.in_progress.recipe
        state.crafting.count = self.crafting.in_progress.count or 0
        state.crafting.action_id = self.crafting.in_progress.action_id
    end
    
    -- Get crafting queue length from character
    if self.character and self.character.valid then
        local queue = self.character.crafting_queue
        state.crafting.queue_length = queue and #queue or 0
    end
    
    return state
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
    if not (self.character and self.character.valid) then
        return
    end
    -- Process walking jobs
    self:process_walking()

    -- Process mining
    self:process_mining()

    -- Process crafting
    self:process_crafting()

    -- Process placement jobs
    -- TODO: Implement placement job processing
    -- For now, jobs are queued but not processed
    
    -- Process reachability cache (only if dirty)
    self:process_reachable()
end

return Agent
