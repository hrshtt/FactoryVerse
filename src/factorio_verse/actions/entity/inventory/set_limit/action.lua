local Action = require("core.action.Action")
local ParamSpec = require("core.action.ParamSpec")
local GameState = require("core.game_state.GameState")

local gs = GameState:new()

--- @class SetLimitParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field unit_number number Unique identifier for the target entity
--- @field inventory_type string Inventory type string (e.g., "chest", "input", "output")
--- @field limit number Maximum number of slots to allow (0 = unlimited)
local SetLimitParams = ParamSpec:new({
    agent_id = { type = "number", required = true },
    unit_number = { type = "number", required = true },
    inventory_type = { type = "string", required = true },
    limit = { type = "number", required = true }
})

--- @class SetLimitAction : Action
local SetLimitAction = Action:new("entity.inventory.set_limit", SetLimitParams)

--- @param params SetLimitParams
--- @return table result Data about the limit change
function SetLimitAction:run(params)
    local p = self:_pre_run(gs, params)
    ---@cast p SetLimitParams

    local entity = game.get_entity_by_unit_number(p.unit_number)
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
            unit_number = entity.unit_number,
            entity_name = entity.name,
            entity_type = entity.type,
            inventory_type = p.inventory_type,
            previous_limit = current_limit,
            new_limit = p.limit,
            action = "no_op",
            message = "Inventory already has this limit",
            affected_unit_numbers = { entity.unit_number }
        }, p)
    end

    -- Set the limit
    target_inventory.set_bar(p.limit)

    local result = {
        unit_number = entity.unit_number,
        entity_name = entity.name,
        entity_type = entity.type,
        inventory_type = p.inventory_type,
        previous_limit = current_limit,
        new_limit = p.limit,
        action = "set",
        affected_unit_numbers = { entity.unit_number }
    }
    
    return self:_post_run(result, p)
end

return SetLimitAction
