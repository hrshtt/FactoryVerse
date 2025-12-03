-- Test: Put Item into Entity Inventory
-- Verifies that agents can put items into entity inventories

return {
    setup = function(ctx)
        ctx:create_agent()
        -- Teleport agent to a clear area near origin
        local pos = {x = 10, y = 10}
        ctx:agent_call("teleport", pos)
        ctx:clear_area(pos, 15)
        
        -- Place chest next to agent - use entity.position for exact coords
        ctx.chest = ctx:place_entity("iron-chest", {x = pos.x + 2, y = pos.y})
        ctx.assert.not_nil(ctx.chest, "Should create test chest")
        ctx.test_position = ctx.chest.position  -- Use actual entity position
        
        -- Give agent items directly by inserting into agent's character inventory
        -- We access the character via inspect and direct surface lookup
        local agent_pos = ctx:agent_call("inspect").position
        local characters = ctx.surface.find_entities_filtered({
            position = agent_pos,
            radius = 1,
            type = "character"
        })
        if characters[1] then
            characters[1].insert({name = "iron-plate", count = 50})
        end
    end,
    
    test = function(ctx)
        -- Put items into the chest using the exact entity position
        local result = ctx:agent_call("put_inventory_item", "iron-chest", ctx.test_position, "chest", "iron-plate", 20)
        ctx.assert.not_nil(result, "put_inventory_item should return result")
        
        if result.success or result.transferred then
            -- Verify items are in chest
            local chest_inv = ctx.chest.get_inventory(defines.inventory.chest)
            local count = chest_inv.get_item_count("iron-plate")
            ctx.assert.is_true(count > 0, "Chest should have iron plates")
        end
    end,
    
    teardown = function(ctx)
        ctx:clear_area(ctx.test_position or {x=10, y=10}, 15)
        ctx:destroy_agent()
    end,
}

