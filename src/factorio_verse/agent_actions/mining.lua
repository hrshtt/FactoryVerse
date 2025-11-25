--- Agent mining action methods
--- Methods operate directly on Agent instances (self)
--- State is stored in self.mining (count_progress, target_count, mine_entity)
--- These methods are mixed into the Agent class at module level

local MiningActions = {}

--- Resource type mappings for trees/rocks
local RESOURCE_TYPE_MAP = {
    ["tree"] = "tree",
    ["rock"] = "simple-entity",
}

--- Resource item mappings for trees/rocks
local RESOURCE_ITEM_MAP = {
    ["tree"] = "wood",
    ["rock"] = "stone",
}

--- Calculate estimated mining time in ticks
--- @param mining_speed number Mining speed
--- @param resource_entity LuaEntity Resource entity to mine
--- @param count number|nil Number of entities to mine (only used for ores, ignored for trees/rocks)
--- @return number|nil Estimated ticks (nil if cannot calculate)
local function calculate_mining_time_ticks(mining_speed, resource_entity, count)
    
    local proto = resource_entity.prototype
    if not proto or not proto.mineable_properties then
        return nil
    end
    
    local mineable_props = proto.mineable_properties
    local mining_time_seconds = mineable_props.mining_time  -- Base time in seconds at speed 1.0
    
    -- Validate mining_time exists and is positive
    if not mining_time_seconds or mining_time_seconds <= 0 then
        return nil
    end
    
    -- Calculate ticks to mine one entity: (mining_time_seconds / mining_speed) * 60
    local ticks_per_entity = (mining_time_seconds / mining_speed) * 60
    
    -- For ores: multiply by count if specified
    if count and count > 1 then
        return math.ceil(ticks_per_entity * count)
    end
    
    -- For trees/rocks or single ore: just return time for one entity
    return math.ceil(ticks_per_entity)
end

--- Start mining a resource (async)
--- @param resource_name string Resource name (e.g., "iron-ore", "tree", "rock")
--- @param max_count number|nil Maximum count to mine (only for ores/coal/stone, ignored for trees/rocks)
--- @return table Result with {success, queued, action_id, tick}
function MiningActions.mine_resource(self, resource_name, max_count)
    if not resource_name or type(resource_name) ~= "string" then
        error("Agent: resource_name (string) is required")
    end
    
    -- Validate: cannot mine oil
    if string.find(resource_name:lower(), "oil") then
        error("Agent: Cannot mine oil resources")
    end
    
    -- Use agent position and resource reach distance for search
    local agent_pos = self.character.position
    local radius = self.character.resource_reach_distance or 2.5
    local surface = self.character.surface or game.surfaces[1]
    
    -- Determine if this is a tree/rock (point entity) or ore/coal/stone
    local is_point_entity = (resource_name == "tree" or resource_name == "rock")
    
    -- For trees/rocks, ignore max_count parameter
    if is_point_entity then
        max_count = nil
    end
    
    local search_args = {
        position = { x = agent_pos.x, y = agent_pos.y },
        radius = radius,
    }
    
    if is_point_entity then
        search_args.type = RESOURCE_TYPE_MAP[resource_name]
    else
        search_args.name = resource_name
    end
    
    -- Find resource entity (not strict - take first result)
    local entities = surface.find_entities_filtered(search_args)
    if not entities or #entities == 0 then
        error("Agent: Resource not found within reach")
    end
    
    local resource_entity = entities[1]
    if not resource_entity or not resource_entity.valid then
        error("Agent: Resource entity is invalid")
    end
    
    -- Determine item name
    local item_name = is_point_entity and RESOURCE_ITEM_MAP[resource_name] or resource_name
    
    -- Initialize mining state
    local current_count = self.character.get_item_count(item_name)
    self.mining.count_progress = current_count
    self.mining.mine_entity = resource_entity
    self.mining.item_name = item_name  -- Store for completion message
    self.mining.start_tick = game.tick  -- Store start tick for actual time calculation
    
    -- Set target_count only for ores/coal/stone (not trees/rocks)
    if is_point_entity then
        self.mining.target_count = nil  -- Mine until depleted
    else
        max_count = max_count or 10
        self.mining.target_count = current_count + max_count
    end
    
    -- Start mining on entity (stop walking, set mining state)
    if self.character.walking_state and self.character.walking_state.walking then
        self.character.walking_state = { walking = false }
    end
    
    self.character.mining_state = {
        mining = true,
        position = { x = resource_entity.position.x, y = resource_entity.position.y }
    }
    self.character.selected = resource_entity
    
    -- Generate action ID and enqueue message
    local action_id = string.format("mine_resource_%d_%d", game.tick, self.agent_id)
    local rcon_tick = game.tick
    
    -- Calculate estimated mining time
    -- For trees/rocks, ignore max_count and only calculate time for one entity
    -- For ores, use max_count if provided
    local count_for_calculation = is_point_entity and nil or max_count
    local estimated_ticks = calculate_mining_time_ticks(
        self.character.prototype.mining_speed,
        resource_entity,
        count_for_calculation
    )
    
    -- Get products from mineable_properties
    local products = nil
    local proto = resource_entity.prototype
    if proto and proto.mineable_properties and proto.mineable_properties.products then
        products = proto.mineable_properties.products
    end
    
    self:enqueue_message({
        action = "mine_resource",
        agent_id = self.agent_id,
        success = true,
        queued = true,
        action_id = action_id,
        tick = rcon_tick,
        resource_name = resource_name,
        position = { x = resource_entity.position.x, y = resource_entity.position.y },
        estimated_ticks = estimated_ticks,
        products = products,
    }, "mining")
    
    return {
        success = true,
        queued = true,
        action_id = action_id,
        tick = rcon_tick,
        estimated_ticks = estimated_ticks,
        products = products,
    }
end

--- Cancel active mining
--- @return table Result
function MiningActions.stop_mining(self)
    local was_mining = (self.mining.mine_entity ~= nil)
    
    -- Clear mining state
    self.mining.count_progress = 0
    self.mining.target_count = nil
    self.mining.mine_entity = nil
    self.mining.item_name = nil
    self.mining.start_tick = nil
    
    -- Stop mining on entity
    if self.character.mining_state then
        self.character.mining_state = { mining = false }
    end
    if self.character.clear_selected_entity then
        self.character.clear_selected_entity()
    end
    
    -- Enqueue cancel message
    self:enqueue_message({
        action = "cancel_mining",
        agent_id = self.agent_id,
        success = true,
        cancelled = was_mining,
        tick = game.tick or 0,
    }, "mining")
    
    return {
        success = true,
        cancelled = was_mining,
    }
end

--- Process mining state (called from Agent:process())
function MiningActions.process_mining(self)
    if not self.mining.mine_entity then
        return
    end
    
    local entity = self.mining.mine_entity
    
    -- Check if entity is still valid (for trees/rocks, invalid means depleted)
    if not entity.valid then
        -- Entity depleted - complete mining
        self:complete_mining()
        return
    end
    
    -- For ores/coal/stone: check if target count reached
    if self.mining.target_count then
        -- Determine item name from entity type
        local item_name = nil
        if entity.type == "resource" then
            item_name = entity.name  -- e.g., "iron-ore", "copper-ore"
        elseif entity.type == "tree" then
            item_name = "wood"
        elseif entity.type == "simple-entity" then
            item_name = "stone"
        end
        
        if item_name then
            local current_count = self.character.get_item_count(item_name)
            self.mining.count_progress = current_count
            
            if current_count >= self.mining.target_count then
                -- Target count reached - complete mining
                self:complete_mining()
                return
            end
        end
    end
    -- For trees/rocks: continue mining until entity becomes invalid (depleted)
end

--- Complete mining and send completion message
function MiningActions.complete_mining(self)
    if not self.mining.mine_entity then
        return
    end
    
    local entity = self.mining.mine_entity
    local item_name = self.mining.item_name
    local was_valid = entity.valid
    
    -- Determine resource name from entity if still valid, otherwise infer from item_name
    local resource_name = nil
    if was_valid then
        if entity.type == "resource" then
            resource_name = entity.name
        elseif entity.type == "tree" then
            resource_name = "tree"
        elseif entity.type == "simple-entity" then
            resource_name = "rock"
        end
    else
        -- Infer from item_name
        if item_name == "wood" then
            resource_name = "tree"
        elseif item_name == "stone" then
            resource_name = "rock"
        else
            resource_name = item_name  -- For ores, item_name == resource_name
        end
    end
    
    local current_count = item_name and self.character.get_item_count(item_name) or 0
    local initial_count = self.mining.count_progress or 0
    local mined_count = current_count - initial_count
    
    -- Calculate actual time taken
    local actual_ticks = nil
    if self.mining.start_tick then
        actual_ticks = (game.tick or 0) - self.mining.start_tick
    end
    
    -- Send completion message
    self:enqueue_message({
        action = "mine_resource",
        agent_id = self.agent_id,
        success = true,
        tick = game.tick or 0,
        resource_name = resource_name,
        position = was_valid and { x = entity.position.x, y = entity.position.y } or nil,
        item_name = item_name,
        count = mined_count,
        actual_ticks = actual_ticks,
    }, "mining")
    
    -- Clear mining state
    self.mining.count_progress = 0
    self.mining.target_count = nil
    self.mining.mine_entity = nil
    self.mining.item_name = nil
    
    -- Stop mining on entity
    if self.character.mining_state then
        self.character.mining_state = { mining = false }
    end
    if self.character.clear_selected_entity then
        self.character.clear_selected_entity()
    end
end

return MiningActions
