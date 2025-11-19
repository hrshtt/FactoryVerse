-- Test entity.inventory.set_limit action
local TestHelpers = require("__factorio_verse__.core.test.TestHelpers")

return {
    name = "inventory.set_limit",
    
    setup = function(context)
        context.surface = game.surfaces[1]
        
        -- Create agent via admin_api - returns table of created agents
        local agents = remote.call("helpers", "create_agent_characters", 1, true)
        if not agents or #agents == 0 then
            error("Failed to create test agent")
        end
        context.agent = agents[1]
    end,
    
    tests = {
        test_set_inventory_limit = function(context)
            -- Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local position = chest.position
            local entity_name = chest.name
            
            -- Execute set_limit action
            local result = remote.call("actions", "entity.inventory.set_limit", {
                agent_id = 1,
                position_x = position.x,
                position_y = position.y,
                entity_name = entity_name,
                inventory_type = "chest",
                limit = 5
            })
            
            if not result then
                error("set_limit returned nil")
            end
            if result.new_limit ~= 5 then
                error("Expected new_limit to be 5, got: " .. tostring(result.new_limit))
            end
        end
    },
    
    teardown = function(context)
        -- Cleanup handled by game
    end
}
