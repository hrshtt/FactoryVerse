local Action = require("types.Action")

--- @class PickupEntityParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field position table Position of the target entity: { x = number, y = number }
--- @field entity_name string Entity prototype name
local PickupEntityParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    position = { type = "table", required = true },
    entity_name = { type = "string", required = true }
})

--- @class PickupEntityAction : Action
local PickupEntityAction = Action:new("entity.pickup", PickupEntityParams)

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

--- @param params PickupEntityParams
--- @return table result Data about the picked up entity and items
function PickupEntityAction:run(params)
    local p = self:_pre_run(params)
    ---@cast p PickupEntityParams

    local position = p.position
    local entity = game.surfaces[1].find_entity(p.entity_name, position)
    if not entity or not entity.valid then
        error("Entity not found or invalid")
    end

    -- Check if entity is minable
    if not entity.minable then
        error("Entity is not minable")
    end

    local agent = self.game_state.agent:get_agent(p.agent_id)
    if not agent then
        error("Agent not found")
    end
    local agent_inventory = agent.get_inventory(defines.inventory.character_main)
    if not agent_inventory then
        error("Agent inventory not found")
    end

    agent.update_selected_entity(entity.position)

    local e_inventory = extract_entity_inventories(entity)

    local result = agent.mine_entity(agent.selected)
    if not result then
        error("Failed to mine entity")
    end

    local response = {
        success = true,
        items_obtained = e_inventory,
        picked_up_entity = { position = entity.position, name = entity.name, type = entity.type },
    }
    
    return self:_post_run(response, p)
end

return { action = PickupEntityAction, params = PickupEntityParams }
