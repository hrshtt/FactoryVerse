local TestHelpers = require("core.test.TestHelpers")
local TestAssertions = require("core.test.TestAssertions")

return {
    name = "entity.pickup",
    
    setup = function(context)
        -- Create test surface area
        context.surface = game.surfaces[1]
        context.test_area = TestHelpers.create_test_area({x=0, y=0}, 20)
        context.agent = TestHelpers.spawn_agent(context.surface, {x=0, y=0})
        
        -- Clear agent inventory
        TestHelpers.clear_agent_inventory(context.agent)
    end,
    
    tests = {
        test_pickup_empty_entity = function(context)
            -- Create a minable entity (wooden chest)
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local unit_number = chest.unit_number
            
            -- Execute pickup action
            local result = remote.call("actions", "entity.pickup", {
                agent_id = context.agent.player_index,
                unit_number = unit_number
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.entity_name, "wooden-chest")
            TestAssertions.assert_equal(result.items_obtained["wooden-chest"], 1)
            
            -- Check agent inventory
            TestAssertions.assert_agent_has_items(context.agent, {["wooden-chest"] = 1})
            
            -- Check entity is removed
            TestAssertions.assert_entity_exists(unit_number) -- Should fail since entity is destroyed
        end,
        
        test_pickup_entity_with_contents = function(context)
            -- Create a chest with items
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2}, {
                ["iron-plate"] = 10,
                ["copper-plate"] = 5
            })
            local unit_number = chest.unit_number
            
            -- Execute pickup action
            local result = remote.call("actions", "entity.pickup", {
                agent_id = context.agent.player_index,
                unit_number = unit_number
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.entity_name, "wooden-chest")
            TestAssertions.assert_equal(result.items_obtained["wooden-chest"], 1)
            TestAssertions.assert_equal(result.items_obtained["iron-plate"], 10)
            TestAssertions.assert_equal(result.items_obtained["copper-plate"], 5)
            
            -- Check agent inventory
            TestAssertions.assert_agent_has_items(context.agent, {
                ["wooden-chest"] = 1,
                ["iron-plate"] = 10,
                ["copper-plate"] = 5
            })
        end,
        
        test_pickup_insufficient_space = function(context)
            -- Fill agent inventory to capacity
            local inventory = TestHelpers.get_agent_inventory(context.agent)
            for i = 1, inventory.size do
                inventory.insert({name = "iron-plate", count = 1})
            end
            
            -- Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local unit_number = chest.unit_number
            
            -- Try pickup - should fail
            local success, error = pcall(function()
                remote.call("actions", "entity.pickup", {
                    agent_id = context.agent.player_index,
                    unit_number = unit_number
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "insufficient space")
        end,
        
        test_pickup_non_minable_entity = function(context)
            -- Create a non-minable entity (assembler)
            local assembler = TestHelpers.spawn_entity(context.surface, "assembling-machine-1", {x=2, y=2})
            local unit_number = assembler.unit_number
            
            -- Try pickup - should fail
            local success, error = pcall(function()
                remote.call("actions", "entity.pickup", {
                    agent_id = context.agent.player_index,
                    unit_number = unit_number
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "not minable")
        end,
        
        test_pickup_entity_not_found = function(context)
            -- Try picking up non-existent entity
            local success, error = pcall(function()
                remote.call("actions", "entity.pickup", {
                    agent_id = context.agent.player_index,
                    unit_number = 99999
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "Entity not found")
        end,
        
        test_pickup_agent_not_found = function(context)
            -- Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local unit_number = chest.unit_number
            
            -- Try pickup with invalid agent
            local success, error = pcall(function()
                remote.call("actions", "entity.pickup", {
                    agent_id = 99999,
                    unit_number = unit_number
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "Agent not found")
        end,
        
        test_pickup_assembler_with_modules = function(context)
            -- Create an assembler with modules
            local assembler = TestHelpers.create_test_assembler(context.surface, {x=2, y=2})
            local unit_number = assembler.unit_number
            
            -- Add modules to assembler
            local module_inventory = assembler.get_inventory(defines.inventory.assembling_machine_modules)
            module_inventory.insert({name = "speed-module", count = 2})
            
            -- Give agent the assembler item first
            TestHelpers.give_agent_items(context.agent, {["assembling-machine-1"] = 1})
            
            -- Execute pickup action
            local result = remote.call("actions", "entity.pickup", {
                agent_id = context.agent.player_index,
                unit_number = unit_number
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.entity_name, "assembling-machine-1")
            TestAssertions.assert_equal(result.items_obtained["assembling-machine-1"], 1)
            TestAssertions.assert_equal(result.items_obtained["speed-module"], 2)
        end
    },
    
    teardown = function(context)
        -- Clean up test artifacts
        TestHelpers.clear_test_area(context.surface, context.test_area)
    end
}
