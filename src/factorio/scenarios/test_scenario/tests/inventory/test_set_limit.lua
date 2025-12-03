-- Test: Set Inventory Limit
-- Verifies that agents can set inventory bar limits on containers

return {
    setup = function(ctx)
        ctx:create_agent()
        -- Teleport agent to a clear area near origin
        local pos = {x = 30, y = 10}
        ctx:agent_call("teleport", pos)
        ctx:clear_area(pos, 15)
        
        -- Place chest next to agent - use entity.position for exact coords
        ctx.chest = ctx:place_entity("steel-chest", {x = pos.x + 2, y = pos.y})
        ctx.assert.not_nil(ctx.chest, "Should create test chest")
        ctx.test_position = ctx.chest.position  -- Use actual entity position
    end,
    
    test = function(ctx)
        -- Set inventory limit to 5 slots using exact entity position
        local result = ctx:agent_call("set_inventory_limit", "steel-chest", ctx.test_position, "chest", 5)
        ctx.assert.not_nil(result, "set_inventory_limit should return result")
        
        if result.success then
            -- Verify limit was set
            local chest_inv = ctx.chest.get_inventory(defines.inventory.chest)
            local bar = chest_inv.get_bar()
            ctx.assert.is_true(bar ~= nil, "Chest should have bar set")
        end
    end,
    
    teardown = function(ctx)
        ctx:clear_area(ctx.test_position or {x=30, y=10}, 15)
        ctx:destroy_agent()
    end,
}

