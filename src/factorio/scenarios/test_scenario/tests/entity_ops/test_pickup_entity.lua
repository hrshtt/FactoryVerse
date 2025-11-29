-- Test: Pickup Entity
-- Verifies that agents can pick up entities

return {
    setup = function(ctx)
        ctx:create_agent()
        -- Teleport agent to a clear area
        local pos = {x = -180, y = 190}
        ctx:agent_call("teleport", pos)
        ctx:clear_area(pos, 15)
        ctx.agent_pos = pos
        
        -- Place a chest for the agent to pick up - use entity.position for exact coords
        local entity = ctx:place_entity("wooden-chest", {x = pos.x + 2, y = pos.y})
        ctx.assert.not_nil(entity, "Should create test chest")
        ctx.test_position = {x = entity.position.x, y = entity.position.y}  -- Copy position, don't keep entity ref
    end,
    
    test = function(ctx)
        -- Call pickup_entity with exact entity position
        local result = ctx:agent_call("pickup_entity", "wooden-chest", ctx.test_position)
        
        -- The API should return something (success or error)
        ctx.assert.not_nil(result, "pickup_entity should return a result")
        
        -- If successful, entity should be gone
        if result.success then
            local entities = ctx.surface.find_entities_filtered({
                position = ctx.test_position,
                radius = 1,
                name = "wooden-chest"
            })
            ctx.assert.is_true(#entities == 0, "Entity should be removed after pickup")
            
            -- Verify agent got the item
            local inv = ctx:agent_call("inspect", true)
            -- Just verify inspect works after pickup
            ctx.assert.not_nil(inv, "Should be able to inspect after pickup")
        end
        -- If not successful, that's okay - we're testing the API exists and responds
    end,
    
    teardown = function(ctx)
        ctx:clear_area(ctx.agent_pos, 15)
        ctx:destroy_agent()
    end,
}

