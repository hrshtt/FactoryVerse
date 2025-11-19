-- Test entity.pickup action
local TestHelpers = require("__factorio_verse__.core.test.TestHelpers")

return {
    name = "entity.pickup",
    
    setup = function(context)
        context.surface = game.surfaces[1]
        
        -- Create agent via admin_api - returns table of created agents
        local agents = remote.call("helpers", "create_agent_characters", 1, true)
        if not agents or #agents == 0 then
            error("Failed to create test agent")
        end
        context.agent = agents[1]
        
        -- Clear agent inventory
        TestHelpers.clear_agent_inventory(context.agent)
    end,
    
    tests = {
        test_pickup_empty_entity = function(context)
            -- Create a minable entity (wooden chest)
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local position = chest.position
            local entity_name = chest.name
            
            -- Execute pickup action
            local result = remote.call("actions", "entity.pickup", {
                agent_id = 1,
                position_x = position.x,
                position_y = position.y,
                entity_name = entity_name
            })
            
            if not result then
                error("Pickup returned nil")
            end
            if result.entity_name ~= "wooden-chest" then
                error("Expected entity_name to be wooden-chest, got: " .. tostring(result.entity_name))
            end
        end,
        
        test_pickup_entity_with_contents = function(context)
            -- Clear agent inventory first
            TestHelpers.clear_agent_inventory(context.agent)
            
            -- Create a chest with items
            local chest = TestHelpers.create_test_chest(context.surface, {x=3, y=3}, {
                ["iron-plate"] = 10,
                ["copper-plate"] = 5
            })
            local position = chest.position
            local entity_name = chest.name
            
            -- Execute pickup action
            local result = remote.call("actions", "entity.pickup", {
                agent_id = 1,
                position_x = position.x,
                position_y = position.y,
                entity_name = entity_name
            })
            
            if not result then
                error("Pickup returned nil")
            end
            if result.entity_name ~= "wooden-chest" then
                error("Expected wooden-chest, got: " .. tostring(result.entity_name))
            end
        end
    },
    
    teardown = function(context)
        -- Cleanup handled by game
    end
}
