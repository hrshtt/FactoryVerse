--- EntityInterface: High-level wrapper around LuaEntity for entity manipulation
--- Provides low-level interface operations with basic validation only
--- Agent-agnostic - no agent-specific validation (that's done by Agent class)
--- @class EntityInterface
--- @field entity LuaEntity The wrapped LuaEntity instance

-- ============================================================================
-- METATABLE REGISTRATION (must be at module load time)
-- ============================================================================

local EntityInterface = {}
EntityInterface.__index = EntityInterface

-- Register metatable for save/load persistence (if needed in future)
-- Note: EntityInterface instances are typically not stored, but registration is safe
script.register_metatable('EntityInterface', EntityInterface)

-- ============================================================================
-- CUSTOM EVENT INITIALIZATION (must be at module load time)
-- ============================================================================

-- Generate custom event ID for entity configuration changes
-- This event is raised whenever entity configuration changes (recipe, filter, inventory_limit, etc.)
EntityInterface.on_entity_configuration_changed = script.generate_event_name()
log("EntityInterface: Generated custom event 'entity_configuration_changed': " .. tostring(EntityInterface.on_entity_configuration_changed))

-- ============================================================================
-- ENTITY RESOLUTION
-- ============================================================================

--- Resolve entity from resolution parameters
--- Agent-agnostic: only supports exact lookup or radius search
--- @param resolution_params table Resolution parameters:
---   - entity_name (string, required): Entity prototype name
---   - position (table, required): Position {x, y} for lookup
---   - radius (number, optional): Search radius (if provided, uses radius search; if nil, uses exact lookup)
---   - strict (boolean, optional): If true, error on multiple matches in radius search (default: true)
--- @return LuaEntity|nil Resolved entity or nil if not found
local function _resolve_entity(resolution_params)
    local entity_name = resolution_params.entity_name
    if not entity_name or type(entity_name) ~= "string" then
        error("EntityInterface: entity_name (string) is required")
    end
    
    local position = resolution_params.position
    if not position or type(position.x) ~= "number" or type(position.y) ~= "number" then
        error("EntityInterface: position {x, y} is required")
    end
    
    local surface = game.surfaces[1]
    if not surface then
        error("EntityInterface: No surface available")
    end
    
    -- Validate prototype exists
    local proto = prototypes and prototypes.entity and prototypes.entity[entity_name]
    if not proto then
        error("EntityInterface: Unknown entity prototype: " .. entity_name)
    end
    
    local radius = resolution_params.radius
    local strict = resolution_params.strict ~= false  -- Default true
    
    -- Exact lookup: position + name (no radius)
    if not radius then
        local entity = surface.find_entity(entity_name, position)
        if not entity or not entity.valid then
            error("EntityInterface: Entity '" .. entity_name .. "' not found at position " ..
                  "{x=" .. position.x .. ", y=" .. position.y .. "}")
        end
        return entity
    end
    
    -- Radius search: position + radius + name
    local entities = surface.find_entities_filtered({
        position = position,
        radius = radius,
        name = entity_name
    })
    
    -- Filter valid entities
    local valid_entities = {}
    for _, e in ipairs(entities) do
        if e and e.valid then
            table.insert(valid_entities, e)
        end
    end
    
    if #valid_entities == 0 then
        error("EntityInterface: Entity '" .. entity_name .. "' not found within radius " ..
              radius .. " of position {x=" .. position.x .. ", y=" .. position.y .. "}")
    elseif #valid_entities > 1 and strict then
        error("EntityInterface: Multiple entities '" .. entity_name .. "' found within radius " ..
              radius .. ". Provide exact position or set strict=false.")
    end
    
    return valid_entities[1]
end

-- ============================================================================
-- ENTITY INTERFACE CREATION
-- ============================================================================

--- Create EntityInterface wrapper around a LuaEntity
--- Agent-agnostic: only accepts position-based resolution or direct LuaEntity wrapping
--- @param resolution_params table|LuaEntity Resolution parameters or LuaEntity to wrap directly
---   If table: {entity_name (string), position ({x, y}), radius? (number), strict? (boolean)}
---   If LuaEntity: wraps directly (for internal/admin use)
--- @return EntityInterface
function EntityInterface:new(resolution_params)
    local lua_entity = nil
    
    -- If already a LuaEntity, wrap it directly
    if type(resolution_params) == "table" and resolution_params.valid ~= nil then
        -- Assume it's a LuaEntity (has .valid property)
        if not resolution_params.valid then
            error("EntityInterface: Cannot wrap invalid LuaEntity")
        end
        lua_entity = resolution_params
    else
        -- Resolve entity from params (agent-agnostic: requires explicit position)
        lua_entity = _resolve_entity(resolution_params)
    end
    
    if not lua_entity or not lua_entity.valid then
        error("EntityInterface: Entity is invalid")
    end
    
    return setmetatable({
        entity = lua_entity,
    }, EntityInterface)
end

-- ============================================================================
-- ENTITY INTERFACE METHODS (Low-Level, Basic Validation Only)
-- ============================================================================

--- Set recipe on entity
--- Validates: entity type supports recipes, recipe compatible with entity
--- Does NOT validate: recipe accessible to agent's force (that's Agent class responsibility)
--- @param recipe_name string|nil Recipe name (nil to clear recipe)
--- @param overwrite boolean|nil If true, allows overwriting existing recipe (default: false)
--- @return boolean Success
function EntityInterface:set_recipe(recipe_name, overwrite)
    overwrite = overwrite or false
    
    if not (self.entity and self.entity.valid) then
        error("EntityInterface: Entity is invalid")
    end
    
    -- Check if entity type supports recipes
    local supported_types = {"assembling-machine", "furnace", "rocket-silo"}
    local is_supported = false
    for _, entity_type in ipairs(supported_types) do
        if self.entity.type == entity_type then
            is_supported = true
            break
        end
    end
    
    -- Also check if entity has crafting_categories (for modded entities)
    if not is_supported and self.entity.prototype and self.entity.prototype.crafting_categories then
        is_supported = true
    end
    
    if not is_supported then
        error("EntityInterface: Entity type does not support recipes: " .. self.entity.type)
    end
    
    -- Get current recipe
    local current_recipe = self.entity.get_recipe()
    local current_recipe_name = current_recipe and current_recipe.name or nil
    
    -- Handle recipe clearing (nil)
    if not recipe_name then
        if current_recipe_name then
            self.entity.set_recipe(nil)
            -- Raise configuration changed event
            script.raise_event(EntityInterface.on_entity_configuration_changed, {
                entity = self.entity,
                change_type = "recipe",
                old_value = current_recipe_name,
                new_value = nil,
            })
        end
        return true
    end
    
    -- Validate recipe prototype exists
    local recipe_proto = prototypes and prototypes.recipe and prototypes.recipe[recipe_name]
    if not recipe_proto then
        error("EntityInterface: Recipe prototype not found: " .. recipe_name)
    end
    
    -- Check if recipe is compatible with entity
    local entity_categories = self.entity.prototype.crafting_categories
    if entity_categories then
        local recipe_category = recipe_proto.category or "crafting"
        local is_compatible = false
        for category_name, _ in pairs(entity_categories) do
            if category_name == recipe_category then
                is_compatible = true
                break
            end
        end
        if not is_compatible then
            local categories_str = ""
            for category_name, _ in pairs(entity_categories) do
                if categories_str ~= "" then categories_str = categories_str .. ", " end
                categories_str = categories_str .. category_name
            end
            error("EntityInterface: Recipe '" .. recipe_name .. "' (category: " .. recipe_category .. 
                  ") is not compatible with entity (categories: " .. categories_str .. ")")
        end
    end
    
    -- Check if recipe is already set
    if current_recipe_name == recipe_name then
        return true  -- No-op, already set
    end
    
    -- Check if overwrite is needed
    if current_recipe_name and not overwrite then
        error("EntityInterface: Entity already has recipe '" .. current_recipe_name .. 
              "'. Set overwrite=true to replace it.")
    end
    
    -- Set the recipe
    local success = self.entity.set_recipe(recipe_name)
    if not success then
        error("EntityInterface: Failed to set recipe: " .. recipe_name)
    end
    
    -- Raise configuration changed event
    script.raise_event(EntityInterface.on_entity_configuration_changed, {
        entity = self.entity,
        change_type = "recipe",
        old_value = current_recipe_name,
        new_value = recipe_name,
    })
    
    return true
end

--- Set filter on entity inventory
--- Validates: inventory exists, filter can be set
--- @param inventory_type number|string Inventory type (defines.inventory constant or name)
--- @param filter_index number|nil Filter slot index (nil for all slots)
--- @param filter_item string|nil Item name to filter (nil to clear filter)
--- @return boolean Success
function EntityInterface:set_filter(inventory_type, filter_index, filter_item)
    if not (self.entity and self.entity.valid) then
        error("EntityInterface: Entity is invalid")
    end
    
    -- Resolve inventory type
    local inv_index = inventory_type
    if type(inventory_type) == "string" then
        -- Map string names to defines.inventory constants
        local inv_map = {
            chest = defines.inventory.chest,
            fuel = defines.inventory.fuel,
            input = defines.inventory.assembling_machine_input,
            output = defines.inventory.assembling_machine_output,
        }
        inv_index = inv_map[inventory_type]
        if not inv_index then
            error("EntityInterface: Unknown inventory type name: " .. inventory_type)
        end
    end
    
    -- Get inventory
    local inventory = self.entity.get_inventory(inv_index)
    if not inventory then
        error("EntityInterface: Entity does not have inventory at index " .. tostring(inv_index))
    end
    
    -- Get current filter state for event
    local old_filter = nil
    if filter_index then
        old_filter = inventory.get_filter(filter_index)
    end
    
    -- Set filter
    if filter_index then
        -- Set specific slot filter
        if filter_item then
            inventory.set_filter(filter_index, filter_item)
        else
            inventory.set_filter(filter_index, nil)
        end
    else
        -- Clear all filters
        for i = 1, #inventory do
            inventory.set_filter(i, filter_item)
        end
    end
    
    -- Raise configuration changed event
    script.raise_event(EntityInterface.on_entity_configuration_changed, {
        entity = self.entity,
        change_type = "filter",
        inventory_type = inv_index,
        filter_index = filter_index,
        old_value = old_filter,
        new_value = filter_item,
    })
    
    return true
end

--- Set inventory limit on entity
--- Validates: inventory exists
--- @param inventory_type number|string Inventory type (defines.inventory constant or name)
--- @param limit number|nil Limit to set (nil to clear limit)
--- @return boolean Success
function EntityInterface:set_inventory_limit(inventory_type, limit)
    if not (self.entity and self.entity.valid) then
        error("EntityInterface: Entity is invalid")
    end
    
    -- Resolve inventory type
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
            error("EntityInterface: Unknown inventory type name: " .. inventory_type)
        end
    end
    
    -- Get inventory
    local inventory = self.entity.get_inventory(inv_index)
    if not inventory then
        error("EntityInterface: Entity does not have inventory at index " .. tostring(inv_index))
    end
    
    -- Get current limit for event
    local old_limit = inventory.get_bar()
    
    -- Set limit
    if limit then
        inventory.set_bar(limit)
    else
        inventory.set_bar()  -- Clear limit
    end
    
    -- Raise configuration changed event
    script.raise_event(EntityInterface.on_entity_configuration_changed, {
        entity = self.entity,
        change_type = "inventory_limit",
        inventory_type = inv_index,
        old_value = old_limit,
        new_value = limit,
    })
    
    return true
end

--- Get item from entity inventory
--- Validates: inventory exists
--- Does NOT validate: agent has space, etc. (that's Agent class responsibility)
--- @param inventory_type number|string Inventory type
--- @param item_name string Item name to get
--- @param count number|nil Count to get (default: all available)
--- @return number Count actually retrieved
function EntityInterface:get_inventory_item(inventory_type, item_name, count)
    if not (self.entity and self.entity.valid) then
        error("EntityInterface: Entity is invalid")
    end
    
    -- Resolve inventory type
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
            error("EntityInterface: Unknown inventory type name: " .. inventory_type)
        end
    end
    
    -- Get inventory
    local inventory = self.entity.get_inventory(inv_index)
    if not inventory then
        error("EntityInterface: Entity does not have inventory at index " .. tostring(inv_index))
    end
    
    -- Get available count
    local available = inventory.get_item_count(item_name)
    if available == 0 then
        error("EntityInterface: Entity has no items of: " .. item_name)
    end
    
    -- Determine count to get
    local count_to_get = count or available
    if count_to_get > available then
        count_to_get = available
    end
    
    -- Remove from inventory
    local removed = inventory.remove({ name = item_name, count = count_to_get })
    return removed
end

--- Set item in entity inventory
--- Validates: inventory exists, can accept items
--- Does NOT validate: source has items (that's Agent class responsibility)
--- @param inventory_type number|string Inventory type
--- @param item_name string Item name to insert
--- @param count number Count to insert
--- @return number Count actually inserted
function EntityInterface:set_inventory_item(inventory_type, item_name, count)
    if not (self.entity and self.entity.valid) then
        error("EntityInterface: Entity is invalid")
    end
    
    if not count or count <= 0 then
        error("EntityInterface: Count must be positive")
    end
    
    -- Resolve inventory type
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
            error("EntityInterface: Unknown inventory type name: " .. inventory_type)
        end
    end
    
    -- Get inventory
    local inventory = self.entity.get_inventory(inv_index)
    if not inventory then
        error("EntityInterface: Entity does not have inventory at index " .. tostring(inv_index))
    end
    
    -- Insert into inventory
    local inserted = self.entity.insert({ name = item_name, count = count })
    if inserted == 0 then
        error("EntityInterface: Entity cannot accept " .. count .. " items of: " .. item_name)
    end
    
    return inserted
end

--- Extract all items from entity inventories (before pickup/mining)
--- Validates: entity is mineable
--- Note: Actual mining requires an agent (use Agent:pickup_entity() which calls agent.mine_entity())
--- @return table Items from all inventories {item_name = count, ...}
function EntityInterface:extract_inventory_items()
    if not (self.entity and self.entity.valid) then
        error("EntityInterface: Entity is invalid")
    end
    
    -- Check if entity is mineable
    if not self.entity.mineable then
        error("EntityInterface: Entity is not mineable")
    end
    
    local all_items = {}
    
    -- Inventory types to check
    local inventory_types = {
        chest = defines.inventory.chest,
        fuel = defines.inventory.fuel,
        burnt_result = defines.inventory.burnt_result,
        input = defines.inventory.assembling_machine_input,
        output = defines.inventory.assembling_machine_output,
        modules = defines.inventory.assembling_machine_modules,
        ammo = defines.inventory.turret_ammo,
        trunk = defines.inventory.car_trunk,
        cargo = defines.inventory.cargo_wagon,
    }
    
    for inventory_name, inventory_type in pairs(inventory_types) do
        local success, inventory = pcall(function()
            return self.entity.get_inventory(inventory_type)
        end)
        
        if success and inventory and inventory.valid then
            local contents = inventory.get_contents()
            if contents and next(contents) ~= nil then
                -- get_contents() returns an array of {name, count, quality} objects
                for _, item in pairs(contents) do
                    local item_name = item.name or item[1]
                    local count = item.count or item[2]
                    if item_name and count then
                        all_items[item_name] = (all_items[item_name] or 0) + count
                    end
                end
            end
        end
    end
    
    return all_items
end

--- Check if entity can be picked up
--- @return boolean
function EntityInterface:can_pickup()
    if not (self.entity and self.entity.valid) then
        return false
    end
    return self.entity.mineable == true
end

--- Rotate entity
--- @param direction defines.direction|nil Direction to rotate to (nil rotates 90 degrees)
--- @return boolean Success
function EntityInterface:rotate(direction)
    if not (self.entity and self.entity.valid) then
        error("EntityInterface: Entity is invalid")
    end
    
    if direction then
        self.entity.direction = direction
    else
        -- Rotate 90 degrees
        local current_dir = self.entity.direction or defines.direction.north
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
        self.entity.direction = dir_map[current_dir] or defines.direction.north
    end
    
    return true
end

-- ============================================================================
-- UTILITY METHODS
-- ============================================================================

--- Get entity position
--- @return table Position {x, y}
function EntityInterface:get_position()
    if not (self.entity and self.entity.valid) then
        error("EntityInterface: Entity is invalid")
    end
    
    local pos = self.entity.position
    return { x = pos.x, y = pos.y }
end

--- Get entity name
--- @return string Entity prototype name
function EntityInterface:get_name()
    if not (self.entity and self.entity.valid) then
        error("EntityInterface: Entity is invalid")
    end
    
    return self.entity.name
end

--- Get entity type
--- @return string Entity type
function EntityInterface:get_type()
    if not (self.entity and self.entity.valid) then
        error("EntityInterface: Entity is invalid")
    end
    
    return self.entity.type
end

--- Check if entity is valid
--- @return boolean
function EntityInterface:is_valid()
    return self.entity and self.entity.valid == true
end

return EntityInterface

