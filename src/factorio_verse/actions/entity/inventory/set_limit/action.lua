local Action = require("types.Action")

--- @class SetLimitParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field position table Position of the target entity: { x = number, y = number }
--- @field entity_name string Entity prototype name
--- @field inventory_type string Inventory type string (e.g., "chest", "input", "output")
--- @field limit number Maximum number of slots to allow (0 = unlimited)
local SetLimitParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    position = { type = "table", required = true },
    entity_name = { type = "string", required = true },
    inventory_type = { type = "string", required = true },
    limit = { type = "number", required = true }
})

--- @class SetLimitAction : Action
local SetLimitAction = Action:new("entity.inventory.set_limit", SetLimitParams)

--- @param params SetLimitParams
--- @return table result Data about the limit change
function SetLimitAction:run(params)
    local p = self:_pre_run(params)
    ---@cast p SetLimitParams

    local position = { x = p.position.x, y = p.position.y }
    local entity = game.surfaces[1].find_entity(p.entity_name, position)
    if not entity or not entity.valid then
        error("Entity not found or invalid")
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
    
    local inventory_type = inventory_type_map[p.inventory_type]
    if not inventory_type then
        error("Invalid inventory_type: " .. p.inventory_type)
    end

    -- Get target inventory
    local target_inventory = entity.get_inventory(inventory_type)
    if not target_inventory or not target_inventory.valid then
        error("Entity does not have inventory type: " .. p.inventory_type)
    end

    -- Check if inventory supports bar/limit
    if not target_inventory.supports_bar then
        error("Inventory does not support setting limits")
    end

    -- Validate limit value
    local inventory_size = target_inventory.get_bar() or 0
    if p.limit < 0 or p.limit > inventory_size then
        error("Limit must be between 0 and " .. inventory_size .. " (inventory size). Got: " .. p.limit)
    end

    -- Get current limit for comparison
    local current_limit = target_inventory.get_bar()
    if current_limit == p.limit then
        return self:_post_run({
            position = position,
            entity_name = entity.name,
            entity_type = entity.type,
            inventory_type = p.inventory_type,
            previous_limit = current_limit,
            new_limit = p.limit,
            action = "no_op",
            message = "Inventory already has this limit",
            affected_positions = { { position = position, entity_name = p.entity_name, entity_type = entity.type } }
        }, p)
    end

    -- Set the limit
    target_inventory.set_bar(p.limit)

    local result = {
        position = position,
        entity_name = entity.name,
        entity_type = entity.type,
        inventory_type = p.inventory_type,
        previous_limit = current_limit,
        new_limit = p.limit,
        action = "set",
        affected_positions = { { position = position, entity_name = p.entity_name, entity_type = entity.type } }
    }
    
    return self:_post_run(result, p)
end

return { action = SetLimitAction, params = SetLimitParams }
