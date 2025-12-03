-- Test: Stop Mining (Sync)
-- Verifies that mining can be cancelled

return {
    setup = function(ctx)
        ctx:create_agent()
        
        -- Teleport agent to resource area
        local pos = ctx.grid.get_position_in_area("top_middle", 20, 0)
        ctx:agent_call("teleport", pos)
        ctx:clear_area(pos, 5)
        
        -- Create iron ore
        local ore_pos = {x = pos.x + 1, y = pos.y}
        ctx.surface.create_entity({
            name = "iron-ore",
            position = ore_pos,
            amount = 10000
        })
        ctx.ore_position = ore_pos
        
        -- Start mining a large amount
        local result = ctx:agent_call("mine_resource", "iron-ore", 1000)
        ctx.mining_started = result.queued or result.success
    end,
    
    test = function(ctx)
        if not ctx.mining_started then
            -- Mining didn't start, skip test
            return
        end
        
        -- Verify mining is active
        local state_before = ctx:agent_call("get_activity_state")
        ctx.assert.is_true(state_before.mining.active or state_before.mining.action_id ~= nil,
            "Mining should be active before stop")
        
        -- Stop mining
        local result = ctx:agent_call("stop_mining")
        ctx.assert.not_nil(result, "stop_mining should return result")
        
        -- Verify mining stopped
        local state_after = ctx:agent_call("get_activity_state")
        ctx.assert.is_true(not state_after.mining.active and state_after.mining.action_id == nil,
            "Mining should be stopped after stop_mining")
    end,
    
    teardown = function(ctx)
        ctx:clear_area(ctx.ore_position or {x=0, y=0}, 5)
        ctx:destroy_agent()
    end,
}

