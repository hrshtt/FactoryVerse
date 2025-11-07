local GameState = require("GameState")

--- Inventory type mapping from string names to defines.inventory constants
local INVENTORY_TYPE_MAP = {
    chest = defines.inventory.chest,
    fuel = defines.inventory.fuel,
    burnt_result = defines.inventory.burnt_result,
    input = defines.inventory.assembling_machine_input,
    output = defines.inventory.assembling_machine_output,
    modules = defines.inventory.assembling_machine_modules,
    ammo = defines.inventory.turret_ammo,
    trunk = defines.inventory.car_trunk,
    cargo = defines.inventory.cargo_wagon,
    main = defines.inventory.character_main,
}

--- Resolve inventory type string to defines.inventory constant
--- @param inventory_type string|nil
--- @return defines.inventory|nil, string|nil
local function resolve_inventory_type(inventory_type)
    if not inventory_type then
        return nil, "inventory_type not specified"
    end
    
    local resolved = INVENTORY_TYPE_MAP[inventory_type]
    if not resolved then
        local available_types = {}
        for name, _ in pairs(INVENTORY_TYPE_MAP) do
            table.insert(available_types, name)
        end
        return nil, "Invalid inventory_type '" .. inventory_type .. "'. Available: " .. 
                    table.concat(available_types, ", ")
    end
    
    return resolved, nil
end

--- Validate that entity has the specified inventory type
--- @param params table
--- @return boolean, string|nil
local function validate_entity_has_inventory(params)
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
    
    local inventory_type, error_msg = resolve_inventory_type(params.inventory_type)
    if not inventory_type then
        return false, error_msg
    end
    
    -- Check if entity has this inventory type
    local success, inventory = pcall(function()
        return entity.get_inventory(inventory_type)
    end)
    
    if not success or not inventory or not inventory.valid then
        return false, "Entity does not have inventory type: " .. params.inventory_type
    end
    
    return true
end

--- Validate inventory type parameter
--- @param params table
--- @return boolean, string|nil
local function validate_inventory_type(params)
    if not params.inventory_type then
        return true -- inventory_type is optional for some actions
    end
    
    local inventory_type, error_msg = resolve_inventory_type(params.inventory_type)
    if not inventory_type then
        return false, error_msg
    end
    
    return true
end

--- Check if item is appropriate for inventory type
--- @param item_name string
--- @param inventory_type string
--- @param entity LuaEntity
--- @return boolean, string|nil
local function is_item_appropriate_for_inventory(item_name, inventory_type, entity)
    -- Get item prototype
    local item_proto = prototypes and prototypes.item and prototypes.item[item_name]
    if not item_proto then
        return true -- Let other validators handle unknown items
    end
    
    -- Check module inventories
    if inventory_type == "modules" then
        if not item_proto.module_effects then
            return false, "Item '" .. item_name .. "' is not a module"
        end
    end
    
    -- Check fuel inventories
    if inventory_type == "fuel" then
        if not item_proto.fuel_value or item_proto.fuel_value == 0 then
            return false, "Item '" .. item_name .. "' is not a fuel"
        end
    end
    
    -- Check ammo inventories
    if inventory_type == "ammo" then
        if not item_proto.type or item_proto.type ~= "ammo" then
            return false, "Item '" .. item_name .. "' is not ammunition"
        end
    end
    
    return true
end

--- Validate item appropriateness for inventory type
--- @param params table
--- @return boolean, string|nil
local function validate_item_inventory_compatibility(params)
    if not params.item or not params.inventory_type then
        return true -- Skip if parameters not provided
    end
    
    if not params.position or type(params.position.x) ~= "number" or type(params.position.y) ~= "number" then
        return true -- Let other validators handle missing parameters
    end
    
    if not params.entity_name then
        return true -- Let other validators handle missing parameters
    end
    
    local position = { x = params.position.x, y = params.position.y }
    local entity = game.surfaces[1].find_entity(params.entity_name, position)
    if not entity or not entity.valid then
        return true -- Let validate_entity_exists handle this
    end
    
    local is_appropriate, error_msg = is_item_appropriate_for_inventory(params.item, params.inventory_type, entity)
    if not is_appropriate then
        return false, error_msg
    end
    
    return true
end

-- Validators for all inventory actions (loaded automatically for entity.inventory.* actions)
return { validate_inventory_type, validate_entity_has_inventory, validate_item_inventory_compatibility }
