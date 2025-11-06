local Action = require("types.Action")

--- @class PickupEntityParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field position_x number X coordinate of the target entity
--- @field position_y number Y coordinate of the target entity
--- @field entity_name string Entity prototype name
local PickupEntityParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    position_x = { type = "number", required = true },
    position_y = { type = "number", required = true },
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

    local position = { x = p.position_x, y = p.position_y }
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

    -- Extract all items from entity inventories before mining
    local entity_items = extract_entity_inventories(entity)
    
    -- Calculate total items that will be obtained (entity + contents)
    local total_items = {}
    -- Add the entity itself
    total_items[entity.name] = 1
    -- Add all inventory contents
    for item_name, count in pairs(entity_items) do
        total_items[item_name] = (total_items[item_name] or 0) + count
    end

    -- Check if agent has enough space for all items
    local can_fit_all = true
    local space_check = {}
    for item_name, count in pairs(total_items) do
        local can_insert = agent_inventory.can_insert({name = item_name, count = count})
        space_check[item_name] = can_insert
        if not can_insert then
            can_fit_all = false
        end
    end

    if not can_fit_all then
        local missing_items = {}
        for item_name, count in pairs(total_items) do
            local can_insert = space_check[item_name]
            if not can_insert then
                missing_items[item_name] = count - (agent_inventory.get_item_count(item_name) or 0) -- Calculate missing count
            end
        end
        local missing_str = ""
        for item_name, count in pairs(missing_items) do
            if missing_str ~= "" then missing_str = missing_str .. ", " end
            missing_str = missing_str .. item_name .. ":" .. count
        end
        error("Agent inventory insufficient space for entity pickup. Missing space for: " .. missing_str)
    end

    -- Store entity position for removal tracking
    local entity_position = entity.position
    local entity_name = entity.name
    local entity_type = entity.type

    -- Mine the entity (this destroys it and returns items)
    -- entity.mine() with inventory parameter automatically inserts all mined items
    -- (including the entity itself and all inventory contents) into the specified inventory
    local mine_success = entity.mine({inventory = agent_inventory, force = true})
    if not mine_success then
        error("Failed to mine entity")
    end

    -- entity is now invalid after mining, don't access it

    -- Calculate actual items obtained
    -- entity.mine() with inventory parameter auto-inserts all mined items into the inventory
    -- So we use our pre-extracted entity_items as the record
    local actual_items = {}
    -- Add the entity itself
    actual_items[entity_name] = 1
    -- Add all inventory contents that were extracted before mining
    for item_name, count in pairs(entity_items) do
        actual_items[item_name] = count
    end

    -- Calculate inventory changes for mutation contract
    local inventory_changes = {}
    for item_name, count in pairs(actual_items) do
        inventory_changes[item_name] = count -- Positive: items gained
    end

    local result = {
        position = entity_position,
        entity_name = entity_name,
        entity_type = entity_type,
        items_obtained = actual_items,
        removed_positions = { { position = entity_position, entity_name = entity_name } },
        removed_entity = { position = entity_position, name = entity_name },
        affected_inventories = {
            {
                owner_type = "agent",
                owner_id = p.agent_id,
                inventory_type = "character_main",
                changes = inventory_changes
            }
        }
    }
    
    return self:_post_run(result, p)
end

return { action = PickupEntityAction, params = PickupEntityParams }
