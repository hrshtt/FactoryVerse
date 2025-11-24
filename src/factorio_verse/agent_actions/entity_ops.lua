--- Agent entity operation methods (using EntityInterface)
--- Methods operate directly on Agent instances (self)
--- Uses EntityInterface for low-level entity operations
--- These methods are mixed into the Agent class at module level

local EntityInterface = require("EntityInterface")

local EntityOpsActions = {}

--- Helper to resolve entity position (use agent position with default radius if not provided)
--- @param position table|nil Position {x, y} or nil to use agent position
--- @param default_radius number|nil Default radius for search (default: 5.0)
--- @return table Position {x, y}
--- @return number|nil Radius (nil for exact lookup)
local function _resolve_entity_position(self, position, default_radius)
    if position then
        return position, nil  -- Exact lookup
    end
    
    -- Use agent position with default radius
    if not (self.entity and self.entity.valid) then
        error("Agent: Cannot resolve entity position - agent entity is invalid")
    end
    
    local agent_pos = self.entity.position
    return { x = agent_pos.x, y = agent_pos.y }, (default_radius or 5.0)
end

--- Helper to validate agent can reach entity
--- @param self Agent
--- @param entity LuaEntity
--- @return boolean
local function _can_reach_entity(self, entity)
    if not (self.entity and self.entity.valid) then
        return false
    end
    
    local agent_pos = self.entity.position
    local entity_pos = entity.position
    
    -- Check reach distance (default character reach: 2.5 tiles)
    local dx = entity_pos.x - agent_pos.x
    local dy = entity_pos.y - agent_pos.y
    local distance = math.sqrt(dx * dx + dy * dy)
    
    -- Character reach is typically 2.5, but we'll use 3.0 for safety
    return distance <= self.entity.reach_distance
end

--- Helper to validate recipe is accessible to agent's force
--- @param recipe_name string Recipe name
--- @return boolean
local function _can_use_recipe(self, recipe_name)
    if not (self.entity and self.entity.valid) then
        return false
    end
    
    local force = self.entity.force
    if not force then
        return false
    end
    
    -- Check if recipe is available to force
    local recipe = force.recipes[recipe_name]
    return recipe ~= nil and recipe.enabled
end

--- Set recipe on entity
--- @param entity_name string Entity prototype name
--- @param position table|nil Position {x, y} (nil to use agent position with radius search)
--- @param recipe_name string|nil Recipe name (nil to clear recipe)
--- @return table Result
function EntityOpsActions.set_entity_recipe(self, entity_name, position, recipe_name)
    if not (self.entity and self.entity.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    -- Resolve entity position
    local pos, radius = _resolve_entity_position(self, position, 5.0)
    
    -- Create EntityInterface instance
    local entity_interface = EntityInterface:new(entity_name, pos, radius, true)
    local entity = entity_interface.entity
    
    -- Validate agent can reach entity
    if not _can_reach_entity(self, entity) then
        error("Agent: Entity is out of reach")
    end
    
    -- Validate recipe is accessible to agent's force (if setting a recipe)
    if recipe_name and not _can_use_recipe(self, recipe_name) then
        error("Agent: Recipe '" .. recipe_name .. "' is not available to agent's force")
    end
    
    -- Set recipe via EntityInterface
    entity_interface:set_recipe(recipe_name, true)  -- Allow overwrite
    
    -- Enqueue completion message (sync action)
    self:enqueue_message({
        action = "set_entity_recipe",
        agent_id = self.agent_id,
        entity_name = entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        recipe_name = recipe_name,
        tick = game.tick or 0,
    }, "entity_ops")
    
    return {
        success = true,
        entity_name = entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        recipe_name = recipe_name,
    }
end

--- Set filter on entity inventory
--- @param entity_name string Entity prototype name
--- @param position table|nil Position {x, y} (nil to use agent position with radius search)
--- @param inventory_type number|string Inventory type
--- @param filter_index number|nil Filter slot index (nil for all slots)
--- @param filter_item string|nil Item name to filter (nil to clear filter)
--- @return table Result
function EntityOpsActions.set_entity_filter(self, entity_name, position, inventory_type, filter_index, filter_item)
    if not (self.entity and self.entity.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    -- Resolve entity position
    local pos, radius = _resolve_entity_position(self, position, 5.0)
    
    -- Create EntityInterface instance
    local entity_interface = EntityInterface:new(entity_name, pos, radius, true)
    local entity = entity_interface.entity
    
    -- Validate agent can reach entity
    if not _can_reach_entity(self, entity) then
        error("Agent: Entity is out of reach")
    end
    
    -- Set filter via EntityInterface
    entity_interface:set_filter(inventory_type, filter_index, filter_item)
    
    -- Enqueue completion message (sync action)
    self:enqueue_message({
        action = "set_entity_filter",
        agent_id = self.agent_id,
        entity_name = entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        inventory_type = inventory_type,
        filter_index = filter_index,
        filter_item = filter_item,
        tick = game.tick or 0,
    }, "entity_ops")
    
    return {
        success = true,
        entity_name = entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        inventory_type = inventory_type,
        filter_index = filter_index,
        filter_item = filter_item,
    }
end

--- Set inventory limit on entity
--- @param entity_name string Entity prototype name
--- @param position table|nil Position {x, y} (nil to use agent position with radius search)
--- @param inventory_type number|string Inventory type
--- @param limit number|nil Limit to set (nil to clear limit)
--- @return table Result
function EntityOpsActions.set_inventory_limit(self, entity_name, position, inventory_type, limit)
    if not (self.entity and self.entity.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    -- Resolve entity position
    local pos, radius = _resolve_entity_position(self, position, 5.0)
    
    -- Create EntityInterface instance
    local entity_interface = EntityInterface:new(entity_name, pos, radius, true)
    local entity = entity_interface.entity
    
    -- Validate agent can reach entity
    if not _can_reach_entity(self, entity) then
        error("Agent: Entity is out of reach")
    end
    
    -- Set limit via EntityInterface
    entity_interface:set_inventory_limit(inventory_type, limit)
    
    -- Enqueue completion message (sync action)
    self:enqueue_message({
        action = "set_inventory_limit",
        agent_id = self.agent_id,
        entity_name = entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        inventory_type = inventory_type,
        limit = limit,
        tick = game.tick or 0,
    }, "entity_ops")
    
    return {
        success = true,
        entity_name = entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        inventory_type = inventory_type,
        limit = limit,
    }
end

--- Get item from entity inventory (transfers to agent inventory)
--- @param entity_name string Entity prototype name
--- @param position table|nil Position {x, y} (nil to use agent position with radius search)
--- @param inventory_type number|string Inventory type
--- @param item_name string Item name to get
--- @param count number|nil Count to get (default: all available)
--- @return table Result
function EntityOpsActions.get_inventory_item(self, entity_name, position, inventory_type, item_name, count)
    if not (self.entity and self.entity.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    -- Resolve entity position
    local pos, radius = _resolve_entity_position(self, position, 5.0)
    
    -- Create EntityInterface instance
    local entity_interface = EntityInterface:new(entity_name, pos, radius, true)
    local entity = entity_interface.entity
    
    -- Validate agent can reach entity
    if not _can_reach_entity(self, entity) then
        error("Agent: Entity is out of reach")
    end
    
    -- Get agent's main inventory
    local agent_inventory = self.entity.get_inventory(defines.inventory.character_main)
    if not agent_inventory then
        error("Agent: Agent inventory is invalid")
    end
    
    -- Resolve inventory type to defines.inventory constant
    local inv_index = inventory_type
    if type(inventory_type) == "string" then
        local inv_map = {
            chest = defines.inventory.chest,
            fuel = defines.inventory.fuel,
            input = defines.inventory.assembling_machine_input,
            output = defines.inventory.assembling_machine_output,
        }
        inv_index = inv_map[inventory_type]
        if not inv_index then
            error("Agent: Unknown inventory type name: " .. inventory_type)
        end
    end
    
    -- Get entity inventory
    local entity_inventory = entity.get_inventory(inv_index)
    if not entity_inventory then
        error("Agent: Entity inventory is invalid")
    end
    
    -- Get available count
    local available_count = entity_inventory.get_item_count(item_name)
    if available_count == 0 then
        error("Agent: Item '" .. item_name .. "' not found in entity inventory")
    end
    
    -- Determine transfer count
    local transfer_count = count or available_count
    if transfer_count > available_count then
        transfer_count = available_count
    end
    
    -- Check agent inventory space
    local can_insert = agent_inventory.can_insert({ name = item_name, count = transfer_count })
    if not can_insert then
        error("Agent: Cannot insert item into agent inventory (insufficient space)")
    end
    
    -- Transfer items
    local removed = entity_inventory.remove({ name = item_name, count = transfer_count })
    if removed > 0 then
        local inserted = agent_inventory.insert({ name = item_name, count = removed })
        if inserted < removed then
            -- Rollback: put remaining items back
            entity_inventory.insert({ name = item_name, count = removed - inserted })
            error("Agent: Partial transfer failed - only " .. inserted .. " of " .. removed .. " items inserted")
        end
    end
    
    -- Enqueue completion message (sync action)
    self:enqueue_message({
        action = "get_inventory_item",
        agent_id = self.agent_id,
        entity_name = entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        inventory_type = inventory_type,
        item_name = item_name,
        count = transfer_count,
        tick = game.tick or 0,
    }, "entity_ops")
    
    return {
        success = true,
        entity_name = entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        inventory_type = inventory_type,
        item_name = item_name,
        count = transfer_count,
    }
end

--- Set item in entity inventory (transfers from agent inventory)
--- @param entity_name string Entity prototype name
--- @param position table|nil Position {x, y} (nil to use agent position with radius search)
--- @param inventory_type number|string Inventory type
--- @param item_name string Item name to set
--- @param count number Count to set
--- @return table Result
function EntityOpsActions.set_inventory_item(self, entity_name, position, inventory_type, item_name, count)
    if not (self.entity and self.entity.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    if not count or count <= 0 then
        error("Agent: Count must be positive")
    end
    
    -- Resolve entity position
    local pos, radius = _resolve_entity_position(self, position, 5.0)
    
    -- Create EntityInterface instance
    local entity_interface = EntityInterface:new(entity_name, pos, radius, true)
    local entity = entity_interface.entity
    
    -- Validate agent can reach entity
    if not _can_reach_entity(self, entity) then
        error("Agent: Entity is out of reach")
    end
    
    -- Get agent's main inventory
    local agent_inventory = self.entity.get_inventory(defines.inventory.character_main)
    if not agent_inventory then
        error("Agent: Agent inventory is invalid")
    end
    
    -- Check agent has items
    local available_count = agent_inventory.get_item_count(item_name)
    if available_count < count then
        error("Agent: Insufficient items in agent inventory (have " .. available_count .. ", need " .. count .. ")")
    end
    
    -- Resolve inventory type to defines.inventory constant
    local inv_index = inventory_type
    if type(inventory_type) == "string" then
        local inv_map = {
            chest = defines.inventory.chest,
            fuel = defines.inventory.fuel,
            input = defines.inventory.assembling_machine_input,
            output = defines.inventory.assembling_machine_output,
        }
        inv_index = inv_map[inventory_type]
        if not inv_index then
            error("Agent: Unknown inventory type name: " .. inventory_type)
        end
    end
    
    -- Get entity inventory
    local entity_inventory = entity.get_inventory(inv_index)
    if not entity_inventory then
        error("Agent: Entity inventory is invalid")
    end
    
    -- Check entity inventory space
    local can_insert = entity_inventory.can_insert({ name = item_name, count = count })
    if not can_insert then
        error("Agent: Cannot insert item into entity inventory (insufficient space)")
    end
    
    -- Transfer items
    local removed = agent_inventory.remove({ name = item_name, count = count })
    if removed > 0 then
        local inserted = entity_inventory.insert({ name = item_name, count = removed })
        if inserted < removed then
            -- Rollback: put remaining items back
            agent_inventory.insert({ name = item_name, count = removed - inserted })
            error("Agent: Partial transfer failed - only " .. inserted .. " of " .. removed .. " items inserted")
        end
    end
    
    -- Enqueue completion message (sync action)
    self:enqueue_message({
        action = "set_inventory_item",
        agent_id = self.agent_id,
        entity_name = entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        inventory_type = inventory_type,
        item_name = item_name,
        count = count,
        tick = game.tick or 0,
    }, "entity_ops")
    
    return {
        success = true,
        entity_name = entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        inventory_type = inventory_type,
        item_name = item_name,
        count = count,
    }
end

--- Pick up an entity (transfers to agent inventory)
--- @param entity_name string Entity prototype name
--- @param position table|nil Position {x, y} (nil to use agent position with radius search)
--- @return table Result
function EntityOpsActions.pickup_entity(self, entity_name, position)
    if not (self.entity and self.entity.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    -- Resolve entity position
    local pos, radius = _resolve_entity_position(self, position, 5.0)
    
    -- Create EntityInterface instance
    local entity_interface = EntityInterface:new(entity_name, pos, radius, true)
    local entity = entity_interface.entity
    
    -- Validate agent can reach entity
    if not _can_reach_entity(self, entity) then
        error("Agent: Entity is out of reach")
    end
    
    -- Check if entity can be picked up
    if not entity_interface:can_pickup() then
        error("Agent: Entity cannot be picked up")
    end
    
    -- Get agent's main inventory
    local agent_inventory = self.entity.get_inventory(defines.inventory.character_main)
    if not agent_inventory then
        error("Agent: Agent inventory is invalid")
    end
    
    -- Extract items from entity (if it has inventory)
    local extracted_items = entity_interface:extract_inventory_items()
    
    -- Transfer extracted items to agent inventory
    local transferred = {}
    for item_name, count in pairs(extracted_items) do
        if count > 0 then
            local inserted = agent_inventory.insert({ name = item_name, count = count })
            if inserted > 0 then
                transferred[item_name] = inserted
            end
        end
    end
    
    -- Destroy entity
    local entity_pos = { x = entity.position.x, y = entity.position.y }
    entity.destroy()
    
    -- Enqueue completion message (sync action)
    self:enqueue_message({
        action = "pickup_entity",
        agent_id = self.agent_id,
        entity_name = entity_name,
        position = entity_pos,
        extracted_items = transferred,
        tick = game.tick or 0,
    }, "entity_ops")
    
    return {
        success = true,
        entity_name = entity_name,
        position = entity_pos,
        extracted_items = transferred,
    }
end

return EntityOpsActions

