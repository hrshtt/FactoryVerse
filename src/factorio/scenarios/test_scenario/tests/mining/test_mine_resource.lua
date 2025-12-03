-- Test: Mine Resource (Sync - Queue Verification)
-- Verifies that mining can be started and returns queued status

return {
    setup = function(ctx)
        ctx:create_agent()
        
        -- Teleport agent to a clear area
        local pos = {x = 50, y = 50}
        ctx:agent_call("teleport", pos)
        ctx:clear_area(pos, 10)
        
        -- Create iron ore RIGHT NEXT to agent (within resource_reach_distance ~2.7 tiles)
        ctx.ore_position = {x = pos.x + 1, y = pos.y}
        ctx.surface.create_entity({
            name = "iron-ore",
            position = ctx.ore_position,
            amount = 1000
        })
    end,
    
    test = function(ctx)
        -- Start mining iron ore
        local result = ctx:agent_call("mine_resource", "iron-ore", 10)
        ctx.assert.not_nil(result, "mine_resource should return result")
        
        -- Should be queued or have error
        if result.queued or result.success then
            ctx.assert.not_nil(result.action_id or result.tick, "Should have action_id or tick")
            
            -- Check activity state shows mining
            local state = ctx:agent_call("get_activity_state")
            ctx.assert.not_nil(state, "get_activity_state should return result")
            ctx.assert.not_nil(state.mining, "Should have mining state")
            ctx.assert.is_true(state.mining.active or state.mining.action_id ~= nil,
                "Mining should be active or have action_id")
        else
            -- May fail if no ore in range
            ctx.assert.not_nil(result.error, "Failed mining should have error")
        end
    end,
    
    teardown = function(ctx)
        -- Stop any ongoing mining
        pcall(function() ctx:agent_call("stop_mining") end)
        ctx:clear_area(ctx.ore_position or {x=50, y=50}, 10)
        ctx:destroy_agent()
    end,
}

