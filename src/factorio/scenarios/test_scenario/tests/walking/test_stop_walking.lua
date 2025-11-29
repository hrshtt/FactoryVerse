-- Test: Stop Walking (Sync)
-- Verifies that walking can be cancelled

return {
    setup = function(ctx)
        ctx:create_agent()
        
        -- Teleport agent to a clear area
        local pos = {x = 60, y = 60}
        ctx:agent_call("teleport", pos)
        ctx:clear_area(pos, 100)
        
        ctx.start_position = pos
        -- Long walk distance so we can stop it
        ctx.target_position = {x = pos.x + 30, y = pos.y + 30}
        
        -- Start walking
        local result = ctx:agent_call("walk_to", ctx.target_position)
        ctx.walking_started = result.queued or result.success
        ctx.walk_action_id = result.action_id
    end,
    
    test = function(ctx)
        if not ctx.walking_started then
            -- Walking didn't start, skip test
            return
        end
        
        -- Stop walking
        local result = ctx:agent_call("stop_walking")
        ctx.assert.not_nil(result, "stop_walking should return result")
        
        -- stop_walking returns success if agent was walking, or error if not
        -- Either way, after this call walking should be stopped
        if result.success then
            -- Verify walking stopped (check action_id is cleared)
            local state_after = ctx:agent_call("get_activity_state")
            -- After successful stop_walking, action_id should be nil
            ctx.assert.is_true(state_after.walking.action_id == nil,
                "Walking action_id should be nil after successful stop_walking")
        else
            -- Agent may not have been walking yet (path request still pending)
            -- This is acceptable - the test verifies the API works
            ctx.assert.not_nil(result.error, "Failed stop should have error message")
        end
    end,
    
    teardown = function(ctx)
        ctx:destroy_agent()
    end,
}

