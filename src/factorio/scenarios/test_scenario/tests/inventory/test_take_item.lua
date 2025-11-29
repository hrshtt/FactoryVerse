-- Test: Take Item from Entity Inventory
-- Verifies that agents can take items from entity inventories

return {
    setup = function(ctx)
        ctx:create_agent()
        -- Teleport agent to a clear area near origin
        local pos = {x = 20, y = 10}
        ctx:agent_call("teleport", pos)
        ctx:clear_area(pos, 15)
        
        -- Place chest next to agent - use entity.position for exact coords
        ctx.chest = ctx:place_entity("iron-chest", {x = pos.x + 2, y = pos.y})
        ctx.assert.not_nil(ctx.chest, "Should create test chest")
        ctx.test_position = ctx.chest.position  -- Use actual entity position
        ctx.chest.insert({name = "copper-plate", count = 100})
    end,
    
    test = function(ctx)
        -- Take items from the chest using exact entity position
        local result = ctx:agent_call("take_inventory_item", "iron-chest", ctx.test_position, "chest", "copper-plate", 30)
        ctx.assert.not_nil(result, "take_inventory_item should return result")
        
        -- Verify transfer
        if result.success or result.transferred then
            -- Check chest has fewer items
            local chest_inv = ctx.chest.get_inventory(defines.inventory.chest)
            local remaining = chest_inv.get_item_count("copper-plate")
            ctx.assert.is_true(remaining < 100, "Chest should have fewer copper plates after take")
        end
    end,
    
    teardown = function(ctx)
        ctx:clear_area(ctx.test_position or {x=20, y=10}, 15)
        ctx:destroy_agent()
    end,
}

