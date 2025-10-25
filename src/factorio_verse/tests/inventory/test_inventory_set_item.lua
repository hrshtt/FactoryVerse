local TestHelpers = require("core.test.TestHelpers")
local TestAssertions = require("core.test.TestAssertions")

return {
    name = "inventory.set_item",
    
    setup = function(context)
        -- Create test surface area
        context.surface = game.surfaces[1]
        context.test_area = TestHelpers.create_test_area({x=0, y=0}, 20)
        context.agent = TestHelpers.spawn_agent(context.surface, {x=0, y=0})
        
        -- Clear agent inventory and give test items
        TestHelpers.clear_agent_inventory(context.agent)
        TestHelpers.give_agent_items(context.agent, {
            ["iron-plate"] = 50,
            ["copper-plate"] = 30,
            ["speed-module"] = 5,
            ["coal"] = 20
        })
    end,
    
    tests = {
        test_insert_items_into_chest = function(context)
            -- Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local unit_number = chest.unit_number
            
            -- Execute set_item action
            local result = remote.call("actions", "entity.inventory.set_item", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                item = "iron-plate",
                count = 10,
                inventory_type = "chest"
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.item, "iron-plate")
            TestAssertions.assert_equal(result.count, 10)
            TestAssertions.assert_equal(result.inserted, 10)
            TestAssertions.assert_equal(result.inventory_type, "chest")
            
            -- Check chest inventory
            TestAssertions.assert_inventory_contains(chest, defines.inventory.chest, "iron-plate", 10)
            
            -- Check agent inventory reduced
            local agent_inventory = TestHelpers.get_agent_inventory(context.agent)
            TestAssertions.assert_equal(agent_inventory.get_item_count("iron-plate"), 40)
        end,
        
        test_module_insertion_explicit_type = function(context)
            -- Create an assembler
            local assembler = TestHelpers.create_test_assembler(context.surface, {x=2, y=2})
            local unit_number = assembler.unit_number
            
            -- Insert module with explicit inventory_type
            local result = remote.call("actions", "entity.inventory.set_item", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                item = "speed-module",
                count = 2,
                inventory_type = "modules"
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.item, "speed-module")
            TestAssertions.assert_equal(result.inserted, 2)
            TestAssertions.assert_equal(result.inventory_type, "modules")
            
            -- Check module inventory
            TestAssertions.assert_inventory_contains(assembler, defines.inventory.assembling_machine_modules, "speed-module", 2)
        end,
        
        test_fuel_insertion_auto_resolution = function(context)
            -- Create a furnace
            local furnace = TestHelpers.spawn_entity(context.surface, "stone-furnace", {x=2, y=2})
            local unit_number = furnace.unit_number
            
            -- Insert fuel without specifying inventory_type (should auto-resolve)
            local result = remote.call("actions", "entity.inventory.set_item", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                item = "coal",
                count = 5
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.item, "coal")
            TestAssertions.assert_equal(result.inserted, 5)
            
            -- Check fuel inventory
            TestAssertions.assert_inventory_contains(furnace, defines.inventory.fuel, "coal", 5)
        end,
        
        test_ambiguity_detection = function(context)
            -- Create an assembler (has both input and modules inventories)
            local assembler = TestHelpers.create_test_assembler(context.surface, {x=2, y=2})
            local unit_number = assembler.unit_number
            
            -- Try inserting module without specifying inventory_type
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.set_item", {
                    agent_id = context.agent.player_index,
                    unit_number = unit_number,
                    item = "speed-module",
                    count = 1
                })
            end)
            
            -- Should fail with ambiguity error
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "Ambiguous")
            TestAssertions.assert_contains(error, "specify inventory_type")
        end,
        
        test_inventory_space_validation = function(context)
            -- Create a small chest and fill it
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local unit_number = chest.unit_number
            
            -- Fill chest to capacity
            local inventory = chest.get_inventory(defines.inventory.chest)
            for i = 1, inventory.size do
                inventory.insert({name = "iron-plate", count = 1})
            end
            
            -- Try inserting more items
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.set_item", {
                    agent_id = context.agent.player_index,
                    unit_number = unit_number,
                    item = "copper-plate",
                    count = 1,
                    inventory_type = "chest"
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "cannot accept")
        end,
        
        test_agent_insufficient_items = function(context)
            -- Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local unit_number = chest.unit_number
            
            -- Try inserting more items than agent has
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.set_item", {
                    agent_id = context.agent.player_index,
                    unit_number = unit_number,
                    item = "iron-plate",
                    count = 100, -- Agent only has 50
                    inventory_type = "chest"
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "does not have enough items")
        end,
        
        test_invalid_inventory_type = function(context)
            -- Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local unit_number = chest.unit_number
            
            -- Try with invalid inventory_type
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.set_item", {
                    agent_id = context.agent.player_index,
                    unit_number = unit_number,
                    item = "iron-plate",
                    count = 1,
                    inventory_type = "invalid_type"
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "Invalid inventory_type")
        end,
        
        test_entity_no_inventory = function(context)
            -- Create an entity without the specified inventory
            local inserter = TestHelpers.spawn_entity(context.surface, "inserter", {x=2, y=2})
            local unit_number = inserter.unit_number
            
            -- Try inserting into non-existent inventory
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.set_item", {
                    agent_id = context.agent.player_index,
                    unit_number = unit_number,
                    item = "iron-plate",
                    count = 1,
                    inventory_type = "chest"
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "does not have inventory type")
        end,
        
        test_item_type_validation = function(context)
            -- Create an assembler
            local assembler = TestHelpers.create_test_assembler(context.surface, {x=2, y=2})
            local unit_number = assembler.unit_number
            
            -- Try inserting non-module into modules inventory
            local success, error = pcall(function()
                remote.call("actions", "entity.inventory.set_item", {
                    agent_id = context.agent.player_index,
                    unit_number = unit_number,
                    item = "iron-plate",
                    count = 1,
                    inventory_type = "modules"
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "is not a module")
        end,
        
        test_default_count = function(context)
            -- Create a chest
            local chest = TestHelpers.create_test_chest(context.surface, {x=2, y=2})
            local unit_number = chest.unit_number
            
            -- Insert item without specifying count (should default to 1)
            local result = remote.call("actions", "entity.inventory.set_item", {
                agent_id = context.agent.player_index,
                unit_number = unit_number,
                item = "iron-plate",
                inventory_type = "chest"
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.count, 1)
            TestAssertions.assert_equal(result.inserted, 1)
            
            -- Check inventory
            TestAssertions.assert_inventory_contains(chest, defines.inventory.chest, "iron-plate", 1)
        end
    },
    
    teardown = function(context)
        -- Clean up test artifacts
        TestHelpers.clear_test_area(context.surface, context.test_area)
    end
}
