local TestHelpers = require("core.test.TestHelpers")
local TestAssertions = require("core.test.TestAssertions")

return {
    name = "inventory.set_limit",
    
    setup = function(context)
        -- Create test surface area
        context.surface = game.surfaces[1]
        context.test_area = TestHelpers.create_test_area({x=0, y=0}, 20)
        context.agent = TestHelpers.spawn_agent(context.surface, {x=0, y=0})
    end,
    
    tests = {
        test_set_inventory_limit = function(context)
            -- Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local unit_number = chest.unit_number
            
            -- Execute set_limit action
            local result = remote.call("actions", "entity.inventory.set_limit", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                inventory_type = "chest",
                limit = 5
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.inventory_type, "chest")
            TestAssertions.assert_equal(result.new_limit, 5)
            TestAssertions.assert_equal(result.action, "set")
            
            -- Check limit is actually set
            local inventory = chest.get_inventory(defines.inventory.chest)
            TestAssertions.assert_equal(inventory.get_bar(), 5)
        end,
        
        test_bar_support_validation = function(context)
            -- Create an entity without bar support (inserter)
            local inserter = TestHelpers.spawn_entity(context.surface, "inserter", {x=2, y=2})
            local unit_number = inserter.unit_number
            
            -- Try setting limit
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.set_limit", {
                    agent_id = context.agent.player_index,
                    unit_number = unit_number,
                    inventory_type = "chest",
                    limit = 5
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "does not support setting limits")
        end,
        
        test_limit_range_validation = function(context)
            -- Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local unit_number = chest.unit_number
            
            -- Try setting negative limit
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.set_limit", {
                    agent_id = context.agent.player_index,
                    unit_number = unit_number,
                    inventory_type = "chest",
                    limit = -1
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "must be between 0 and")
        end,
        
        test_limit_exceeds_inventory_size = function(context)
            -- Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local unit_number = chest.unit_number
            
            local inventory = chest.get_inventory(defines.inventory.chest)
            local max_size = inventory.get_bar() or inventory.size
            
            -- Try setting limit higher than inventory size
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.set_limit", {
                    agent_id = context.agent.player_index,
                    unit_number = unit_number,
                    inventory_type = "chest",
                    limit = max_size + 10
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "must be between 0 and")
        end,
        
        test_no_op_when_limit_already_set = function(context)
            -- Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local unit_number = chest.unit_number
            
            -- Set initial limit
            local inventory = chest.get_inventory(defines.inventory.chest)
            inventory.set_bar(5)
            
            -- Try setting same limit
            local result = remote.call("actions", "entity.inventory.set_limit", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                inventory_type = "chest",
                limit = 5
            })
            
            -- Should be no-op
            TestAssertions.assert_equal(result.action, "no_op")
            TestAssertions.assert_contains(result.message, "already has this limit")
        end,
        
        test_set_limit_to_zero = function(context)
            -- Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local unit_number = chest.unit_number
            
            -- Set limit to 0 (unlimited)
            local result = remote.call("actions", "entity.inventory.set_limit", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                inventory_type = "chest",
                limit = 0
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.new_limit, 0)
            TestAssertions.assert_equal(result.action, "set")
            
            -- Check limit is actually set
            local inventory = chest.get_inventory(defines.inventory.chest)
            TestAssertions.assert_equal(inventory.get_bar(), 0)
        end,
        
        test_invalid_inventory_type = function(context)
            -- Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local unit_number = chest.unit_number
            
            -- Try with invalid inventory_type
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.set_limit", {
                    agent_id = context.agent.player_index,
                    unit_number = unit_number,
                    inventory_type = "invalid_type",
                    limit = 5
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "Invalid inventory_type")
        end,
        
        test_entity_no_inventory = function(context)
            -- Create an entity without the specified inventory
            local inserter = TestHelpers.spawn_entity(context.surface, "inserter", {x=2, y=2})
            local unit_number = inserter.unit_number
            
            -- Try setting limit on non-existent inventory
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.set_limit", {
                    agent_id = context.agent.player_index,
                    unit_number = unit_number,
                    inventory_type = "chest",
                    limit = 5
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "does not have inventory type")
        end,
        
        test_entity_not_found = function(context)
            -- Try setting limit on non-existent entity
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.set_limit", {
                    agent_id = context.agent.player_index,
                    unit_number = 99999,
                    inventory_type = "chest",
                    limit = 5
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "Entity not found")
        end,
        
        test_assembler_input_limit = function(context)
            -- Create an assembler
            local assembler = TestHelpers.create_test_assembler(context.surface, {x=2, y=2})
            local unit_number = assembler.unit_number
            
            -- Set limit on input inventory
            local result = remote.call("actions", "entity.inventory.set_limit", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                inventory_type = "input",
                limit = 3
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.inventory_type, "input")
            TestAssertions.assert_equal(result.new_limit, 3)
            TestAssertions.assert_equal(result.action, "set")
            
            -- Check limit is actually set
            local inventory = assembler.get_inventory(defines.inventory.assembling_machine_input)
            TestAssertions.assert_equal(inventory.get_bar(), 3)
        end,
        
        test_assembler_output_limit = function(context)
            -- Create an assembler
            local assembler = TestHelpers.create_test_assembler(context.surface, {x=2, y=2})
            local unit_number = assembler.unit_number
            
            -- Set limit on output inventory
            local result = remote.call("actions", "entity.inventory.set_limit", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                inventory_type = "output",
                limit = 2
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.inventory_type, "output")
            TestAssertions.assert_equal(result.new_limit, 2)
            TestAssertions.assert_equal(result.action, "set")
            
            -- Check limit is actually set
            local inventory = assembler.get_inventory(defines.inventory.assembling_machine_output)
            TestAssertions.assert_equal(inventory.get_bar(), 2)
        end,
        
        test_non_integer_limit = function(context)
            -- Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local unit_number = chest.unit_number
            
            -- Try setting non-integer limit
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.set_limit", {
                    agent_id = context.agent.player_index,
                    unit_number = unit_number,
                    inventory_type = "chest",
                    limit = 5.5
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "must be an integer")
        end
    },
    
    teardown = function(context)
        -- Clean up test artifacts
        TestHelpers.clear_test_area(context.surface, context.test_area)
    end
}
