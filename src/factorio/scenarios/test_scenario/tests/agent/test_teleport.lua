-- Test: Agent Teleport
-- Verifies that agents can be teleported and position is updated

return {
    setup = function(ctx)
        ctx:create_agent()
    end,
    
    test = function(ctx)
        -- Get initial position
        local initial = ctx:agent_call("inspect")
        ctx.assert.not_nil(initial.position, "Agent should have initial position")
        
        -- Teleport to new position
        local target = {x = 50, y = 50}
        local result = ctx:agent_call("teleport", target)
        ctx.assert.is_true(result, "teleport should return true")
        
        -- Verify new position
        local after = ctx:agent_call("inspect")
        ctx.assert.not_nil(after.position, "Agent should have position after teleport")
        
        -- Allow small floating point tolerance
        local dx = math.abs(after.position.x - target.x)
        local dy = math.abs(after.position.y - target.y)
        ctx.assert.is_true(dx < 1, "X position should be close to target")
        ctx.assert.is_true(dy < 1, "Y position should be close to target")
    end,
    
    teardown = function(ctx)
        ctx:destroy_agent()
    end,
}

