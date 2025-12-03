-- Test: Walk To (Sync - Queue Verification)
-- Verifies that walking can be started and returns queued status

return {
    setup = function(ctx)
        ctx:create_agent()
        
        -- Teleport agent to movement test area
        local pos = ctx.grid.get_position_in_area("middle_middle", 0, 0)
        ctx:agent_call("teleport", pos)
        ctx:clear_area(pos, 20)
        
        ctx.start_position = pos
        ctx.target_position = {x = pos.x + 10, y = pos.y + 10}
    end,
    
    test = function(ctx)
        -- Start walking to target
        local result = ctx:agent_call("walk_to", ctx.target_position)
        ctx.assert.not_nil(result, "walk_to should return result")
        
        -- Should be queued or have error
        if result.queued or result.success then
            ctx.assert.not_nil(result.action_id or result.tick, "Should have action_id or tick")
            
            -- Check activity state shows walking
            local state = ctx:agent_call("get_activity_state")
            ctx.assert.not_nil(state, "get_activity_state should return result")
            ctx.assert.not_nil(state.walking, "Should have walking state")
            -- Walking should be active (has path or waiting for path)
            ctx.assert.is_true(state.walking.active or state.walking.path_id ~= nil or state.walking.action_id ~= nil,
                "Walking should be active or have path_id/action_id")
        else
            -- May fail if path not possible
            ctx.assert.not_nil(result.error, "Failed walk should have error")
        end
    end,
    
    teardown = function(ctx)
        -- Stop any ongoing walking
        pcall(function() ctx:agent_call("stop_walking") end)
        ctx:destroy_agent()
    end,
}

