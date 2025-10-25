local TestHelpers = require("core.test.TestHelpers")
local TestAssertions = require("core.test.TestAssertions")

return {
    name = "inventory.get_item",
    
    setup = function(context)
        -- Create test surface area
        context.surface = game.surfaces[1]
        context.test_area = TestHelpers.create_test_area({x=0, y=0}, 20)
        context.agent = TestHelpers.spawn_agent(context.surface, {x=0, y=0})
        
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
            local unit_number = chest.unit_number
            
            -- Execute get_item action
            local result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                item = "iron-plate",
                count = 10,
                inventory_type = "chest"
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.item, "iron-plate")
            TestAssertions.assert_equal(result.total_transferred, 10)
            TestAssertions.assert_equal(result.inventory_type, "chest")
            
            -- Check transfer results
            TestAssertions.assert_not_nil(result.transfer_results["iron-plate"])
            TestAssertions.assert_equal(result.transfer_results["iron-plate"].transferred, 10)
            TestAssertions.assert_equal(result.transfer_results["iron-plate"].reason, "complete")
            
            -- Check agent inventory
            TestAssertions.assert_agent_has_items(context.agent, {["iron-plate"] = 10})
            
            -- Check chest inventory reduced
            TestAssertions.assert_inventory_contains(chest, defines.inventory.chest, "iron-plate", 10)
        end,
        
        test_batch_extraction = function(context)
            -- Create a chest with items
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2}, {
                ["iron-plate"] = 20,
                ["copper-plate"] = 15,
                ["steel-plate"] = 5
            })
            local unit_number = chest.unit_number
            
            -- Execute batch get_item action
            local result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                item = {
                    ["iron-plate"] = 10,
                    ["copper-plate"] = 8,
                    ["steel-plate"] = 3
                },
                inventory_type = "chest"
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.total_transferred, 21)
            
            -- Check transfer results for each item
            TestAssertions.assert_equal(result.transfer_results["iron-plate"].transferred, 10)
            TestAssertions.assert_equal(result.transfer_results["copper-plate"].transferred, 8)
            TestAssertions.assert_equal(result.transfer_results["steel-plate"].transferred, 3)
            
            -- Check agent inventory
            TestAssertions.assert_agent_has_items(context.agent, {
                ["iron-plate"] = 10,
                ["copper-plate"] = 8,
                ["steel-plate"] = 3
            })
        end,
        
        test_all_items_keyword = function(context)
            -- Create a chest with items
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2}, {
                ["iron-plate"] = 20,
                ["copper-plate"] = 15,
                ["steel-plate"] = 5
            })
            local unit_number = chest.unit_number
            
            -- Execute ALL_ITEMS action
            local result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                item = "ALL_ITEMS",
                inventory_type = "chest"
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.item, "ALL_ITEMS")
            TestAssertions.assert_equal(result.total_transferred, 40)
            
            -- Check all items were transferred
            TestAssertions.assert_equal(result.transfer_results["iron-plate"].transferred, 20)
            TestAssertions.assert_equal(result.transfer_results["copper-plate"].transferred, 15)
            TestAssertions.assert_equal(result.transfer_results["steel-plate"].transferred, 5)
            
            -- Check agent inventory
            TestAssertions.assert_agent_has_items(context.agent, {
                ["iron-plate"] = 20,
                ["copper-plate"] = 15,
                ["steel-plate"] = 5
            })
            
            -- Check chest is empty
            local chest_inventory = chest.get_inventory(defines.inventory.chest)
            TestAssertions.assert_equal(chest_inventory.get_item_count("iron-plate"), 0)
            TestAssertions.assert_equal(chest_inventory.get_item_count("copper-plate"), 0)
            TestAssertions.assert_equal(chest_inventory.get_item_count("steel-plate"), 0)
        end,
        
        test_partial_transfer_agent_full = function(context)
            -- Fill agent inventory to capacity
            local agent_inventory = TestHelpers.get_agent_inventory(context.agent)
            for i = 1, agent_inventory.size do
                agent_inventory.insert({name = "iron-plate", count = 1})
            end
            
            -- Create a chest with items
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2}, {
                ["copper-plate"] = 20
            })
            local unit_number = chest.unit_number
            
            -- Try getting items
            local result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                item = "copper-plate",
                count = 10,
                inventory_type = "chest"
            })
            
            -- Should handle gracefully with partial transfer
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.transfer_results["copper-plate"].reason, "agent_inventory_full")
            TestAssertions.assert_equal(result.transfer_results["copper-plate"].transferred, 0)
        end,
        
        test_empty_inventory = function(context)
            -- Create an empty chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local unit_number = chest.unit_number
            
            -- Try getting items from empty inventory
            local result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                item = "iron-plate",
                count = 10,
                inventory_type = "chest"
            })
            
            -- Should handle gracefully
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.transfer_results["iron-plate"].reason, "not_available")
            TestAssertions.assert_equal(result.transfer_results["iron-plate"].transferred, 0)
        end,
        
        test_item_not_found = function(context)
            -- Create a chest with different items
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2}, {
                ["copper-plate"] = 20
            })
            local unit_number = chest.unit_number
            
            -- Try getting item that doesn't exist
            local result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                item = "iron-plate",
                count = 10,
                inventory_type = "chest"
            })
            
            -- Should handle gracefully
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.transfer_results["iron-plate"].reason, "not_available")
            TestAssertions.assert_equal(result.transfer_results["iron-plate"].transferred, 0)
        end,
        
        test_insufficient_items = function(context)
            -- Create a chest with limited items
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2}, {
                ["iron-plate"] = 5
            })
            local unit_number = chest.unit_number
            
            -- Try getting more items than available
            local result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                item = "iron-plate",
                count = 10,
                inventory_type = "chest"
            })
            
            -- Should transfer what's available
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.transfer_results["iron-plate"].transferred, 5)
            TestAssertions.assert_equal(result.transfer_results["iron-plate"].reason, "partial")
            
            -- Check agent got the available amount
            TestAssertions.assert_agent_has_items(context.agent, {["iron-plate"] = 5})
        end,
        
        test_auto_resolve_inventory_type = function(context)
            -- Create a chest (only has one inventory type)
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2}, {
                ["iron-plate"] = 20
            })
            local unit_number = chest.unit_number
            
            -- Get items without specifying inventory_type
            local result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                item = "iron-plate",
                count = 10
            })
            
            -- Should auto-resolve to chest inventory
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.inventory_type, "chest")
            TestAssertions.assert_equal(result.transfer_results["iron-plate"].transferred, 10)
        end,
        
        test_entity_not_found = function(context)
            -- Try getting items from non-existent entity
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.get_item", {
                    agent_id = context.agent.player_index,
                    unit_number = 99999,
                    item = "iron-plate",
                    count = 10,
                    inventory_type = "chest"
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "Entity not found")
        end,
        
        test_agent_not_found = function(context)
            -- Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2}, {
                ["iron-plate"] = 20
            })
            local unit_number = chest.unit_number
            
            -- Try with invalid agent
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.get_item", {
                    agent_id = 99999,
                    unit_number = unit_number,
                    item = "iron-plate",
                    count = 10,
                    inventory_type = "chest"
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "Agent not found")
        end,
        
        test_default_count = function(context)
            -- Create a chest with items
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2}, {
                ["iron-plate"] = 20
            })
            local unit_number = chest.unit_number
            
            -- Get items without specifying count (should default to 1)
            local result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                item = "iron-plate",
                inventory_type = "chest"
            })
            
            -- Should get 1 item
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.transfer_results["iron-plate"].transferred, 1)
            TestAssertions.assert_agent_has_items(context.agent, {["iron-plate"] = 1})
        end
    },
    
    teardown = function(context)
        -- Clean up test artifacts
        TestHelpers.clear_test_area(context.surface, context.test_area)
    end
}
