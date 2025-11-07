local GameState = require("GameState")

--- Validate that entity inventory has sufficient items
--- @param params table
--- @return boolean, string|nil
local function validate_entity_has_items(params)
    if not params.item or not params.count then
        return true -- Let other validators handle missing parameters
    end
    
    -- Support both position_x/position_y and position table
    local pos_x = params.position_x or (params.position and params.position.x)
    local pos_y = params.position_y or (params.position and params.position.y)
    
    if not params.entity_name or type(pos_x) ~= "number" or type(pos_y) ~= "number" then
        return true -- Let other validators handle missing parameters
    end
    
    local position = { x = pos_x, y = pos_y }
    local entity = game.surfaces[1].find_entity(params.entity_name, position)
    if not entity or not entity.valid then
        return true -- Let validate_entity_exists handle this
    end
    
    -- Default to "output" inventory if not specified
    local inventory_type_name = params.inventory_type or "output"
    
    -- Map inventory type name to defines constant
    local inventory_type_map = {
        chest = defines.inventory.chest,
        fuel = defines.inventory.fuel,
        modules = defines.inventory.assembling_machine_modules,
        input = defines.inventory.assembling_machine_input,
        output = defines.inventory.assembling_machine_output,
        ammo = defines.inventory.turret_ammo,
        trunk = defines.inventory.car_trunk,
        cargo = defines.inventory.cargo_wagon,
    }
    
    local inventory_type = inventory_type_map[inventory_type_name]
    if not inventory_type then
        return true -- Let validate_inventory_type handle this
    end
    
    local source_inventory = entity.get_inventory(inventory_type)
    if not source_inventory or not source_inventory.valid then
        return true -- Let validate_entity_has_inventory handle this
    end
    
    local available_count = source_inventory.get_item_count(params.item)
    if available_count < params.count then
        return false, "Entity inventory does not have enough items. Has: " .. 
                      available_count .. ", needs: " .. params.count
    end
    
    return true
end

--- Validate that agent inventory has space for the items
--- @param params table
--- @return boolean, string|nil
local function validate_agent_inventory_space(params)
    if not params.agent_id or not params.item or not params.count then
        return true -- Let other validators handle missing parameters
    end
    
    local gs = GameState:new()
    local agent = gs.agent:get_agent(params.agent_id)
    if not agent then
        return true -- Let other validators handle agent validation
    end
    
    local agent_inventory = agent.get_inventory(defines.inventory.character_main)
    if not agent_inventory then
        return false, "Agent inventory not found"
    end
    
    local can_insert = agent_inventory.can_insert({name = params.item, count = params.count})
    if not can_insert then
        return false, "Agent inventory cannot accept " .. params.count .. " of item: " .. params.item
    end
    
    return true
end

return { validate_entity_has_items, validate_agent_inventory_space }

