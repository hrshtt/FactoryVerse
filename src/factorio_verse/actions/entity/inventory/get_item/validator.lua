local ValidatorRegistry = require("core.action.ValidatorRegistry")
local GameState = require("core.game_state.GameState")

local validator_registry = ValidatorRegistry:new()

--- Validate that items exist in entity inventory
--- @param params table
--- @return boolean, string|nil
local function validate_items_exist_in_entity(params)
    -- Support both position_x/position_y and position table
    local pos_x = params.position_x or (params.position and params.position.x)
    local pos_y = params.position_y or (params.position and params.position.y)
    
    if not params.item or not params.inventory_type or not params.entity_name or type(pos_x) ~= "number" or type(pos_y) ~= "number" then
        return true -- Let other validators handle missing parameters
    end
    
    local position = { x = pos_x, y = pos_y }
    local entity = game.surfaces[1].find_entity(params.entity_name, position)
    if not entity or not entity.valid then
        return true -- Let validate_entity_exists handle this
    end
    
    -- Map inventory type name to defines constant
    local inventory_type_map = {
        chest = defines.inventory.chest,
        fuel = defines.inventory.fuel,
        modules = defines.inventory.assembling_machine_modules,
        input = defines.inventory.assembling_machine_input,
        output = defines.inventory.assembling_machine_output,
        ammo = defines.inventory.turret_ammo,
    }
    
    local inventory_type = inventory_type_map[params.inventory_type]
    if not inventory_type then
        return true -- Let validate_inventory_type handle this
    end
    
    local target_inventory = entity.get_inventory(inventory_type)
    if not target_inventory or not target_inventory.valid then
        return true -- Let validate_entity_has_inventory handle this
    end
    
    -- Handle different item parameter types
    if params.item == "ALL_ITEMS" then
        -- For ALL_ITEMS, just check that inventory has any items
        local contents = target_inventory.get_contents()
        if not contents or next(contents) == nil then
            return false, "Entity inventory is empty"
        end
    elseif type(params.item) == "table" then
        -- Batch operation: check each item
        for item_name, count in pairs(params.item) do
            local available_count = target_inventory.get_item_count(item_name)
            if available_count == 0 then
                return false, "Item '" .. item_name .. "' not found in entity inventory"
            end
        end
    else
        -- Single item operation
        local available_count = target_inventory.get_item_count(params.item)
        if available_count == 0 then
            return false, "Item '" .. params.item .. "' not found in entity inventory"
        end
    end
    
    return true
end

--- Validate that agent inventory has space
--- @param params table
--- @return boolean, string|nil
local function validate_agent_inventory_space(params)
    if not params.agent_id or not params.item then
        return true -- Let other validators handle missing parameters
    end
    
    local gs = GameState:new()
    local agent = gs:agent_state():get_agent(params.agent_id)
    if not agent then
        return true -- Let other validators handle agent validation
    end
    
    local agent_inventory = agent.get_inventory(defines.inventory.character_main)
    if not agent_inventory then
        return false, "Agent inventory not found"
    end
    
    -- For ALL_ITEMS, we can't easily validate space without knowing what items exist
    -- So we'll let the action handle this gracefully
    if params.item == "ALL_ITEMS" then
        return true
    end
    
    -- For specific items, check if agent can accept at least some
    if type(params.item) == "table" then
        -- Batch operation: check each item
        for item_name, count in pairs(params.item) do
            local can_accept = agent_inventory.can_insert({name = item_name, count = 1})
            if can_accept == 0 then
                return false, "Agent inventory cannot accept item: " .. item_name
            end
        end
    else
        -- Single item operation
        local count = params.count or 1
        local can_accept = agent_inventory.can_insert({name = params.item, count = count})
        if can_accept == 0 then
            return false, "Agent inventory cannot accept item: " .. params.item
        end
    end
    
    return true
end

-- Register validators for entity.inventory.get_item
validator_registry:register("entity.inventory.get_item", validate_items_exist_in_entity)
validator_registry:register("entity.inventory.get_item", validate_agent_inventory_space)

return validator_registry
