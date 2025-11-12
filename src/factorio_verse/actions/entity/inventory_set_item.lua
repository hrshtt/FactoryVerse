local Action = require("types.Action")
local GameContext = require("game_state.GameContext")

--- @class SetItemParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field entity_name string Entity prototype name
--- @field position table|nil Optional position: { x = number, y = number }
--- @field items table[] Array of items to transfer: [{name: string, count: number}, ...]
local SetItemParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    entity_name = { type = "entity_name", required = true },
    position = { type = "position", required = false },
    items = { type = "item_stack", required = true }
})

--- @class SetItemAction : Action
local SetItemAction = Action:new("entity.inventory_set_item", SetItemParams)

--- @class SetItemContext
--- @field agent LuaEntity Agent character entity
--- @field entity LuaEntity Target entity
--- @field entity_proto table Entity prototype
--- @field inventory LuaInventory Entity inventory
--- @field items table[] Array of items to transfer: [{name: string, count: number}, ...]
--- @field params SetItemParams ParamSpec instance for _post_run

--- Override _pre_run to build context using GameContext
--- @param params SetItemParams|table|string
--- @return SetItemContext
function SetItemAction:_pre_run(params)
    -- Call parent to get validated ParamSpec
    local p = Action._pre_run(self, params)
    local params_table = p:get_values()
    
    -- Build context using GameContext
    local agent = GameContext.resolve_agent(params_table, self.game_state)
    local entity, entity_proto = GameContext.resolve_entity(params_table, agent)
    local inventory = GameContext.resolve_inventory(entity, defines.inventory.chest)
    
    -- Return context for run()
    return {
        agent = agent,
        entity = entity,
        entity_proto = entity_proto,
        inventory = inventory,
        items = params_table.items,
        params = p
    }
end

--- @param params SetItemParams|table|string
--- @return table result Data about the item transfer
function SetItemAction:run(params)
    --- @type SetItemContext
    local context = self:_pre_run(params)

    -- Process each item (items is already validated as array of {name: string, count: number})
    local processed_items = {}
    local total_removed = 0
    local total_inserted = 0

    for i, item in ipairs(context.items) do
        local item_name = item.name
        local item_count = item.count or 1
        
        -- Get available count first (needed for stack keyword resolution)
        local agent_has = context.agent.get_item_count(item_name)
        
        -- Handle special keywords
        if item_count == "MAX" then
            item_count = agent_has
            if item_count == 0 then
                error("Agent has no items of: " .. item_name)
            end
        elseif item_count == "FULL-STACK" or item_count == "HALF-STACK" then
            local item_proto = prototypes and prototypes.item and prototypes.item[item_name]
            if not item_proto then
                error("Unknown item: " .. item_name)
            end
            local stack_size = item_proto.stack_size
            if item_count == "FULL-STACK" then
                item_count = math.min(stack_size, agent_has)
            else -- HALF-STACK: half of available (up to half of stack_size)
                item_count = math.floor(math.min(agent_has, stack_size) / 2)
            end
            if item_count == 0 then
                error("Agent has no items of: " .. item_name)
            end
        else
            -- Logical validation: Check if agent has the requested count
            if agent_has < item_count then
                error("Agent does not have enough items. Has: " .. agent_has .. ", needs: " .. item_count)
            end
        end
        
        local items_spec = { name = item_name, count = item_count }

        -- Escrow: Insert into entity first (try to insert requested amount)
        local inserted = context.entity.insert(items_spec)
        if inserted == 0 then
            error("Entity cannot accept " .. item_count .. " items of: " .. item_name)
    end

        -- Remove from agent only what was successfully inserted
        local removed = context.agent.remove_item({ name = item_name, count = inserted })
        if removed < inserted then
            -- This shouldn't happen since we validated agent has items, but handle it
            -- Remove what we couldn't remove from entity
            context.entity.remove_item({ name = item_name, count = inserted - removed })
            error("Failed to remove inserted items from agent. Inserted: " .. inserted .. 
                  ", removed: " .. removed)
        end

        -- Track successful transfer
        table.insert(processed_items, {
            name = item_name,
            requested = item_count,
            inserted = inserted,
            removed = removed
        })
        total_removed = total_removed + removed
        total_inserted = total_inserted + inserted
    end

    local params_table = context.params:get_values()
    local result = {
        position = { x = context.entity.position.x, y = context.entity.position.y },
        entity_name = context.entity.name,
        entity_type = context.entity.type,
        items = processed_items,
        total_removed = total_removed,
        total_inserted = total_inserted,
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

return { action = SetItemAction, params = SetItemParams }
