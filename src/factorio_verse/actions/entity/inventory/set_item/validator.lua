local ValidatorRegistry = require("core.action.ValidatorRegistry")
local GameState = require("core.game_state.GameState")

local validator_registry = ValidatorRegistry:new()

--- Validate that agent has sufficient items
--- @param params table
--- @return boolean, string|nil
local function validate_agent_has_items(params)
    if not params.agent_id or not params.item or not params.count then
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
    if not params.unit_number or not params.item or not params.count or not params.inventory_type then
        return true -- Let other validators handle missing parameters
    end
    
    local entity = game.get_entity_by_unit_number(params.unit_number)
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
    if can_insert < params.count then
        return false, "Inventory cannot accept " .. params.count .. " items. Can only accept: " .. can_insert
    end
    
    return true
end

-- Register validators for entity.inventory.set_item
validator_registry:register("entity.inventory.set_item", validate_agent_has_items)
validator_registry:register("entity.inventory.set_item", validate_inventory_space)

return validator_registry
