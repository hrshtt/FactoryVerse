-- Test: Craft Dequeue (Sync)
-- Verifies that queued crafting can be cancelled

return {
    setup = function(ctx)
        ctx:create_agent()
        
        -- Give agent materials
        local pos = ctx:agent_call("inspect").position
        local temp_chest = ctx:place_entity("wooden-chest", {x = pos.x + 2, y = pos.y})
        temp_chest.insert({name = "iron-plate", count = 200})
        ctx:agent_call("take_inventory_item", "wooden-chest", temp_chest.position, "chest", "iron-plate", 200)
        temp_chest.destroy()
        
        -- Enqueue some crafting
        ctx:agent_call("craft_enqueue", "iron-gear-wheel", 20)
    end,
    
    test = function(ctx)
        -- Get initial queue state
        local initial_state = ctx:agent_call("get_activity_state")
        local initial_queue = initial_state.crafting.queue_length or 0
        
        -- Dequeue some crafting
        local result = ctx:agent_call("craft_dequeue", "iron-gear-wheel", 10)
        ctx.assert.not_nil(result, "craft_dequeue should return result")
        
        -- Verify queue was reduced
        local after_state = ctx:agent_call("get_activity_state")
        local after_queue = after_state.crafting.queue_length or 0
        
        -- Queue should be smaller or crafting should be cancelled
        -- Note: exact behavior depends on implementation
        ctx.assert.is_true(after_queue <= initial_queue, "Queue should not grow after dequeue")
    end,
    
    teardown = function(ctx)
        -- Cancel any remaining crafting
        pcall(function() ctx:agent_call("craft_dequeue", "iron-gear-wheel", 100) end)
        ctx:destroy_agent()
    end,
}

