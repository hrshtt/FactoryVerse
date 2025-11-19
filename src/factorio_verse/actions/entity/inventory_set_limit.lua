local Action = require("types.Action")
local GameContext = require("types.GameContext")

--- @class SetLimitParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field entity_name string Entity prototype name
--- @field position table|nil Optional position: { x = number, y = number }
--- @field inventory_type string Inventory type string (e.g., "chest", "input", "output")
--- @field limit number Maximum number of slots to allow (0 = unlimited)
local SetLimitParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    entity_name = { type = "entity_name", required = true },
    position = { type = "position", required = false },
    inventory_type = { type = "string", required = true },
    limit = { type = "number", required = true }
})

--- @class SetLimitAction : Action
local SetLimitAction = Action:new("entity.inventory_set_limit", SetLimitParams)

--- @class SetLimitContext
--- @field agent LuaEntity Agent character entity
--- @field entity LuaEntity Target entity
--- @field entity_proto table Entity prototype
--- @field inventory_type string Inventory type string
--- @field limit number Maximum number of slots to allow
--- @field params SetLimitParams ParamSpec instance for _post_run

--- Override _pre_run to build context using GameContext
--- @param params SetLimitParams|table|string
--- @return SetLimitContext
function SetLimitAction:_pre_run(params)
    -- Call parent to get validated ParamSpec
    local p = Action._pre_run(self, params)
    local params_table = p:get_values()
    
    -- Build context using GameContext
    local agent = GameContext.resolve_agent(params_table, self.game_state)
    local entity, entity_proto = GameContext.resolve_entity(params_table, agent)
    
    -- Return context for run()
    return {
        agent = agent,
        entity = entity,
        entity_proto = entity_proto,
        inventory_type = params_table.inventory_type,
        limit = params_table.limit,
        params = p
    }
end

--- @param params SetLimitParams|table|string
--- @return table result Data about the limit change
function SetLimitAction:run(params)
    --- @type SetLimitContext
    local context = self:_pre_run(params)

    -- Map inventory type name to defines constant
    local inventory_type_map = {
        chest = defines.inventory.chest,
        fuel = defines.inventory.fuel,
        modules = defines.inventory.assembling_machine_modules,
        input = defines.inventory.assembling_machine_input,
        output = defines.inventory.assembling_machine_output,
        ammo = defines.inventory.turret_ammo,
    }
    
    local inventory_type = inventory_type_map[context.inventory_type]
    if not inventory_type then
        error("Invalid inventory_type: " .. context.inventory_type)
    end

    -- Get target inventory
    local target_inventory = context.entity.get_inventory(inventory_type)
    if not target_inventory or not target_inventory.valid then
        error("Entity does not have inventory type: " .. context.inventory_type)
    end

    -- Logical validation: Check if inventory supports bar/limit
    if not target_inventory.supports_bar() then
        error("Inventory does not support setting limits")
    end

    -- Logical validation: Validate limit value
    local inventory_size = #target_inventory
    if math.floor(context.limit) ~= context.limit then
        error("Limit must be an integer, got: " .. context.limit)
    end
    if context.limit < 0 or context.limit > inventory_size then
        error("Limit must be between 0 and " .. inventory_size .. " (inventory size). Got: " .. context.limit)
    end

    -- Get current limit for comparison
    local current_limit = target_inventory.get_bar()
    if current_limit == context.limit then
        local params_table = context.params:get_values()
        return self:_post_run({
            position = { x = context.entity.position.x, y = context.entity.position.y },
            entity_name = context.entity.name,
            entity_type = context.entity.type,
            inventory_type = context.inventory_type,
            previous_limit = current_limit,
            new_limit = context.limit,
            action = "no_op",
            message = "Inventory already has this limit",
            affected_positions = { 
                { 
                    position = { x = context.entity.position.x, y = context.entity.position.y },
                    entity_name = params_table.entity_name,
                    entity_type = context.entity.type
                } 
            }
        }, context.params)
    end

    -- Set the limit
    target_inventory.set_bar(context.limit)

    local params_table = context.params:get_values()
    local result = {
        position = { x = context.entity.position.x, y = context.entity.position.y },
        entity_name = context.entity.name,
        entity_type = context.entity.type,
        inventory_type = context.inventory_type,
        previous_limit = current_limit,
        new_limit = context.limit,
        action = "set",
        affected_positions = { 
            { 
                position = { x = context.entity.position.x, y = context.entity.position.y },
                entity_name = params_table.entity_name,
                entity_type = context.entity.type
            } 
        }
    }
    
    return self:_post_run(result, context.params)
end

return { action = SetLimitAction, params = SetLimitParams }
