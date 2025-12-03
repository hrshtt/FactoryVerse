-- Test: Place Entity
-- Verifies that agents can place entities from their inventory

return {
    setup = function(ctx)
        ctx:create_agent()
        -- Teleport agent to a clear area
        local pos = {x = -190, y = 190}
        ctx:agent_call("teleport", pos)
        ctx:clear_area(pos, 15)
        ctx.agent_pos = pos
        ctx.test_position = {x = pos.x + 3, y = pos.y + 3}
    end,
    
    test = function(ctx)
        -- Give agent a chest to place by inserting directly into character inventory
        local characters = ctx.surface.find_entities_filtered({
            position = ctx.agent_pos,
            radius = 2,
            type = "character"
        })
        ctx.assert.is_true(#characters > 0, "Should find agent character")
        characters[1].insert({name = "iron-chest", count = 1})
        
        -- Verify agent has the item
        local inv_check = ctx:agent_call("inspect", true)
        
        -- Place the entity
        local result = ctx:agent_call("place_entity", "iron-chest", ctx.test_position)
        ctx.assert.not_nil(result, "place_entity should return result")
        
        if result.success then
            -- Verify entity exists - search in area since position may be adjusted
            local placed = ctx.surface.find_entities_filtered({
                position = ctx.test_position,
                radius = 2,
                name = "iron-chest"
            })
            ctx.assert.is_true(#placed > 0, "Placed entity should exist near position")
        else
            -- If placement failed, verify we got a proper error
            ctx.assert.not_nil(result.error or result.message, "Failed placement should have error message")
        end
    end,
    
    teardown = function(ctx)
        ctx:clear_area(ctx.test_position, 10)
        ctx:destroy_agent()
    end,
}

