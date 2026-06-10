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

--- Valid inventory_type names accepted by put_inventory_item (ERR-1 treatment:
--- invalid names must error with this list — the names were undocumented,
--- field failure mode #6, 2026-06-10 retro).
local PUT_INVENTORY_TYPE_NAMES = {
    auto = true, fuel = true, input = true,
    chest = true, output = true, modules = true,
}
local PUT_INVENTORY_TYPE_NAMES_DOC =
    '"auto" (default — engine routes automatically: fuel to fuel slot, ingredients to input), ' ..
    '"fuel", "input", "chest", "output", "modules"'

--- Helper: list the inventory names (from the put/get name mapping) that this
--- entity actually has, for error guidance.
--- @param entity LuaEntity
--- @return string Comma-separated names, or a fallback note
local function _available_inventory_names(entity)
    local is_crafter = entity.type == "furnace" or entity.type == "assembling-machine" or
                       entity.type == "chemical-plant" or entity.type == "oil-refinery"
    local candidates = {
        { "chest", defines.inventory.chest },
        { "fuel", defines.inventory.fuel },
        { "input", is_crafter and defines.inventory.crafter_input or defines.inventory.assembling_machine_input },
        { "output", is_crafter and defines.inventory.crafter_output or defines.inventory.assembling_machine_output },
        { "modules", defines.inventory.assembling_machine_modules },
    }
    local names = {}
    for _, c in ipairs(candidates) do
        local ok, inv = pcall(function() return entity.get_inventory(c[2]) end)
        if ok and inv then
            table.insert(names, "'" .. c[1] .. "'")
        end
    end
    if entity.type == "mining-drill" and entity.get_output_inventory() then
        table.insert(names, "'output'")
    end
    if #names == 0 then
        return "none of the named inventories (try 'auto' routing, or this entity may not accept items)"
    end
    return table.concat(names, ", ")
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
                -- ERR-1 treatment: name the valid options instead of a raw throw
                return {
                    success = false,
                    error = string.format(
                        "Unknown inventory_type '%s' for get_inventory_item. Valid names: \"chest\", \"fuel\", \"input\", \"output\". A raw defines.inventory number is also accepted.",
                        tostring(inventory_type)),
                }
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

    -- Agent-reachable failures return {success=false, error=<cause>} so the
    -- agent sees a clean actionable message, never a traceback (ERR-1
    -- treatment; same contract as placement.lua, certified L4.2). Only the
    -- error STRING reaches the Python agent, so guidance lives in the text.

    if not count or type(count) ~= "number" or count <= 0 then
        return {
            success = false,
            error = string.format(
                "Invalid count %s: must be a positive number of items to insert",
                tostring(count)),
        }
    end

    if not item_name or type(item_name) ~= "string" then
        return {
            success = false,
            error = "item_name (string) is required — e.g. put_inventory_item('stone-furnace', pos, 'fuel', 'coal', 10)",
        }
    end

    if not (prototypes and prototypes.item and prototypes.item[item_name]) then
        return {
            success = false,
            error = string.format(
                "Unknown item '%s': no such item prototype exists (check spelling — item names look like 'iron-plate', 'coal')",
                item_name),
        }
    end

    -- Validate inventory_type name BEFORE any lookup or mutation (field
    -- failure mode #6: the valid names were undocumented). Numbers (raw
    -- defines.inventory constants) pass through.
    if inventory_type ~= nil and type(inventory_type) ~= "number" then
        if type(inventory_type) ~= "string" or not PUT_INVENTORY_TYPE_NAMES[inventory_type] then
            return {
                success = false,
                error = string.format(
                    "Unknown inventory_type %s. Valid names: %s. A raw defines.inventory number is also accepted.",
                    tostring(inventory_type), PUT_INVENTORY_TYPE_NAMES_DOC),
            }
        end
    end

    -- Resolve entity position
    local pos, radius = _resolve_entity_position(self, position, 5.0)

    -- Create EntityInterface instance (pcall: entity-not-found is an
    -- agent-reachable failure, not an infra error)
    local ok, entity_interface = pcall(EntityInterface.new, EntityInterface, entity_name, pos, radius, true)
    if not ok then
        local cause = tostring(entity_interface):gsub("^.-%.lua:%d+:%s*", "")
        return {
            success = false,
            error = cause .. " — check entity_name and position (positions snap to the entity's actual center; read exact positions from the reachable view or map DB)",
            entity_name = entity_name,
        }
    end
    local entity = entity_interface.entity

    -- Validate agent can reach entity
    if not self:can_reach_entity(entity) then
        local char_pos = self.character.position
        local dx, dy = entity.position.x - char_pos.x, entity.position.y - char_pos.y
        local distance = math.sqrt(dx * dx + dy * dy)
        local reach = self.character.reach_distance or 10
        return {
            success = false,
            error = string.format(
                "Cannot reach %s at (%.1f, %.1f): out of reach — agent at (%.1f, %.1f), distance %.1f > reach distance %.1f. Walk closer first.",
                entity_name, entity.position.x, entity.position.y,
                char_pos.x, char_pos.y, distance, reach),
            entity_name = entity_name,
        }
    end

    -- Get agent's main inventory
    local agent_inventory = self.character.get_main_inventory()
    if not agent_inventory then
        error("Agent: Agent inventory is invalid")
    end

    -- Check agent has items
    local available_count = agent_inventory.get_item_count(item_name)
    if available_count < count then
        return {
            success = false,
            error = string.format(
                "Insufficient items: agent has %d %s, tried to put %d. Lower the count or acquire more first.",
                available_count, item_name, count),
            item_name = item_name,
            have = available_count,
            need = count,
        }
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
                    return {
                        success = false,
                        error = string.format(
                            "%s has no accessible output inventory. Nothing was transferred.",
                            entity_name),
                        entity_name = entity_name,
                    }
                end
            else
                local inv_map = {
                    chest = defines.inventory.chest,
                    output = defines.inventory.assembling_machine_output,
                    modules = defines.inventory.assembling_machine_modules,
                }
                inv_index = inv_map[inventory_type]
                if not inv_index then
                    -- Unreachable after the up-front name check; kept as a guard.
                    return {
                        success = false,
                        error = string.format(
                            "Unknown inventory_type '%s'. Valid names: %s.",
                            tostring(inventory_type), PUT_INVENTORY_TYPE_NAMES_DOC),
                    }
                end
            end
        end

        -- Get entity inventory if not already set
        if not entity_inventory then
            entity_inventory = entity.get_inventory(inv_index)
            if not entity_inventory then
                return {
                    success = false,
                    error = string.format(
                        "%s (type '%s') has no '%s' inventory. Inventories this entity has: %s. Nothing was transferred.",
                        entity_name, entity.type, tostring(inventory_type),
                        _available_inventory_names(entity)),
                    entity_name = entity_name,
                }
            end
        end
    end

    -- Check if entity can accept items BEFORE removing from agent.
    -- can_insert means "can at least some be inserted" -> false means ZERO capacity:
    -- fail here, before any mutation.
    local can_insert = false
    if use_auto_routing then
        -- Use entity.can_insert() for auto-routing
        can_insert = entity.can_insert({ name = item_name, count = count })
    else
        -- Check specific inventory for manual insertion
        can_insert = entity_inventory.can_insert({ name = item_name, count = count })
    end

    if not can_insert then
        return {
            success = false,
            error = string.format(
                "Cannot insert %s into %s ('%s' inventory): the target cannot accept ANY of it — it is full, or the item is not allowed there (e.g. only burnable fuel fits 'fuel'). Nothing was transferred. Free space with take_inventory_item() or pick a different inventory_type (valid: %s).",
                item_name, entity_name, tostring(inventory_type or "auto"),
                PUT_INVENTORY_TYPE_NAMES_DOC),
            entity_name = entity_name,
            item_name = item_name,
        }
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

    if actual_transferred == 0 then
        -- can_insert said yes but nothing fit at insert time; the rollback
        -- above restored the agent inventory, so state is unchanged — fail
        -- honestly instead of returning success with count=0.
        return {
            success = false,
            error = string.format(
                "Could not insert any %s into %s: the target inventory rejected the items at insert time. Nothing was lost — all items are back in the agent inventory.",
                item_name, entity_name),
            entity_name = entity_name,
            item_name = item_name,
        }
    end

    -- Partial insert is NOT an error: the mutation happened. Report success
    -- with inserted/requested counts and a clear message instead of throwing
    -- after mutating (field failure mode #6: partial-insert-then-raw-throw).
    local message = nil
    if actual_transferred < count then
        message = string.format(
            "Partial insert: only %d of %d %s fit into %s; the remaining %d were returned to the agent inventory (target inventory is full).",
            actual_transferred, count, item_name, entity_name, count - actual_transferred)
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
        message = message,
        tick = game.tick or 0,
    }, "entity_ops")

    return {
        success = true,
        entity_name = entity_name,
        position = { x = entity.position.x, y = entity.position.y },
        inventory_type = inventory_type or "auto",
        item_name = item_name,
        count = actual_transferred,
        inserted = actual_transferred,
        requested_count = count,
        message = message,
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

    -- Pre-check capacity BEFORE mutating: with a full inventory the engine
    -- does NOT fail the mine — it spills products on the ground (verified
    -- live 2026-06-11), which would read as success with extracted_items={}
    -- while the item silently lies on the floor.
    local products = entity.prototype.mineable_properties
        and entity.prototype.mineable_properties.products
    if products then
        for _, product in pairs(products) do
            if product.type == "item" then
                local needed = product.amount or product.amount_max or 1
                if not agent_inventory.can_insert({name = product.name, count = needed}) then
                    error("Agent: Cannot pick up '" .. entity_name .. "' — your inventory " ..
                          "cannot fit " .. needed .. "x " .. product.name .. ". " ..
                          "Free up inventory space first; nothing was removed.")
                end
            end
        end
    end

    -- Mine entity INTO the agent inventory, raising script_raised_destroy so
    -- the snapshot pipeline sees the removal. character.mine_entity on a
    -- non-player character raises NO event -> permanent phantom map_entity
    -- rows that rebuild cannot recover (SNAP-4, L1.6 churn battery).
    local mined = entity.mine{inventory = agent_inventory, raise_destroyed = true}
    if not mined then
        error("Agent: Failed to mine entity '" .. entity_name .. "' — nothing was removed. " ..
              "Most likely the agent inventory cannot fit the items; free up space and retry.")
    end

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

