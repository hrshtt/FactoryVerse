-- Test entity.inventory.set_item action
local TestHelpers = require("__factorio_verse__.core.test.TestHelpers")

return {
    name = "inventory.set_item",
    
    setup = function(context)
        context.surface = game.surfaces[1]
        
        -- Create agent via admin_api - returns table of created agents
        local agents = remote.call("helpers", "create_agent_characters", 1, true)
        if not agents or #agents == 0 then
            error("Failed to create test agent")
        end
        context.agent = agents[1]
        
        -- Clear agent inventory and give test items
        TestHelpers.clear_agent_inventory(context.agent)
        TestHelpers.give_agent_items(context.agent, {
            ["iron-plate"] = 50,
            ["copper-plate"] = 30
        })
    end,
    
    tests = {
        test_insert_items_into_chest = function(context)
            -- Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local position = chest.position
            local entity_name = chest.name
            
            -- Execute set_item action
            local result = remote.call("actions", "entity.inventory.set_item", {
                agent_id = 1,
                position_x = position.x,
                position_y = position.y,
                entity_name = entity_name,
                item = "iron-plate",
                count = 10,
                inventory_type = "chest"
            })
            
            if not result then
                error("set_item returned nil")
            end
            if result.inserted ~= 10 then
                error("Expected 10 items inserted, got: " .. tostring(result.inserted))
            end
        end,
        
        test_entity_not_found = function(context)
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.set_item", {
                    agent_id = 1,
                    position_x = 99999,
                    position_y = 99999,
                    entity_name = "wooden-chest",
                    item = "iron-plate",
                    count = 10,
                    inventory_type = "chest"
                })
            end)
            
            if success then
                error("Expected set_item to fail for non-existent entity")
            end
        end
    },
    
    teardown = function(context)
        -- Cleanup handled by game
    end
}
