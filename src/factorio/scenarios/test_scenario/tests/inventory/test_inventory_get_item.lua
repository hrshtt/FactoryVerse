-- Test entity.inventory.get_item action
local TestHelpers = require("__factorio_verse__.core.test.TestHelpers")

return {
    name = "inventory.get_item",
    
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
        test_single_item_extraction = function(context)
            -- Create a chest with items
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2}, {
                ["iron-plate"] = 20,
                ["copper-plate"] = 15
            })
            local position = chest.position
            local entity_name = chest.name
            
            -- Execute get_item action
            local result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = 1,
                position_x = position.x,
                position_y = position.y,
                entity_name = entity_name,
                item = "iron-plate",
                count = 10,
                inventory_type = "chest"
            })
            
            if not result then
                error("get_item returned nil")
            end
            if result.item ~= "iron-plate" then
                error("Expected item to be iron-plate")
            end
            if result.total_transferred ~= 10 then
                error("Expected 10 items transferred, got: " .. tostring(result.total_transferred))
            end
        end,
        
        test_all_items_keyword = function(context)
            TestHelpers.clear_agent_inventory(context.agent)
            
            -- Create a chest with items
            local chest = TestHelpers.create_test_chest(context.surface, {x=3, y=3}, {
                ["iron-plate"] = 20,
                ["copper-plate"] = 15,
                ["steel-plate"] = 5
            })
            local position = chest.position
            local entity_name = chest.name
            
            -- Execute ALL_ITEMS action
            local result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = 1,
                position_x = position.x,
                position_y = position.y,
                entity_name = entity_name,
                item = "ALL_ITEMS",
                inventory_type = "chest"
            })
            
            if not result then
                error("get_item returned nil")
            end
            if result.total_transferred ~= 40 then
                error("Expected 40 total items, got: " .. tostring(result.total_transferred))
            end
        end,
        
        test_entity_not_found = function(context)
            -- Try getting items from non-existent entity
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.get_item", {
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
                error("Expected get_item to fail for non-existent entity")
            end
        end
    },
    
    teardown = function(context)
        -- Cleanup handled by game
    end
}
