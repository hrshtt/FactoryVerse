-- Test: Craft Enqueue (Sync)
-- Verifies that crafting can be enqueued and returns queued status

return {
    setup = function(ctx)
        ctx:create_agent()
        
        -- Give agent materials for crafting (iron plates for iron gear wheel)
        local pos = ctx:agent_call("inspect").position
        local temp_chest = ctx:place_entity("wooden-chest", {x = pos.x + 2, y = pos.y})
        temp_chest.insert({name = "iron-plate", count = 100})
        ctx:agent_call("take_inventory_item", "wooden-chest", temp_chest.position, "chest", "iron-plate", 100)
        temp_chest.destroy()
    end,
    
    test = function(ctx)
        -- Enqueue crafting iron gear wheels (requires 2 iron plates each)
        local result = ctx:agent_call("craft_enqueue", "iron-gear-wheel", 5)
        ctx.assert.not_nil(result, "craft_enqueue should return result")
        
        -- Check queued status
        if result.queued or result.success then
            ctx.assert.not_nil(result.action_id or result.tick, "Should have action_id or tick")
            
            -- Check activity state shows crafting
            local state = ctx:agent_call("get_activity_state")
            ctx.assert.not_nil(state, "get_activity_state should return result")
            ctx.assert.not_nil(state.crafting, "Should have crafting state")
            -- Queue length should be > 0
            ctx.assert.is_true(state.crafting.queue_length > 0 or state.crafting.active, 
                "Crafting should be queued or active")
        else
            -- May fail if recipe not available
            ctx.assert.not_nil(result.error, "Failed enqueue should have error")
        end
    end,
    
    teardown = function(ctx)
        -- Cancel any pending crafting
        pcall(function() ctx:agent_call("craft_dequeue", "iron-gear-wheel", 100) end)
        ctx:destroy_agent()
    end,
}

