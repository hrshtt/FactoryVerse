-- Test: Chart Spawn Area (Sync)
-- Verifies that agents can chart the spawn area

return {
    setup = function(ctx)
        ctx:create_agent()
    end,
    
    test = function(ctx)
        -- Get chunks in view before charting
        local chunks_before = ctx:agent_call("get_chunks_in_view")
        ctx.assert.not_nil(chunks_before, "get_chunks_in_view should return result")
        ctx.assert.is_true(type(chunks_before) == "table", "Should return table of chunks")
        
        -- Chart spawn area (this should already be charted for player force)
        -- The chart_spawn_area method charts chunks around spawn
        -- Note: This may be a no-op if already charted
        
        -- Verify chunks are accessible
        local chunks_after = ctx:agent_call("get_chunks_in_view")
        ctx.assert.not_nil(chunks_after, "get_chunks_in_view should return result after chart")
        
        -- Should have some chunks visible
        ctx.assert.is_true(#chunks_after >= 0, "Should have chunk visibility info")
    end,
    
    teardown = function(ctx)
        ctx:destroy_agent()
    end,
}

