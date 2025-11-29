-- Test: Agent Destruction
-- Verifies that agents can be destroyed and their interfaces are removed

return {
    setup = function(ctx)
        -- Create an agent to destroy
        local result = remote.call("agent", "create_agents", 1, true)
        ctx.assert.not_nil(result, "Should create agent")
        ctx.agent_id = 1
    end,
    
    test = function(ctx)
        -- Verify agent exists before destruction
        ctx.assert.is_true(remote.interfaces["agent_1"] ~= nil, "agent_1 interface should exist before destroy")
        
        -- Destroy agent
        local result = remote.call("agent", "destroy_agents", {1}, false)
        ctx.assert.not_nil(result, "destroy_agents should return result")
        ctx.assert.equals(1, #result.destroyed, "Should destroy 1 agent")
        ctx.assert.equals(1, result.destroyed[1], "Destroyed agent should be ID 1")
        
        -- Verify agent interface is removed
        ctx.assert.is_true(remote.interfaces["agent_1"] == nil, "agent_1 interface should be removed after destroy")
        
        ctx.agent_id = nil  -- Already destroyed
    end,
    
    teardown = function(ctx)
        -- Nothing to clean up
    end,
}

