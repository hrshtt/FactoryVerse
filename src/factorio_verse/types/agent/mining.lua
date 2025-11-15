--- Agent mining action methods
--- Methods operate directly on Agent instances (self)
--- State is stored in self.mining (job)
--- These methods are mixed into the Agent class at module level

local MiningActions = {}

--- Start mining a resource (async)
--- @param resource_name string Resource name
--- @param position table|nil Position {x, y} (nil to use agent position with radius search)
--- @param max_count number|nil Maximum count to mine (default: 10)
--- @return table Result with {success, queued, action_id, tick}
function MiningActions.mine_resource(self, resource_name, position, max_count)
    if not (self.entity and self.entity.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    if not resource_name or type(resource_name) ~= "string" then
        error("Agent: resource_name (string) is required")
    end
    
    -- Validate: cannot mine oil
    if string.find(resource_name:lower(), "oil") then
        error("Agent: Cannot mine oil resources")
    end
    
    max_count = max_count or 10
    
    -- Resolve position (use agent position if not provided)
    local search_position = position
    if not search_position then
        local agent_pos = self.entity.position
        search_position = { x = agent_pos.x, y = agent_pos.y }
    end
    
    -- Resource type mappings
    local resource_type_mapping = {
        ["tree"] = "tree",
        ["rock"] = "simple-entity",
    }
    
    local resource_item_mapping = {
        ["tree"] = "wood",
        ["rock"] = "stone",
    }
    
    -- Build search arguments
    local is_point_entity = (resource_name == "tree" or resource_name == "rock")
    local radius = self.entity.resource_reach_distance or 2.5
    local search_args = {}
    
    if is_point_entity then
        search_args.type = resource_type_mapping[resource_name]
        search_args.position = search_position
        search_args.radius = radius
    else
        search_args.name = resource_name
        search_args.position = search_position
        search_args.radius = radius
    end
    
    -- Find resource entity
    local surface = self.entity.surface or game.surfaces[1]
    local resource_entity = surface.find_entities_filtered(search_args)[1]
    
    if not resource_entity or not resource_entity.valid then
        error("Agent: Resource not found")
    end
    
    -- Validate reachability
    local agent_pos = self.entity.position
    local resource_pos = resource_entity.position
    local dx = resource_pos.x - agent_pos.x
    local dy = resource_pos.y - agent_pos.y
    local dist_sq = dx * dx + dy * dy
    local reach = self.entity.resource_reach_distance or 2.5
    
    if dist_sq > (reach * reach) then
        error("Agent: Resource out of reach")
    end
    
    -- Determine item name and initial count
    local item_name = nil
    local initial_count = 0
    
    if is_point_entity then
        item_name = resource_item_mapping[resource_name]
        initial_count = self.entity.get_item_count(item_name)
    else
        item_name = resource_name
        initial_count = self.entity.get_item_count(item_name)
    end
    
    -- Generate action ID
    local action_id = string.format("mine_resource_%d_%d", game.tick, self.agent_id)
    local rcon_tick = game.tick
    
    -- Create mining job
    local job = {
        resource_name = resource_name,
        resource_entity = resource_entity,  -- Store reference (will be validated each tick)
        resource_position = { x = resource_pos.x, y = resource_pos.y },
        item_name = item_name,
        initial_count = initial_count,
        target_count = initial_count + max_count,
        mine_till_depleted = (resource_entity.type == "tree" or resource_entity.type == "simple-entity"),
        action_id = action_id,
        start_tick = rcon_tick,
        cancelled = false,
    }
    
    -- Store job
    self.mining.job = job
    
    -- Start mining on entity
    self:set_mining(true, resource_entity)
    
    -- Enqueue async result message
    self:enqueue_message({
        action = "mine_resource",
        agent_id = self.agent_id,
        success = true,
        queued = true,
        action_id = action_id,
        tick = rcon_tick,
        resource_name = resource_name,
        position = { x = resource_pos.x, y = resource_pos.y },
    }, "mining")
    
    return {
        success = true,
        queued = true,
        action_id = action_id,
        tick = rcon_tick,
    }
end

--- Cancel active mining
--- @return table Result
function MiningActions.cancel_mining(self)
    if not (self.entity and self.entity.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    local job = self.mining.job
    local action_id = job and job.action_id or nil
    
    -- Clear job
    self.mining.job = nil
    
    -- Stop mining on entity
    self:set_mining(false, nil)
    
    -- Enqueue cancel message
    self:enqueue_message({
        action = "cancel_mining",
        agent_id = self.agent_id,
        success = true,
        cancelled = job ~= nil,
        action_id = action_id,
        tick = game.tick or 0,
    }, "mining")
    
    return {
        success = true,
        cancelled = job ~= nil,
        action_id = action_id,
    }
end

--- Set mining state on entity (internal helper)
--- @param mining boolean
--- @param target table|LuaEntity|nil Target position or entity
function MiningActions.set_mining(self, mining, target)
    if not (self.entity and self.entity.valid) then return end
    
    if mining then
        -- Exclusivity: stop walking
        self:stop_walking()
        
        local pos = target and (target.position or target) or nil
        if pos then
            self.entity.mining_state = { mining = true, position = { x = pos.x, y = pos.y } }
        else
            self.entity.mining_state = { mining = true }
        end
        
        -- Set selected entity if target is an entity
        if target and target.valid == true then
            self.entity.selected = target
        end
    else
        self.entity.mining_state = { mining = false }
        self.entity.clear_selected_entity()
    end
end

return MiningActions

