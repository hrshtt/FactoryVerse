local Action = require("types.Action")

--- @class SetItemParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field entity_name string Entity prototype name
--- @field position table|nil Optional position: { x = number, y = number }
--- @field items table[] Array of items to transfer: [{name: string, count: number}, ...]
local SetItemParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    entity_name = { type = "string", required = true },
    position = { type = "table", required = false },
    items = { type = "table", required = true }
})

--- @class SetItemAction : Action
local SetItemAction = Action:new("entity.inventory.set_item", SetItemParams)

--- @param params SetItemParams
--- @return table result Data about the item transfer
function SetItemAction:run(params)
    local p = self:_pre_run(params)
    ---@cast p SetItemParams

    -- Get agent (LuaEntity)
    local agent = self.game_state.agent:get_agent(p.agent_id)
    if not agent or not agent.valid then
        error("Agent not found or invalid")
    end

    -- Find entity within agent's build_distance
    local agent_pos = agent.position
    local build_distance = agent.build_distance or 10
    local surface = game.surfaces[1]
    local entity = nil
    
    if p.position and type(p.position.x) == "number" and type(p.position.y) == "number" then
        -- Try exact position first
        entity = surface.find_entity(p.entity_name, { x = p.position.x, y = p.position.y })
        if entity and entity.valid then
            -- Verify within build_distance
            local dx = entity.position.x - agent_pos.x
            local dy = entity.position.y - agent_pos.y
            local dist_sq = dx * dx + dy * dy
            if dist_sq > build_distance * build_distance then
                entity = nil
            end
        end
    end

    -- If not found at exact position, search within radius
    if not entity or not entity.valid then
        local entities = surface.find_entities_filtered({
            position = agent_pos,
            radius = build_distance,
            name = p.entity_name
        })
        
        -- Filter to valid entities
        local valid_entities = {}
        for _, e in ipairs(entities) do
            if e and e.valid then
                table.insert(valid_entities, e)
            end
        end
        
        if #valid_entities == 0 then
            error("Entity '" .. p.entity_name .. "' not found within build_distance of agent")
        elseif #valid_entities > 1 then
            error("Multiple entities '" .. p.entity_name .. "' found. Provide position parameter to specify which entity.")
        else
            entity = valid_entities[1]
        end
    end

    -- Process each item (items is already validated as array of {name: string, count: number})
    local processed_items = {}
    local total_removed = 0
    local total_inserted = 0

    for i, item in ipairs(p.items) do
        local item_name = item.name
        local item_count = item.count or 1
        
        -- Get available count first (needed for stack keyword resolution)
        local agent_has = agent.get_item_count(item_name)
        
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
            -- Validation: Check if agent has the requested count
            if agent_has < item_count then
                error("Agent does not have enough items. Has: " .. agent_has .. ", needs: " .. item_count)
            end
        end
        
        local items_spec = { name = item_name, count = item_count }

        -- Escrow: Insert into entity first (try to insert requested amount)
        local inserted = entity.insert(items_spec)
        if inserted == 0 then
            error("Entity cannot accept " .. item_count .. " items of: " .. item_name)
    end

        -- Remove from agent only what was successfully inserted
        local removed = agent.remove_item({ name = item_name, count = inserted })
        if removed < inserted then
            -- This shouldn't happen since we validated agent has items, but handle it
            -- Remove what we couldn't remove from entity
            entity.remove_item({ name = item_name, count = inserted - removed })
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

    local result = {
        position = { x = entity.position.x, y = entity.position.y },
        entity_name = entity.name,
        entity_type = entity.type,
        items = processed_items,
        total_removed = total_removed,
        total_inserted = total_inserted,
        affected_positions = { 
            { 
                position = { x = entity.position.x, y = entity.position.y },
                entity_name = p.entity_name,
                entity_type = entity.type
            }
        }
    }
    
    return self:_post_run(result, p)
end

return { action = SetItemAction, params = SetItemParams }
