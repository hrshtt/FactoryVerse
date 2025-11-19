-- Integration test - Full workflow
local TestHelpers = require("__factorio_verse__.core.test.TestHelpers")

return {
    name = "integration.full_workflow",
    
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
        test_create_and_place_entity = function(context)
            -- Step 1: Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2}, {
                ["iron-plate"] = 10
            })
            
            if not chest or not chest.valid then
                error("Failed to create test chest")
            end
            
            -- Step 2: Get items from chest
            local result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = 1,
                position_x = chest.position.x,
                position_y = chest.position.y,
                entity_name = chest.name,
                item = "iron-plate",
                count = 5,
                inventory_type = "chest"
            })
            
            if not result then
                error("get_item returned nil")
            end
            if result.total_transferred ~= 5 then
                error("Expected 5 items transferred, got: " .. tostring(result.total_transferred))
            end
            
            -- Verify agent has the items
            local inventory = TestHelpers.get_agent_inventory(context.agent)
            if inventory.get_item_count("iron-plate") ~= 5 then
                error("Agent should have 5 iron-plates")
            end
        end
    },
    
    teardown = function(context)
        -- Cleanup handled by game
    end
}
