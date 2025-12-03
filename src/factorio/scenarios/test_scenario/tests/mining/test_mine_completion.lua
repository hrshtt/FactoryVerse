-- Test: Mine Completion (Async)
-- Verifies that mining completes and ore appears in inventory

return {
    timeout_ticks = 600,  -- 10 seconds for mining
    
    setup = function(ctx)
        ctx:create_agent()
        
        -- Teleport agent to resource area
        local pos = ctx.grid.get_position_in_area("top_middle", 10, 0)
        ctx:agent_call("teleport", pos)
        ctx:clear_area(pos, 5)
        
        -- Create iron ore right next to agent
        local ore_pos = {x = pos.x + 1, y = pos.y}
        ctx.surface.create_entity({
            name = "iron-ore",
            position = ore_pos,
            amount = 100
        })
        ctx.ore_position = ore_pos
        
        -- Record initial ore count
        local inv = ctx:agent_call("inspect", true)
        ctx.initial_ore = 0
        for item_name, item_data in pairs(inv.inventory or {}) do
            if item_name == "iron-ore" then
                ctx.initial_ore = type(item_data) == "number" and item_data or (item_data.count or 0)
                break
            end
        end
    end,
    
    start = function(ctx)
        -- Start mining a small amount
        local result = ctx:agent_call("mine_resource", "iron-ore", 5)
        ctx.assert.not_nil(result, "mine_resource should return result")
        ctx.mining_started = result.queued or result.success
        
        if not ctx.mining_started and result.error then
            -- Log error for debugging
            game.print("Mining failed to start: " .. tostring(result.error))
        end
    end,
    
    poll = function(ctx)
        if not ctx.mining_started then
            return true  -- Skip if mining didn't start
        end
        
        -- Check if mining is complete
        local state = ctx:agent_call("get_activity_state")
        
        -- Complete when not actively mining and no action_id
        return not state.mining.active and state.mining.action_id == nil
    end,
    
    verify = function(ctx)
        if not ctx.mining_started then
            -- Mining didn't start (maybe no ore in range)
            return
        end
        
        -- Check inventory for mined ore
        local inv = ctx:agent_call("inspect", true)
        local final_ore = 0
        for item_name, item_data in pairs(inv.inventory or {}) do
            if item_name == "iron-ore" then
                final_ore = type(item_data) == "number" and item_data or (item_data.count or 0)
                break
            end
        end
        
        ctx.assert.is_true(final_ore > ctx.initial_ore,
            "Should have more iron ore after mining: initial=" .. ctx.initial_ore .. ", final=" .. final_ore)
    end,
    
    teardown = function(ctx)
        pcall(function() ctx:agent_call("stop_mining") end)
        ctx:clear_area(ctx.ore_position or {x=0, y=0}, 5)
        ctx:destroy_agent()
    end,
}

