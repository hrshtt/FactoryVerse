--- Agent entity operation methods (using EntityInterface)
--- Methods operate directly on Agent instances (self)
--- Uses EntityInterface for low-level entity operations
--- These methods are mixed into the Agent class at module level

local EntityInterface = require("game_state.EntityInterface")
local custom_events = require("utils.custom_events")
local utils = require("utils.utils")

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
    if not (self.character and self.character.valid) then
        error("Agent: Cannot resolve entity position - agent entity is invalid")
    end
    
    local agent_pos = self.character.position
    return { x = agent_pos.x, y = agent_pos.y }, (default_radius or 5.0)
end


--- Helper to validate recipe is accessible to agent's force
--- @param recipe_name string Recipe name
--- @return boolean
local function _can_use_recipe(self, recipe_name)
    if not (self.character and self.character.valid) then
        return false
    end
    
    local force = self.character.force
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
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    -- Resolve entity position
    local pos, radius = _resolve_entity_position(self, position, 5.0)
    
    -- Create EntityInterface instance
    local entity_interface = EntityInterface:new(entity_name, pos, radius, true)
    local entity = entity_interface.entity
    
    -- Validate agent can reach entity
    if not self:can_reach_entity(entity) then
        error("Agent: Entity is out of reach")
    end
    
    -- Validate recipe is accessible to agent's force (if setting a recipe)
    if recipe_name and not _can_use_recipe(self, recipe_name) then
        error("Agent: Recipe '" .. recipe_name .. "' is not available to agent's force")
    end
    
    -- Set recipe via EntityInterface
    entity_interface:set_recipe(recipe_name, true)  -- Allow overwrite
    
    -- Raise agent entity configuration changed event
    script.raise_event(custom_events.on_agent_entity_configuration_changed, {
        entity = entity,
        agent_id = self.agent_id,
        change_type = "recipe",
        new_value = recipe_name,
    })
    
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
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    -- Resolve entity position
    local pos, radius = _resolve_entity_position(self, position, 5.0)
    
    -- Create EntityInterface instance
    local entity_interface = EntityInterface:new(entity_name, pos, radius, true)
    local entity = entity_interface.entity
    
    -- Validate agent can reach entity
    if not self:can_reach_entity(entity) then
        error("Agent: Entity is out of reach")
    end
    
    -- Set filter via EntityInterface
    entity_interface:set_filter(inventory_type, filter_index, filter_item)
    
    -- Raise agent entity configuration changed event
    script.raise_event(custom_events.on_agent_entity_configuration_changed, {
        entity = entity,
        agent_id = self.agent_id,
        change_type = "filter",
        inventory_type = inventory_type,
        filter_index = filter_index,
        new_value = filter_item,
    })
    
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
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    -- Resolve entity position
    local pos, radius = _resolve_entity_position(self, position, 5.0)
    
    -- Create EntityInterface instance
    local entity_interface = EntityInterface:new(entity_name, pos, radius, true)
    local entity = entity_interface.entity
    
    -- Validate agent can reach entity
    if not self:can_reach_entity(entity) then
        error("Agent: Entity is out of reach")
    end
    
    -- Set limit via EntityInterface
    entity_interface:set_inventory_limit(inventory_type, limit)
    
    -- Raise agent entity configuration changed event
    script.raise_event(custom_events.on_agent_entity_configuration_changed, {
        entity = entity,
        agent_id = self.agent_id,
        change_type = "inventory_limit",
        inventory_type = inventory_type,
        new_value = limit,
    })
    
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
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    -- Resolve entity position
    local pos, radius = _resolve_entity_position(self, position, 5.0)
    
    -- Create EntityInterface instance
    local entity_interface = EntityInterface:new(entity_name, pos, radius, true)
    local entity = entity_interface.entity
    
    -- Validate agent can reach entity
    if not self:can_reach_entity(entity) then
        error("Agent: Entity is out of reach")
    end
    
    -- Get agent's main inventory
    local agent_inventory = self.character.get_main_inventory()
    if not agent_inventory then
        error("Agent: Agent inventory is invalid")
    end
    
    -- Resolve inventory type to defines.inventory constant
    local inv_index = inventory_type
    local entity_inventory = nil
    
    -- Special handling for mining drills: use get_output_inventory() for output
    if type(inventory_type) == "string" and inventory_type == "output" and entity.type == "mining-drill" then
        entity_inventory = entity.get_output_inventory()
        if not entity_inventory then
            error("Agent: Mining drill output inventory is invalid")
        end
    else
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
        entity_inventory = entity.get_inventory(inv_index)
        if not entity_inventory then
            error("Agent: Entity inventory is invalid")
        end
    end
    
    -- Handle empty item_name: take all items
    if item_name == "" or item_name == nil then
        local contents_raw = entity_inventory.get_contents()
        if not contents_raw or next(contents_raw) == nil then
            error("Agent: No items found in entity inventory")
        end
        
        -- get_contents() returns an array of {name, count, quality} objects
        -- Convert to {item_name = count} format
        local contents = {}
        for _, item in pairs(contents_raw) do
            local item_name_in_inv = item.name or item[1]
            local item_count = item.count or item[2]
            if item_name_in_inv and item_count and item_count > 0 then
                contents[item_name_in_inv] = (contents[item_name_in_inv] or 0) + item_count
            end
        end
        
        if next(contents) == nil then
            error("Agent: No items found in entity inventory")
        end
        
        local results = {}
        local total_transferred = 0
        
        -- Iterate through all items in inventory
        for item_name_in_inv, item_count in pairs(contents) do
            local transfer_count = count or item_count
            if transfer_count > item_count then
                transfer_count = item_count
            end
            
            -- Special handling: leave at least 1 coal in mining drill output
            if entity.type == "mining-drill" and type(inventory_type) == "string" and inventory_type == "output" and item_name_in_inv == "coal" then
                -- Ensure at least 1 coal remains
                if item_count - transfer_count < 1 then
                    transfer_count = math.max(0, item_count - 1)  -- Leave at least 1
                end
                if transfer_count <= 0 then
                    -- Skip if we can't take any without leaving at least 1
                    goto continue
                end
            end
            
            -- Check agent inventory space
            local can_insert = agent_inventory.can_insert({ name = item_name_in_inv, count = transfer_count })
            if can_insert then
                -- Transfer items
                local removed = entity_inventory.remove({ name = item_name_in_inv, count = transfer_count })
                if removed > 0 then
                    local inserted = agent_inventory.insert({ name = item_name_in_inv, count = removed })
                    if inserted < removed then
                        -- Rollback: put remaining items back
                        entity_inventory.insert({ name = item_name_in_inv, count = removed - inserted })
                        error("Agent: Partial transfer failed for " .. item_name_in_inv .. " - only " .. inserted .. " of " .. removed .. " items inserted")
                    end
                    total_transferred = total_transferred + inserted
                    table.insert(results, {
                        item_name = item_name_in_inv,
                        count = inserted
                    })
                end
            end
            ::continue::
        end
        
        if total_transferred == 0 then
            error("Agent: Could not transfer any items (insufficient space or no items)")
        end
        
        -- Enqueue completion message (sync action)
        self:enqueue_message({
            action = "get_inventory_item",
            agent_id = self.agent_id,
            entity_name = entity_name,
            position = { x = entity.position.x, y = entity.position.y },
            inventory_type = inventory_type,
            item_name = "",  -- Empty indicates "all items"
            count = total_transferred,
            tick = game.tick or 0,
        }, "entity_ops")
        
        return {
            success = true,
            entity_name = entity_name,
            position = { x = entity.position.x, y = entity.position.y },
            inventory_type = inventory_type,
            item_name = "",  -- Empty indicates "all items"
            count = total_transferred,
            items = results,  -- List of items transferred
        }
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
    
    -- Special handling: leave at least 1 coal in mining drill output
    if entity.type == "mining-drill" and type(inventory_type) == "string" and inventory_type == "output" and item_name == "coal" then
        -- Ensure at least 1 coal remains
        if available_count - transfer_count < 1 then
            transfer_count = math.max(0, available_count - 1)  -- Leave at least 1
        end
        if transfer_count <= 0 then
            error("Agent: Cannot take coal from mining drill output - must leave at least 1 coal")
        end
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
    if not (self.character and self.character.valid) then
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
    if not self:can_reach_entity(entity) then
        error("Agent: Entity is out of reach")
    end
    
    -- Get agent's main inventory
    local agent_inventory = self.character.get_main_inventory()
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
    local entity_inventory = nil
    
    -- Special handling for mining drills: use get_output_inventory() for output
    if type(inventory_type) == "string" and inventory_type == "output" and entity.type == "mining-drill" then
        entity_inventory = entity.get_output_inventory()
        if not entity_inventory then
            error("Agent: Mining drill output inventory is invalid")
        end
    else
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
        entity_inventory = entity.get_inventory(inv_index)
        if not entity_inventory then
            error("Agent: Entity inventory is invalid")
        end
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
--- @param self Agent
--- @param entity_name string Entity prototype name
--- @param position table|nil Position {x, y} (nil to use agent position with radius search)
--- @return table Result
function EntityOpsActions.pickup_entity(self, entity_name, position)
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    -- Resolve entity position
    local pos, radius = _resolve_entity_position(self, position, 5.0)
    
    -- Create EntityInterface instance
    local entity_interface = EntityInterface:new(entity_name, pos, radius, true)
    local entity = entity_interface.entity
    
    -- Validate agent can reach entity
    if not self:can_reach_entity(entity) then
        error("Agent: Entity is out of reach")
    end
    
    -- Check if entity can be picked up
    if not entity.minable then
        error("Agent: Entity is not minable")
    end
    
    -- Get agent's main inventory
    local agent_inventory = self.character.get_main_inventory()
    if not agent_inventory then
        error("Agent: Agent inventory is invalid")
    end

    -- get_contents() returns an array of {name, count, quality} objects
    -- Convert to {item_name = count} format
    local before_contents_raw = agent_inventory.get_contents()
    local before_contents = {}
    if before_contents_raw then
        for _, item in pairs(before_contents_raw) do
            local item_name = item.name or item[1]
            local count = item.count or item[2]
            if item_name and count then
                before_contents[item_name] = (before_contents[item_name] or 0) + count
            end
        end
    end

    -- Mine entity
    self.character.mine_entity(entity)

    -- get_contents() returns an array of {name, count, quality} objects
    -- Convert to {item_name = count} format
    local after_contents_raw = agent_inventory.get_contents()
    local after_contents = {}
    if after_contents_raw then
        for _, item in pairs(after_contents_raw) do
            local item_name = item.name or item[1]
            local count = item.count or item[2]
            if item_name and count then
                after_contents[item_name] = (after_contents[item_name] or 0) + count
            end
        end
    end

    -- Calculate transferred items (items that were added)
    local transferred = {}
    -- Check all items in after_contents
    for item_name, after_count in pairs(after_contents) do
        local before_count = before_contents[item_name] or 0
        local diff = after_count - before_count
        if diff > 0 then
            transferred[item_name] = diff
        end
    end
    
    -- Enqueue completion message (sync action)
    self:enqueue_message({
        action = "pickup_entity",
        agent_id = self.agent_id,
        entity_name = entity_name,
        position = position,
        extracted_items = transferred,
        tick = game.tick or 0,
    }, "entity_ops")
    
    return {
        success = true,
        entity_name = entity_name,
        position = position,
        extracted_items = transferred,
    }
end

function EntityOpsActions.remove_ghost(self, entity_name, position)
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end

    if entity_name and type(entity_name) ~= "string" then
        error("Agent: entity_name (string) must be nil or a string")
    end

    local ghost = game.surfaces[1].find_entities_filtered({position=position, type="entity-ghost"})

    if #(ghost) == 0 then
        error("Agent: No ghost entity found at position " .. position.x .. ", " .. position.y)
    end

    local ghost = ghost[1]

    if entity_name then
        if ghost.ghost_name ~= entity_name then
            error("Agent: Ghost entity name does not match expected name: " .. ghost.ghost_name)
        end
    end
    
    -- Store entity info before destruction
    local ghost_name = ghost.ghost_name
    local ghost_position = { x = ghost.position.x, y = ghost.position.y }
    
    ghost.destroy()
    
    -- Raise agent entity destroyed event (for ghost removal)
    -- Note: Ghosts are tracked separately, but we raise the event for consistency
    script.raise_event(custom_events.on_agent_entity_destroyed, {
        entity = ghost,  -- Entity may be invalid, but event handlers should check
        agent_id = self.agent_id,
        entity_name = ghost_name,
        position = ghost_position,
    })

    return {
        success = true,
        entity_name = entity_name,
        position = position,
    }
end

--- Helper to get inventory contents as simple table
--- @param entity LuaEntity
--- @param inventory_type defines.inventory
--- @return table|nil Contents {item_name = count, ...}
local function get_inventory_contents(entity, inventory_type)
    local inventory = entity.get_inventory(inventory_type)
    if not inventory then
        return nil
    end
    local contents = inventory.get_contents()
    -- Convert to simple table (contents is LuaItemStack[])
    local result = {}
    if contents then
        for _, item in pairs(contents) do
            local item_name = item.name or item[1]
            local count = item.count or item[2]
            if item_name and count then
                result[item_name] = (result[item_name] or 0) + count
            end
        end
    end
    return result
end

--- Inspect entity and return comprehensive volatile state
--- @param entity_name string Entity prototype name
--- @param position table Position {x, y}
--- @return table Entity inspection data
function EntityOpsActions.inspect_entity(self, entity_name, position)
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    -- Resolve entity position (exact lookup)
    local entity_interface = EntityInterface:new(entity_name, position, nil, true)
    local entity = entity_interface.entity
    
    -- Validate agent can reach entity
    if not self:can_reach_entity(entity) then
        error("Agent: Entity is out of reach")
    end
    
    -- Build inspection data
    local data = {
        entity_name = entity.name,
        entity_type = entity.type,
        position = { x = entity.position.x, y = entity.position.y },
        tick = game.tick or 0,
    }
    
    -- Add status if available (convert enum to name)
    if entity.status then
        -- Try to convert status enum to name
        local status_name = nil
        if utils and utils.status_to_name then
            status_name = utils.status_to_name(entity.status)
        end
        
        -- If conversion failed, try direct enum lookup
        if not status_name and defines.entity_status then
                for k, v in pairs(defines.entity_status) do
                    if v == entity.status then
                    status_name = string.lower(string.gsub(k, "_", "-"))
                    break
                    end
            end
        end
        
        -- Use converted name or fallback to string
        data.status = status_name or tostring(entity.status)
    end
    
    -- Add recipe if applicable (assemblers, furnaces, rocket-silo)
    local is_crafter = (entity.type == "assembling-machine" or 
                        entity.type == "furnace" or 
                        entity.type == "rocket-silo")
    
    if is_crafter then
        local recipe = entity.get_recipe()
        if recipe then
            data.recipe = recipe.name
        end
        
        -- Add crafting progress for crafting machines
        if entity.crafting_progress ~= nil then
            data.crafting_progress = entity.crafting_progress
        end
    end
    
    -- Add mining progress for mining drills
    if entity.type == "mining-drill" and entity.mining_progress then
        data.mining_progress = entity.mining_progress
    end
    
    -- Add burner information (furnaces, burner mining drills, etc.)
    local burner_result = nil
    if entity.burner and entity.burner.valid then
        local burner = entity.burner
        local burner_data = {}
        
        -- Heat information
        if burner.heat ~= nil then
            burner_data.heat = burner.heat
        end
        
        if burner.heat_capacity ~= nil then
            burner_data.heat_capacity = burner.heat_capacity
        end
        
        if burner.remaining_burning_fuel ~= nil then
            burner_data.remaining_burning_fuel = burner.remaining_burning_fuel
        end
        
        -- Currently burning item
        local currently_burning = burner.currently_burning
        local item_name = nil
        if currently_burning then
            item_name = currently_burning.name
            if item_name then
                burner_data.currently_burning = item_name
            end
        end
        
        -- If currently_burning is nil but there's remaining_burning_fuel, infer from fuel inventory
        -- This handles cases where currently_burning isn't set but fuel is actively burning
        if not item_name and burner_data.remaining_burning_fuel and burner_data.remaining_burning_fuel > 0 then
            -- Check fuel inventory to see what fuel is available
            local fuel_inv = entity.get_inventory(defines.inventory.fuel)
            if fuel_inv then
                -- Get the first fuel item in the inventory
                for i = 1, #fuel_inv do
                    local stack = fuel_inv[i]
                    if stack and stack.valid_for_read and stack.count > 0 then
                        item_name = stack.name
                        burner_data.currently_burning = item_name
                        break
                    end
                end
            end
        end
        
        -- Calculate burning progress if we have item_name and remaining_burning_fuel
        if item_name and burner_data.remaining_burning_fuel and burner_data.remaining_burning_fuel > 0 then
            -- Try to get fuel energy from prototype if available
            local fuel_proto = prototypes.item[item_name]
            if fuel_proto then
                local fuel_energy = fuel_proto.fuel_value
                if fuel_energy and fuel_energy > 0 then
                    local progress = 1.0 - (burner_data.remaining_burning_fuel / fuel_energy)
                    -- Clamp to [0, 1]
                    if progress < 0 then progress = 0 end
                    if progress > 1 then progress = 1 end
                    burner_data.burning_progress = progress
                end
            end
        end
        
        burner_result = burner_data
    end
    
    if burner_result then
        data.burner = burner_result
    end
    
    -- Add productivity bonus if available
    if entity.productivity_bonus then
        data.productivity_bonus = entity.productivity_bonus
    end
    
    -- Add energy state if applicable
    if entity.energy ~= nil then
        data.energy = {
            current = entity.energy,
            capacity = entity.electric_buffer_size or 0,
        }
    end
    
    -- Collect relevant inventories based on entity type
    local inventories = {}
    
    -- Generic fuel for burner entities
    if entity.burner and entity.burner.valid then
        local fuel_inv = get_inventory_contents(entity, defines.inventory.fuel)
        if fuel_inv and next(fuel_inv) ~= nil then
            inventories.fuel = fuel_inv
        end
    end

    -- Type-specific inventories
    if entity.type == "assembling-machine" then
        local input_inv = get_inventory_contents(entity, defines.inventory.assembling_machine_input)
        if input_inv and next(input_inv) ~= nil then inventories.input = input_inv end
        
        local output_inv = get_inventory_contents(entity, defines.inventory.assembling_machine_output)
        if output_inv and next(output_inv) ~= nil then inventories.output = output_inv end
        
        local module_inv = get_inventory_contents(entity, defines.inventory.assembling_machine_modules)
        if module_inv and next(module_inv) ~= nil then inventories.modules = module_inv end
        
    elseif entity.type == "furnace" then
        local source_inv = get_inventory_contents(entity, defines.inventory.furnace_source)
        if source_inv and next(source_inv) ~= nil then inventories.input = source_inv end
        
        local result_inv = get_inventory_contents(entity, defines.inventory.furnace_result)
        if result_inv and next(result_inv) ~= nil then inventories.output = result_inv end
        
    elseif entity.type == "container" or entity.type == "logistic-container" then
        local chest_inv = get_inventory_contents(entity, defines.inventory.chest)
        if chest_inv and next(chest_inv) ~= nil then inventories.chest = chest_inv end
        
    elseif entity.type == "mining-drill" then
        local output_inv = entity.get_output_inventory()
        if output_inv then
            local contents = output_inv.get_contents()
            if contents then
                local output_contents = {}
                for _, item in pairs(contents) do
                    local item_name = item.name or item[1]
                    local count = item.count or item[2]
                    if item_name and count then
                        output_contents[item_name] = (output_contents[item_name] or 0) + count
                    end
                end
                if next(output_contents) ~= nil then
                    inventories.output = output_contents
                end
            end
        end
        
    elseif entity.type == "car" or entity.type == "cargo-wagon" then
        local cargo_inv = get_inventory_contents(entity, defines.inventory.car_trunk) or get_inventory_contents(entity, defines.inventory.cargo_wagon)
        if cargo_inv and next(cargo_inv) ~= nil then inventories.cargo = cargo_inv end
    end

    -- Add inventories if any exist
    if next(inventories) ~= nil then
        data.inventories = inventories
    end
    
    -- Add inserter and mining drill targets
    if entity.type == "inserter" then
        local held = entity.held_stack
        if held and held.valid_for_read then
            data.held_item = {
                name = held.name,
                count = held.count
            }
        end
        
        data.pickup_position = { x = entity.pickup_position.x, y = entity.pickup_position.y }
        data.drop_position = { x = entity.drop_position.x, y = entity.drop_position.y }

        if entity.drop_target then
            data.drop_target = {
                name = entity.drop_target.name,
                position = { x = entity.drop_target.position.x, y = entity.drop_target.position.y }
            }
        end
        if entity.pickup_target then
            data.pickup_target = {
                name = entity.pickup_target.name,
                position = { x = entity.pickup_target.position.x, y = entity.pickup_target.position.y }
            }
        end
    elseif entity.type == "mining-drill" then
        data.drop_position = { x = entity.drop_position.x, y = entity.drop_position.y }
        if entity.drop_target then
            data.drop_target = {
                name = entity.drop_target.name,
                position = { x = entity.drop_target.position.x, y = entity.drop_target.position.y }
            }
        end
    end
    
    return data
end

return EntityOpsActions

