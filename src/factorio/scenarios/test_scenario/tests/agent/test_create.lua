-- Test: Agent Creation
-- Verifies that agents can be created via remote.call and have expected state

return {
    setup = function(ctx)
        -- Ensure no existing agents
        pcall(function()
            remote.call("agent", "destroy_agents", {1, 2, 3}, false)
        end)
    end,
    
    test = function(ctx)
        -- Create agent via remote interface
        local result = remote.call("agent", "create_agents", 1, true)
        
        ctx.assert.not_nil(result, "create_agents should return result")
        ctx.assert.is_true(#result >= 1, "Should create at least one agent")
        ctx.assert.equals(1, result[1].agent_id, "Agent ID should be 1")
        
        -- Verify agent interface exists
        local interfaces = remote.interfaces
        ctx.assert.is_true(interfaces["agent_1"] ~= nil, "agent_1 interface should exist")
        
        -- Verify agent can be inspected
        local inspect_result = remote.call("agent_1", "inspect")
        ctx.assert.not_nil(inspect_result, "inspect should return result")
        ctx.assert.equals(1, inspect_result.agent_id, "Inspected agent_id should be 1")
        ctx.assert.not_nil(inspect_result.position, "Agent should have position")
        ctx.assert.not_nil(inspect_result.position.x, "Position should have x")
        ctx.assert.not_nil(inspect_result.position.y, "Position should have y")
        
        ctx.agent_id = 1
    end,
    
    teardown = function(ctx)
        ctx:destroy_agent()
    end,
}

