-- Test: Agent Inspect
-- Verifies that inspect returns expected structure with optional attachments

return {
    setup = function(ctx)
        ctx:create_agent()
    end,
    
    test = function(ctx)
        -- Basic inspect (no attachments)
        local basic = ctx:agent_call("inspect")
        ctx.assert.not_nil(basic, "inspect should return result")
        ctx.assert.equals(ctx.agent_id, basic.agent_id, "Should have correct agent_id")
        ctx.assert.not_nil(basic.tick, "Should have tick")
        ctx.assert.not_nil(basic.position, "Should have position")
        ctx.assert.not_nil(basic.position.x, "Position should have x")
        ctx.assert.not_nil(basic.position.y, "Position should have y")
        
        -- Inspect with inventory
        local with_inv = ctx:agent_call("inspect", true, false)
        ctx.assert.not_nil(with_inv.inventory, "Should have inventory when requested")
        ctx.assert.is_true(type(with_inv.inventory) == "table", "Inventory should be a table")
        
        -- Inspect with reachable entities
        local with_entities = ctx:agent_call("inspect", false, true)
        ctx.assert.not_nil(with_entities.reachable_resources, "Should have reachable_resources when requested")
        ctx.assert.not_nil(with_entities.reachable_entities, "Should have reachable_entities when requested")
        ctx.assert.is_true(type(with_entities.reachable_resources) == "table", "reachable_resources should be a table")
        ctx.assert.is_true(type(with_entities.reachable_entities) == "table", "reachable_entities should be a table")
        
        -- Inspect with both
        local with_both = ctx:agent_call("inspect", true, true)
        ctx.assert.not_nil(with_both.inventory, "Should have inventory")
        ctx.assert.not_nil(with_both.reachable_resources, "Should have reachable_resources")
        ctx.assert.not_nil(with_both.reachable_entities, "Should have reachable_entities")
    end,
    
    teardown = function(ctx)
        ctx:destroy_agent()
    end,
}

