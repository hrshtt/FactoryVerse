local Action = require("types.Action")

--- @class GetItemParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field position table Position of the target entity: { x = number, y = number }
--- @field entity_name string Entity prototype name
--- @field item string Name of the item to retrieve
--- @field count number|nil Number of items to retrieve (defaults to 1)
--- @field inventory_type string|nil Inventory type string (e.g., "output", "input", "chest", "fuel"). Defaults to "output" if not specified.
local GetItemParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    position = { type = "table", required = true },
    entity_name = { type = "string", required = true },
    item = { type = "string", required = true },
    count = { type = "number", required = false, default = 1 },
    inventory_type = { type = "string", required = false }
})

--- @class GetItemAction : Action
local GetItemAction = Action:new("entity.inventory.get_item", GetItemParams)

--- Map inventory type name to defines.inventory constant
--- @param inventory_type_name string
--- @return defines.inventory|nil, string|nil
local function map_inventory_type(inventory_type_name)
    local inventory_type_map = {
        chest = defines.inventory.chest,
        fuel = defines.inventory.fuel,
        modules = defines.inventory.assembling_machine_modules,
        input = defines.inventory.assembling_machine_input,
        output = defines.inventory.assembling_machine_output,
        ammo = defines.inventory.turret_ammo,
        trunk = defines.inventory.car_trunk,
        cargo = defines.inventory.cargo_wagon,
    }
    
    local inventory_type = inventory_type_map[inventory_type_name]
    if not inventory_type then
        local available_types = {}
        for name, _ in pairs(inventory_type_map) do
            table.insert(available_types, name)
        end
        return nil, "Invalid inventory_type: " .. inventory_type_name .. 
                    ". Available: " .. table.concat(available_types, ", ")
    end
    
    return inventory_type, nil
end

--- @param params GetItemParams
--- @return table result Data about the item retrieval
function GetItemAction:run(params)
    local p = self:_pre_run(params)
    ---@cast p GetItemParams

    -- Resolve entity position
    local position = { x = p.position.x, y = p.position.y }
    local entity = game.surfaces[1].find_entity(p.entity_name, position)
    if not entity or not entity.valid then
        error("Entity not found or invalid")
    end

    -- Get agent and agent inventory
    local agent = self.game_state.agent:get_agent(p.agent_id)
    if not agent then
        error("Agent not found")
    end
    local agent_inventory = agent.get_inventory(defines.inventory.character_main)
    if not agent_inventory then
        error("Agent inventory not found")
    end

    -- Default to "output" inventory if not specified
    local inventory_type_name = p.inventory_type or "output"
    
    -- Map inventory type name to defines constant
    local inventory_type, error_msg = map_inventory_type(inventory_type_name)
    if not inventory_type then
        error(error_msg)
    end

    -- Get source inventory from entity
    local source_inventory = entity.get_inventory(inventory_type)
    if not source_inventory or not source_inventory.valid then
        error("Entity does not have inventory type: " .. inventory_type_name)
    end

    -- Check if source inventory has enough items
    local available_count = source_inventory.get_item_count(p.item)
    if available_count < p.count then
        error("Entity inventory does not have enough items. Has: " .. 
              available_count .. ", needs: " .. p.count)
    end

    -- Check if agent inventory has space for the items
    local can_insert = agent_inventory.can_insert({name = p.item, count = p.count})
    if not can_insert then
        error("Agent inventory cannot accept " .. p.count .. " items of: " .. p.item)
    end

    -- Remove items from entity inventory
    local removed = source_inventory.remove({name = p.item, count = p.count})
    if removed < p.count then
        error("Failed to remove items from entity inventory. Removed: " .. removed .. 
              ", requested: " .. p.count)
    end

    -- Insert items into agent inventory
    local inserted = agent_inventory.insert({name = p.item, count = p.count})
    if inserted < p.count then
        -- Rollback: return items to entity inventory if insertion fails
        local remaining = p.count - inserted
        source_inventory.insert({name = p.item, count = remaining})
        error("Failed to insert all items into agent inventory. Inserted: " .. 
              inserted .. ", remaining: " .. remaining)
    end

    -- Build result structure
    local result = {
        position = position,
        entity_name = entity.name,
        entity_type = entity.type,
        item = p.item,
        count = p.count,
        inventory_type = inventory_type_name,
        retrieved = inserted,
        affected_positions = { 
            { 
                position = position, 
                entity_name = p.entity_name, 
                entity_type = entity.type 
            } 
        },
        affected_inventories = {
            {
                owner_type = "entity",
                owner_position = position,
                owner_name = p.entity_name,
                inventory_type = inventory_type_name,
                changes = { [p.item] = -p.count } -- Negative: items removed from entity
            },
            {
                owner_type = "agent",
                owner_id = p.agent_id,
                inventory_type = "character_main",
                changes = { [p.item] = p.count } -- Positive: items added to agent
            }
        }
    }
    
    return self:_post_run(result, p)
end

return { action = GetItemAction, params = GetItemParams }

