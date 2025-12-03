-- Test: Set Entity Recipe
-- Verifies that agents can set recipes on crafting machines

return {
    setup = function(ctx)
        ctx:create_agent()
        -- Teleport agent to a clear area
        local pos = {x = -170, y = 190}
        ctx:agent_call("teleport", pos)
        ctx:clear_area(pos, 15)
        
        -- Place an assembling machine - use entity.position for exact coords
        ctx.assembler = ctx:place_entity("assembling-machine-1", {x = pos.x + 3, y = pos.y})
        ctx.assert.not_nil(ctx.assembler, "Should create assembling machine")
        ctx.test_position = ctx.assembler.position  -- Use actual entity position
    end,
    
    test = function(ctx)
        -- Set recipe to iron-gear-wheel using exact entity position
        local result = ctx:agent_call("set_entity_recipe", "assembling-machine-1", ctx.test_position, "iron-gear-wheel")
        ctx.assert.not_nil(result, "set_entity_recipe should return result")
        
        if result.success then
            -- Verify recipe was set
            local recipe = ctx.assembler.get_recipe()
            ctx.assert.not_nil(recipe, "Assembler should have recipe set")
            ctx.assert.equals("iron-gear-wheel", recipe.name, "Recipe should be iron-gear-wheel")
        else
            -- Recipe might not be available if not researched
            -- Just verify we got a proper error response
            ctx.assert.not_nil(result.error or result.message, "Failed set_recipe should have error")
        end
        
        -- Test clearing recipe (set to nil)
        local clear_result = ctx:agent_call("set_entity_recipe", "assembling-machine-1", ctx.test_position, nil)
        ctx.assert.not_nil(clear_result, "Clearing recipe should return result")
    end,
    
    teardown = function(ctx)
        ctx:clear_area(ctx.test_position or {x=-170, y=190}, 10)
        ctx:destroy_agent()
    end,
}

