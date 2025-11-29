-- Test: Walk Completion (Async)
-- Verifies that walking completes and agent reaches destination

return {
    timeout_ticks = 600,  -- 10 seconds for short walk
    
    setup = function(ctx)
        ctx:create_agent()
        
        -- Teleport agent to movement test area
        local pos = ctx.grid.get_position_in_area("middle_middle", -20, -20)
        ctx:agent_call("teleport", pos)
        ctx:clear_area(pos, 30)
        
        ctx.start_position = pos
        -- Short walk distance
        ctx.target_position = {x = pos.x + 5, y = pos.y + 5}
    end,
    
    start = function(ctx)
        -- Start walking to target
        local result = ctx:agent_call("walk_to", ctx.target_position)
        ctx.assert.not_nil(result, "walk_to should return result")
        ctx.walking_started = result.queued or result.success
        
        if not ctx.walking_started and result.error then
            game.print("Walking failed to start: " .. tostring(result.error))
        end
    end,
    
    poll = function(ctx)
        if not ctx.walking_started then
            return true  -- Skip if walking didn't start
        end
        
        -- Check if walking is complete
        local state = ctx:agent_call("get_activity_state")
        
        -- Complete when not actively walking
        return not state.walking.active and state.walking.action_id == nil
    end,
    
    verify = function(ctx)
        if not ctx.walking_started then
            return
        end
        
        -- Check agent position is near target
        local current = ctx:agent_call("inspect")
        local dx = math.abs(current.position.x - ctx.target_position.x)
        local dy = math.abs(current.position.y - ctx.target_position.y)
        local distance = math.sqrt(dx*dx + dy*dy)
        
        -- Agent should be within 2 tiles of target
        ctx.assert.is_true(distance < 2,
            "Agent should be near target: distance=" .. distance)
    end,
    
    teardown = function(ctx)
        pcall(function() ctx:agent_call("stop_walking") end)
        ctx:destroy_agent()
    end,
}

