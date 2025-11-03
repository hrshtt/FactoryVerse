local Action = require("types.Action")
local GameState = require("core.game_state.GameState")

local gs = GameState:new()

--- @class SetItemParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field position_x number X coordinate of the target entity
--- @field position_y number Y coordinate of the target entity
--- @field entity_name string Entity prototype name
--- @field item string Name of the item to insert
--- @field count number|nil Number of items to insert (defaults to 1)
--- @field inventory_type string|nil Inventory type string (e.g., "chest", "modules", "fuel")
local SetItemParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    position_x = { type = "number", required = true },
    position_y = { type = "number", required = true },
    entity_name = { type = "string", required = true },
    item = { type = "string", required = true },
    count = { type = "number", required = false, default = 1 },
    inventory_type = { type = "string", required = false }
})

--- @class SetItemAction : Action
local SetItemAction = Action:new("entity.inventory.set_item", SetItemParams)

--- Auto-resolve inventory type for unambiguous cases
--- @param entity LuaEntity
--- @param item_name string
--- @return string|nil, string|nil
local function auto_resolve_inventory_type(entity, item_name)
    -- Get item prototype to check type
    local item_proto = prototypes and prototypes.item and prototypes.item[item_name]
    if not item_proto then
        return nil, "Unknown item: " .. item_name
    end
    
    -- Check available inventory types
    local available_inventories = {}
    local inventory_types = {
        chest = defines.inventory.chest,
        fuel = defines.inventory.fuel,
        modules = defines.inventory.assembling_machine_modules,
        input = defines.inventory.assembling_machine_input,
        output = defines.inventory.assembling_machine_output,
        ammo = defines.inventory.turret_ammo,
    }
    
    for name, inv_type in pairs(inventory_types) do
        local success, inventory = pcall(function()
            return entity.get_inventory(inv_type)
        end)
        if success and inventory and inventory.valid then
            table.insert(available_inventories, name)
        end
    end
    
    -- If only one inventory available, use it
    if #available_inventories == 1 then
        return available_inventories[1], nil
    end
    
    -- Check for module ambiguity (modules can go to modules or input)
    if item_proto.module_effects then
        local has_modules = false
        local has_input = false
        for _, inv_name in ipairs(available_inventories) do
            if inv_name == "modules" then has_modules = true end
            if inv_name == "input" then has_input = true end
        end
        
        if has_modules and has_input then
            return nil, "Ambiguous: specify inventory_type ('modules' or 'input') for module items"
        end
    end
    
    -- Check for fuel ambiguity
    if item_proto.fuel_value and item_proto.fuel_value > 0 then
        local has_fuel = false
        local has_input = false
        for _, inv_name in ipairs(available_inventories) do
            if inv_name == "fuel" then has_fuel = true end
            if inv_name == "input" then has_input = true end
        end
        
        if has_fuel and has_input then
            return nil, "Ambiguous: specify inventory_type ('fuel' or 'input') for fuel items"
        end
    end
    
    -- Default to first available inventory
    if #available_inventories > 0 then
        return available_inventories[1], nil
    end
    
    return nil, "No suitable inventory found for item: " .. item_name
end

--- @param params SetItemParams
--- @return table result Data about the item insertion
function SetItemAction:run(params)
    local p = self:_pre_run(gs, params)
    ---@cast p SetItemParams

    local position = { x = p.position_x, y = p.position_y }
    local entity = game.surfaces[1].find_entity(p.entity_name, position)
    if not entity or not entity.valid then
        error("Entity not found or invalid")
    end

    local agent = gs:agent():get_agent(p.agent_id)
    if not agent then
        error("Agent not found")
    end
    local agent_inventory = agent.get_inventory(defines.inventory.character_main)
    if not agent_inventory then
        error("Agent inventory not found")
    end

    -- Check if agent has the item
    local agent_item_count = agent_inventory.get_item_count(p.item)
    if agent_item_count < p.count then
        error("Agent does not have enough items. Has: " .. agent_item_count .. ", needs: " .. p.count)
    end

    -- Resolve inventory type
    local inventory_type_name = p.inventory_type
    if not inventory_type_name then
        inventory_type_name, error_msg = auto_resolve_inventory_type(entity, p.item)
        if not inventory_type_name then
            error(error_msg)
        end
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
    
    local inventory_type = inventory_type_map[inventory_type_name]
    if not inventory_type then
        error("Invalid inventory_type: " .. inventory_type_name)
    end

    -- Get target inventory
    local target_inventory = entity.get_inventory(inventory_type)
    if not target_inventory or not target_inventory.valid then
        error("Entity does not have inventory type: " .. inventory_type_name)
    end

    -- Check if inventory can accept the item
    local can_insert = target_inventory.can_insert({name = p.item, count = p.count})
    if not can_insert then
        error("Inventory cannot accept " .. p.count .. " items of: " .. p.item)
    end

    -- Remove items from agent inventory
    local removed = agent_inventory.remove({name = p.item, count = p.count})
    if removed < p.count then
        error("Failed to remove items from agent inventory")
    end

    -- Insert items into target inventory
    local inserted = target_inventory.insert({name = p.item, count = p.count})
    if inserted < p.count then
        -- This shouldn't happen since we checked can_insert, but handle gracefully
        -- Put remaining items back in agent inventory
        local remaining = p.count - inserted
        agent_inventory.insert({name = p.item, count = remaining})
        error("Failed to insert all items. Inserted: " .. inserted .. ", remaining: " .. remaining)
    end

    local result = {
        position = position,
        entity_name = entity.name,
        entity_type = entity.type,
        item = p.item,
        count = p.count,
        inventory_type = inventory_type_name,
        inserted = inserted,
        affected_positions = { { position = position, entity_name = p.entity_name, entity_type = entity.type } },
        affected_inventories = {
            {
                owner_type = "agent",
                owner_id = p.agent_id,
                inventory_type = "character_main",
                changes = { [p.item] = -p.count } -- Negative: items removed from agent
            },
            {
                owner_type = "entity",
                owner_position = position,
                owner_name = p.entity_name,
                inventory_type = inventory_type_name,
                changes = { [p.item] = p.count } -- Positive: items added to entity
            }
        }
    }
    
    return self:_post_run(result, p)
end

return { action = SetItemAction, params = SetItemParams }
