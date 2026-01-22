--- Agent entity operation methods (using EntityInterface)
--- Methods operate directly on Agent instances (self)
--- Uses EntityInterface for low-level entity operations
--- These methods are mixed into the Agent class at module level

local EntityInterface = require("game_state.EntityInterface")
local custom_events = require("utils.custom_events")
local utils = require("utils.utils")
local inspection = require("agent_actions.inspection")

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
--- @param inventory_type number|string|defines.inventory Inventory type
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
            -- Factorio 2.0+: Use crafter_output/crafter_input for crafting machines
            local is_crafter = entity.type == "furnace" or entity.type == "assembling-machine" or 
                              entity.type == "chemical-plant" or entity.type == "oil-refinery"
            
            if inventory_type == "output" and is_crafter then
                inv_index = defines.inventory.crafter_output
            elseif inventory_type == "input" and is_crafter then
                inv_index = defines.inventory.crafter_input
            else
                -- Fallback to legacy inventory types
                local inv_map = {
                    chest = defines.inventory.chest,
                    fuel = defines.inventory.fuel,
                    input = defines.inventory.assembling_machine_input,
                    output = defines.inventory.assembling_machine_output,
                }
                inv_index = inv_map[inventory_type]
            end
            
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
                        -- Rollback: put remaining items back into entity inventory
                        entity_inventory.insert({ name = item_name_in_inv, count = removed - inserted })
                    end
                    if inserted > 0 then
                        total_transferred = total_transferred + inserted
                        table.insert(results, {
                            item_name = item_name_in_inv,
                            count = inserted,
                            requested_count = transfer_count
                        })
                    end
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
    local actual_transferred = 0

    if removed > 0 then
        local inserted = agent_inventory.insert({ name = item_name, count = removed })
        if inserted < removed then
            -- Rollback: put remaining items back into entity inventory
            entity_inventory.insert({ name = item_name, count = removed - inserted })
        end
        actual_transferred = inserted
    end

    -- Enqueue completion message (sync action)
    self:enqueue_message({
        action = "get_inventory_item",
        agent_id = self.agent_id,
        entity_name = entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        inventory_type = inventory_type,
        item_name = item_name,
        count = actual_transferred,
        requested_count = transfer_count,
        tick = game.tick or 0,
    }, "entity_ops")

    return {
        success = true,
        entity_name = entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        inventory_type = inventory_type,
        item_name = item_name,
        count = actual_transferred,
        requested_count = transfer_count,
    }
end

--- Set item in entity inventory (transfers from agent inventory)
--- Uses entity.insert() for automatic routing (fuel -> fuel slot, ore -> input slot, etc.)
--- Only uses manual inventory selection for specific cases like chests and output
--- @param entity_name string Entity prototype name
--- @param position table|nil Position {x, y} (nil to use agent position with radius search)
--- @param inventory_type number|string Inventory type (nil/"auto" = use entity.insert() auto-routing)
--- @param item_name string Item name to set
--- @param count number Count to set
--- @return table Result
function EntityOpsActions.put_inventory_item(self, entity_name, position, inventory_type, item_name, count)
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
    
    -- Determine if we should use auto-routing (entity.insert()) or manual inventory selection
    local use_auto_routing = false
    local entity_inventory = nil
    local inv_index = inventory_type
    
    -- Auto-routing: Use entity.insert() for fuel, input, or when inventory_type is nil/"auto"
    -- The engine automatically routes: coal -> fuel, ore -> input, etc.
    if inventory_type == nil or inventory_type == "auto" or 
       (type(inventory_type) == "string" and (inventory_type == "fuel" or inventory_type == "input")) then
        use_auto_routing = true
    else
        -- Manual inventory selection for specific cases (chest, output, etc.)
        if type(inventory_type) == "string" then
            -- Factorio 2.0+: Use crafter_output for crafting machines
            local is_crafter = entity.type == "furnace" or entity.type == "assembling-machine" or 
                              entity.type == "chemical-plant" or entity.type == "oil-refinery"
            
            if inventory_type == "output" and is_crafter then
                inv_index = defines.inventory.crafter_output
            elseif inventory_type == "output" and entity.type == "mining-drill" then
                -- Special handling for mining drills: use get_output_inventory() for output
                entity_inventory = entity.get_output_inventory()
                if not entity_inventory then
                    error("Agent: Mining drill output inventory is invalid")
                end
            else
                local inv_map = {
                    chest = defines.inventory.chest,
                    output = defines.inventory.assembling_machine_output,
                    modules = defines.inventory.assembling_machine_modules,
                }
                inv_index = inv_map[inventory_type]
                if not inv_index then
                    error("Agent: Unknown inventory type name: " .. inventory_type)
                end
            end
        end
        
        -- Get entity inventory if not already set
        if not entity_inventory then
            entity_inventory = entity.get_inventory(inv_index)
            if not entity_inventory then
                error("Agent: Entity inventory is invalid")
            end
        end
    end
    
    -- Check if entity can accept items before removing from agent
    local can_insert = false
    if use_auto_routing then
        -- Use entity.can_insert() for auto-routing
        can_insert = entity.can_insert({ name = item_name, count = count })
    else
        -- Check specific inventory for manual insertion
        can_insert = entity_inventory.can_insert({ name = item_name, count = count })
    end
    
    if not can_insert then
        error("Agent: Cannot insert item into entity inventory (insufficient space or invalid item)")
    end
    
    -- Transfer items
    local removed = agent_inventory.remove({ name = item_name, count = count })
    local actual_transferred = 0

    if removed > 0 then
        local inserted = 0

        if use_auto_routing then
            -- Use entity.insert() - engine automatically routes to correct inventory
            -- Coal goes to fuel, ore goes to input, etc.
            inserted = entity.insert({ name = item_name, count = removed })
        else
            -- Manual inventory insertion for specific cases
            inserted = entity_inventory.insert({ name = item_name, count = removed })
        end

        if inserted < removed then
            -- Rollback: put remaining items back into agent inventory
            agent_inventory.insert({ name = item_name, count = removed - inserted })
        end

        actual_transferred = inserted
    end

    -- Enqueue completion message (sync action)
    self:enqueue_message({
        action = "put_inventory_item",
        agent_id = self.agent_id,
        entity_name = entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        inventory_type = inventory_type or "auto",
        item_name = item_name,
        count = actual_transferred,
        requested_count = count,
        tick = game.tick or 0,
    }, "entity_ops")

    return {
        success = true,
        entity_name = entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        inventory_type = inventory_type or "auto",
        item_name = item_name,
        count = actual_transferred,
        requested_count = count,
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
    
    -- Destroy ghost with raise_destroy=true to trigger script_raised_destroy event
    -- This allows fv_snapshot to track the ghost removal via Factorio's built-in event system
    ghost.destroy({raise_destroy=true})

    return {
        success = true,
        entity_name = entity_name,
        position = position,
    }
end

--- Rotate entity to a specific direction
--- Supports both regular entities and ghost entities
--- Note: Asymmetric entities (tile_width != tile_height) can only rotate in 180° increments
--- @param entity_name string Entity prototype name (use ghost_name for ghosts)
--- @param position table|nil Position {x, y} (nil to use agent position with radius search)
--- @param direction defines.direction|nil Direction to rotate to (nil rotates 90° clockwise)
--- @param is_ghost boolean|nil Whether to target a ghost entity (default: false)
--- @return table Result
function EntityOpsActions.rotate_entity(self, entity_name, position, direction, is_ghost)
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    -- Resolve entity position
    local pos, radius = _resolve_entity_position(self, position, 5.0)
    
    local entity = nil
    local actual_entity_name = entity_name
    
    if is_ghost then
        -- Find ghost entity by ghost_name at position
        local ghosts = game.surfaces[1].find_entities_filtered({
            position = pos,
            radius = radius,
            type = "entity-ghost",
            ghost_name = entity_name
        })
        
        if #ghosts == 0 then
            error("Agent: No ghost entity '" .. entity_name .. "' found at position " .. pos.x .. ", " .. pos.y)
        end
        
        entity = ghosts[1]
    else
        -- Create EntityInterface instance for regular entity
        local entity_interface = EntityInterface:new(entity_name, pos, radius, true)
        entity = entity_interface.entity
    end
    
    -- Validate agent can reach entity
    if not self:can_reach_entity(entity) then
        error("Agent: Entity is out of reach")
    end
    
    -- Store old direction for result
    local old_direction = entity.direction
    
    -- Perform rotation
    if direction then
        entity.direction = direction
    else
        -- Rotate 90 degrees clockwise
        local current_dir = old_direction or defines.direction.north
        local dir_map = {
            [defines.direction.north] = defines.direction.east,
            [defines.direction.east] = defines.direction.south,
            [defines.direction.south] = defines.direction.west,
            [defines.direction.west] = defines.direction.north,
            [defines.direction.northeast] = defines.direction.southeast,
            [defines.direction.southeast] = defines.direction.southwest,
            [defines.direction.southwest] = defines.direction.northwest,
            [defines.direction.northwest] = defines.direction.northeast,
        }
        entity.direction = dir_map[current_dir] or defines.direction.north
    end
    
    local new_direction = entity.direction
    
    -- Raise agent entity rotated event (snapshot will handle ghost vs entity)
    script.raise_event(custom_events.on_agent_entity_rotated, {
        entity = entity,
        agent_id = self.agent_id,
        old_direction = old_direction,
        new_direction = new_direction,
        is_ghost = is_ghost or (entity.type == "entity-ghost"),
    })
    
    -- Enqueue completion message (sync action)
    self:enqueue_message({
        action = "rotate_entity",
        agent_id = self.agent_id,
        entity_name = actual_entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        old_direction = old_direction,
        new_direction = new_direction,
        is_ghost = is_ghost or false,
        tick = game.tick or 0,
    }, "entity_ops")
    
    return {
        success = true,
        entity_name = actual_entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        old_direction = old_direction,
        new_direction = new_direction,
        is_ghost = is_ghost or false,
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
--- Note: Inspection is a read-only query and works from any distance (no reachability check)
function EntityOpsActions.inspect_entity(self, entity_name, position)
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    -- Resolve entity position (exact lookup)
    local entity_interface = EntityInterface:new(entity_name, position, nil, true)
    local entity = entity_interface.entity
    
    -- No reachability check - inspection is read-only and works from anywhere
    
    -- Use centralized inspection module
    return inspection.inspect_entity(entity)
end

return EntityOpsActions

