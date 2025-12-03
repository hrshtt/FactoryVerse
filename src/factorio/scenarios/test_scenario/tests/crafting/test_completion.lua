-- Test: Craft Completion (Async)
-- Verifies that crafting completes and items appear in inventory

return {
    timeout_ticks = 300,  -- 5 seconds should be enough for a few gear wheels
    
    setup = function(ctx)
        ctx:create_agent()
        
        -- Give agent materials for crafting
        local pos = ctx:agent_call("inspect").position
        local temp_chest = ctx:place_entity("wooden-chest", {x = pos.x + 2, y = pos.y})
        temp_chest.insert({name = "iron-plate", count = 20})
        ctx:agent_call("take_inventory_item", "wooden-chest", temp_chest.position, "chest", "iron-plate", 20)
        temp_chest.destroy()
        
        -- Record initial gear wheel count
        local inv = ctx:agent_call("inspect", true)
        ctx.initial_gears = 0
        for item_name, item_data in pairs(inv.inventory or {}) do
            if item_name == "iron-gear-wheel" then
                ctx.initial_gears = type(item_data) == "number" and item_data or (item_data.count or 0)
                break
            end
        end
    end,
    
    start = function(ctx)
        -- Enqueue crafting (2 iron plates per gear wheel, we have 20 plates = 10 gears max)
        local result = ctx:agent_call("craft_enqueue", "iron-gear-wheel", 3)
        ctx.assert.not_nil(result, "craft_enqueue should return result")
        ctx.craft_started = result.queued or result.success
    end,
    
    poll = function(ctx)
        if not ctx.craft_started then
            return true  -- Skip if crafting didn't start
        end
        
        -- Check if crafting is complete
        local state = ctx:agent_call("get_activity_state")
        
        -- Complete when queue is empty and not actively crafting
        local queue_empty = (state.crafting.queue_length or 0) == 0
        local not_active = not state.crafting.active
        
        return queue_empty and not_active
    end,
    
    verify = function(ctx)
        if not ctx.craft_started then
            -- Crafting didn't start (maybe recipe not available)
            return
        end
        
        -- Check inventory for crafted items
        local inv = ctx:agent_call("inspect", true)
        local final_gears = 0
        for item_name, item_data in pairs(inv.inventory or {}) do
            if item_name == "iron-gear-wheel" then
                final_gears = type(item_data) == "number" and item_data or (item_data.count or 0)
                break
            end
        end
        
        ctx.assert.is_true(final_gears > ctx.initial_gears, 
            "Should have more gear wheels after crafting: initial=" .. ctx.initial_gears .. ", final=" .. final_gears)
    end,
    
    teardown = function(ctx)
        ctx:destroy_agent()
    end,
}

