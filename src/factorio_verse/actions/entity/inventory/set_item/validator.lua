local GameState = require("core.game_state.GameState")

--- Validate that agent has sufficient items
--- @param params table
--- @return boolean, string|nil
local function validate_agent_has_items(params)
    if not params.agent_id or not params.item or not params.count then
        return true -- Let other validators handle missing parameters
    end
    
    local gs = GameState:new()
    local agent = gs:agent():get_agent(params.agent_id)
    if not agent then
        return true -- Let other validators handle agent validation
    end
    
    local agent_inventory = agent.get_inventory(defines.inventory.character_main)
    if not agent_inventory then
        return false, "Agent inventory not found"
    end
    
    local agent_item_count = agent_inventory.get_item_count(params.item)
    if agent_item_count < params.count then
        return false, "Agent does not have enough items. Has: " .. agent_item_count .. ", needs: " .. params.count
    end
    
    return true
end

--- Validate that inventory has space for the item
--- @param params table
--- @return boolean, string|nil
local function validate_inventory_space(params)
    -- Support both position_x/position_y and position table
    local pos_x = params.position_x or (params.position and params.position.x)
    local pos_y = params.position_y or (params.position and params.position.y)
    
    if not params.item or not params.count or not params.inventory_type or not params.entity_name or type(pos_x) ~= "number" or type(pos_y) ~= "number" then
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
    
    local can_insert = target_inventory.can_insert({name = params.item, count = params.count})
    if not can_insert then
        return false, "Inventory cannot accept " .. params.count .. " of item: " .. params.item
    end
    
    return true
end

return { validate_agent_has_items, validate_inventory_space }
