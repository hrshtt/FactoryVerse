local Action = require("core.action.Action")
local ParamSpec = require("core.action.ParamSpec")
local GameState = require("core.game_state.GameState")

local gs = GameState:new()

--- @class GetItemParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field unit_number number Unique identifier for the target entity
--- @field item string|table Item name to get, or table of {item_name = count}, or "ALL_ITEMS"
--- @field count number|nil Number of items to get (ignored if item is table or "ALL_ITEMS")
--- @field inventory_type string|nil Inventory type string (e.g., "chest", "modules", "fuel")
local GetItemParams = ParamSpec:new({
    agent_id = { type = "number", required = true },
    unit_number = { type = "number", required = true },
    item = { type = "any", required = true },
    count = { type = "number", required = false, default = 1 },
    inventory_type = { type = "string", required = false }
})

--- @class GetItemAction : Action
local GetItemAction = Action:new("entity.inventory.get_item", GetItemParams)

--- Auto-resolve inventory type for unambiguous cases
--- @param entity LuaEntity
--- @return string|nil, string|nil
local function auto_resolve_inventory_type(entity)
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
    
    -- Default to first available inventory
    if #available_inventories > 0 then
        return available_inventories[1], nil
    end
    
    return nil, "No suitable inventory found"
end

--- Get all items from entity inventory
--- @param inventory LuaInventory
--- @return table Items with counts
local function get_all_items_from_inventory(inventory)
    local contents = inventory.get_contents()
    return contents or {}
end

--- @param params GetItemParams
--- @return table result Data about the item transfer
function GetItemAction:run(params)
    local p = self:_pre_run(gs, params)
    ---@cast p GetItemParams

    local entity = game.get_entity_by_unit_number(p.unit_number)
    if not entity or not entity.valid then
        error("Entity not found or invalid")
    end

    local agent = gs:agent_state():get_agent(p.agent_id)
    if not agent then
        error("Agent not found")
    end
    local agent_inventory = agent.get_inventory(defines.inventory.character_main)
    if not agent_inventory then
        error("Agent inventory not found")
    end

    -- Resolve inventory type
    local inventory_type_name = p.inventory_type
    if not inventory_type_name then
        inventory_type_name, error_msg = auto_resolve_inventory_type(entity)
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

    local items_to_get = {}
    
    -- Handle different item parameter types
    if p.item == "ALL_ITEMS" then
        -- Get all items from the inventory
        items_to_get = get_all_items_from_inventory(target_inventory)
    elseif type(p.item) == "table" then
        -- Batch operation: table of {item_name = count}
        items_to_get = p.item
    else
        -- Single item operation
        items_to_get = {}
        items_to_get[p.item] = p.count
    end

    local transfer_results = {}
    local total_transferred = 0
    local inventory_changes_agent = {}
    local inventory_changes_entity = {}

    -- Process each item
    for item_name, requested_count in pairs(items_to_get) do
        -- Get available count in entity inventory
        local available_count = target_inventory.get_item_count(item_name)
        if available_count == 0 then
            transfer_results[item_name] = {
                requested = requested_count,
                available = 0,
                transferred = 0,
                reason = "not_available"
            }
            goto continue
        end

        -- Calculate how many we can actually transfer
        local count_to_transfer = math.min(requested_count, available_count)
        
        -- Check how many the agent can accept
        local can_accept = agent_inventory.can_insert({name = item_name, count = count_to_transfer})
        local actual_transfer = math.min(count_to_transfer, can_accept or 0)
        
        if actual_transfer > 0 then
            -- Remove from entity inventory
            local removed = target_inventory.remove({name = item_name, count = actual_transfer})
            if removed > 0 then
                -- Insert into agent inventory
                local inserted = agent_inventory.insert({name = item_name, count = removed})
                if inserted > 0 then
                    transfer_results[item_name] = {
                        requested = requested_count,
                        available = available_count,
                        transferred = inserted,
                        reason = inserted < requested_count and "partial" or "complete"
                    }
                    total_transferred = total_transferred + inserted
                    
                    -- Track inventory changes
                    inventory_changes_agent[item_name] = (inventory_changes_agent[item_name] or 0) + inserted
                    inventory_changes_entity[item_name] = (inventory_changes_entity[item_name] or 0) - inserted
                else
                    -- Failed to insert, put back in entity
                    target_inventory.insert({name = item_name, count = removed})
                    transfer_results[item_name] = {
                        requested = requested_count,
                        available = available_count,
                        transferred = 0,
                        reason = "agent_inventory_full"
                    }
                end
            else
                transfer_results[item_name] = {
                    requested = requested_count,
                    available = available_count,
                    transferred = 0,
                    reason = "failed_to_remove"
                }
            end
        else
            transfer_results[item_name] = {
                requested = requested_count,
                available = available_count,
                transferred = 0,
                reason = "agent_inventory_full"
            }
        end
        
        ::continue::
    end

    local result = {
        unit_number = entity.unit_number,
        entity_name = entity.name,
        entity_type = entity.type,
        inventory_type = inventory_type_name,
        items_requested = items_to_get,
        transfer_results = transfer_results,
        total_transferred = total_transferred,
        affected_unit_numbers = { entity.unit_number },
        affected_inventories = {
            {
                owner_type = "agent",
                owner_id = p.agent_id,
                inventory_type = "character_main",
                changes = inventory_changes_agent
            },
            {
                owner_type = "entity",
                owner_id = p.unit_number,
                inventory_type = inventory_type_name,
                changes = inventory_changes_entity
            }
        }
    }
    
    return self:_post_run(result, p)
end

return GetItemAction
