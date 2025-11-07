local GameState = require("GameState")

--- Validate that inventory supports bar/limit
--- @param params table
--- @return boolean, string|nil
local function validate_inventory_supports_bar(params)
    if not params.position or type(params.position.x) ~= "number" or type(params.position.y) ~= "number" then
        return true -- Let other validators handle missing parameters
    end
    
    if not params.inventory_type or not params.entity_name then
        return true -- Let other validators handle missing parameters
    end
    
    local position = { x = params.position.x, y = params.position.y }
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
    
    if not target_inventory.supports_bar then
        return false, "Inventory does not support setting limits"
    end
    
    return true
end

--- Validate limit value is within valid range
--- @param params table
--- @return boolean, string|nil
local function validate_limit_value(params)
    if not params.position or type(params.position.x) ~= "number" or type(params.position.y) ~= "number" then
        return true -- Let other validators handle missing parameters
    end
    
    if not params.inventory_type or not params.limit or not params.entity_name then
        return true -- Let other validators handle missing parameters
    end
    
    local position = { x = params.position.x, y = params.position.y }
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
    
    -- Check if limit is an integer
    if math.floor(params.limit) ~= params.limit then
        return false, "Limit must be an integer, got: " .. params.limit
    end
    
    -- Check if limit is within valid range
    local inventory_size = target_inventory.get_bar() or 0
    if params.limit < 0 or params.limit > inventory_size then
        return false, "Limit must be between 0 and " .. inventory_size .. " (inventory size). Got: " .. params.limit
    end
    
    return true
end

-- Validators for entity.inventory.set_limit action
return { validate_inventory_supports_bar, validate_limit_value }
