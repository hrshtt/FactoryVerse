local Action = require("types.Action")
local GameContext = require("types.GameContext")

--- @class PickupEntityParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field position table Position of the target entity: { x = number, y = number }
--- @field entity_name string Entity prototype name
local PickupEntityParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    position = { type = "position", required = true },
    entity_name = { type = "entity_name", required = true }
})

--- @class PickupEntityAction : Action
local PickupEntityAction = Action:new("entity.pickup", PickupEntityParams)

--- @class PickupEntityContext
--- @field agent LuaEntity Agent character entity
--- @field entity LuaEntity Target entity
--- @field entity_proto table Entity prototype
--- @field params PickupEntityParams ParamSpec instance for _post_run

--- Override _pre_run to build context using GameContext
--- @param params PickupEntityParams|table|string
--- @return PickupEntityContext
function PickupEntityAction:_pre_run(params)
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
        params = p
    }
end

--- Extract all inventories from an entity before mining
--- @param entity LuaEntity
--- @return table All items from all inventories
local function extract_entity_inventories(entity)
    local all_items = {}
    
    -- Inventory types to check (from EntitiesSnapshot.lua)
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
            return entity.get_inventory(inventory_type)
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

--- @param params PickupEntityParams|table|string
--- @return table result Data about the picked up entity and items
function PickupEntityAction:run(params)
    --- @type PickupEntityContext
    local context = self:_pre_run(params)

    -- Logical validation: Check if entity is minable
    if not context.entity.minable then
        error("Entity is not minable")
    end
    local agent_inventory = context.agent.get_inventory(defines.inventory.character_main)
    if not agent_inventory then
        error("Agent inventory not found")
    end

    context.agent.update_selected_entity(context.entity.position)

    local e_inventory = extract_entity_inventories(context.entity)

    local result = context.agent.mine_entity(context.agent.selected)
    if not result then
        error("Failed to mine entity")
    end

    local response = {
        success = true,
        items_obtained = e_inventory,
        picked_up_entity = { position = context.entity.position, name = context.entity.name, type = context.entity.type },
    }
    
    return self:_post_run(response, context.params)
end

return { action = PickupEntityAction, params = PickupEntityParams }
