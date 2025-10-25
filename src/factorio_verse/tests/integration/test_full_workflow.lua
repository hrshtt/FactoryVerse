local TestHelpers = require("core.test.TestHelpers")
local TestAssertions = require("core.test.TestAssertions")

return {
    name = "integration.full_workflow",
    
    setup = function(context)
        -- Create test surface area
        context.surface = game.surfaces[1]
        context.test_area = TestHelpers.create_test_area({x=0, y=0}, 30)
        context.agent = TestHelpers.spawn_agent(context.surface, {x=0, y=0})
        
        -- Clear agent inventory
        TestHelpers.clear_agent_inventory(context.agent)
    end,
    
    tests = {
        test_complete_workflow = function(context)
            -- Step 1: Find and mine a resource
            local resource = TestHelpers.get_nearby_resource(context.surface, {x=5, y=5}, "iron-ore")
            if not resource then
                -- Create a resource if none exists
                resource = TestHelpers.spawn_entity(context.surface, "iron-ore", {x=5, y=5})
            end
            
            local resource_unit_number = resource.unit_number
            
            -- Mine the resource
            local mine_result = remote.call("actions", "mine_resource", {
                agent_id = context.agent.player_index,
                resource_unit_number = resource_unit_number,
                count = 10
            })
            
            TestAssertions.assert_not_nil(mine_result)
            TestAssertions.assert_agent_has_items(context.agent, {["iron-ore"] = 10})
            
            -- Step 2: Place a chest
            local place_result = remote.call("actions", "entity.place", {
                agent_id = context.agent.player_index,
                entity_type = "wooden-chest",
                position = {x=10, y=10}
            })
            
            TestAssertions.assert_not_nil(place_result)
            local chest_unit_number = place_result.unit_number
            TestAssertions.assert_entity_exists(chest_unit_number)
            
            -- Step 3: Insert items into chest
            local set_item_result = remote.call("actions", "entity.inventory.set_item", {
                agent_id = context.agent.player_index,
                unit_number = chest_unit_number,
                item = "iron-ore",
                count = 5,
                inventory_type = "chest"
            })
            
            TestAssertions.assert_not_nil(set_item_result)
            TestAssertions.assert_equal(set_item_result.inserted, 5)
            
            -- Verify chest has items
            local chest = game.get_entity_by_unit_number(chest_unit_number)
            TestAssertions.assert_inventory_contains(chest, defines.inventory.chest, "iron-ore", 5)
            
            -- Verify agent inventory reduced
            TestAssertions.assert_agent_has_items(context.agent, {["iron-ore"] = 5})
            
            -- Step 4: Place an assembler
            local assembler_place_result = remote.call("actions", "entity.place", {
                agent_id = context.agent.player_index,
                entity_type = "assembling-machine-1",
                position = {x=15, y=15}
            })
            
            TestAssertions.assert_not_nil(assembler_place_result)
            local assembler_unit_number = assembler_place_result.unit_number
            TestAssertions.assert_entity_exists(assembler_unit_number)
            
            -- Step 5: Set recipe on assembler
            local set_recipe_result = remote.call("actions", "entity.set_recipe", {
                agent_id = context.agent.player_index,
                unit_number = assembler_unit_number,
                recipe = "iron-plate"
            })
            
            TestAssertions.assert_not_nil(set_recipe_result)
            TestAssertions.assert_equal(set_recipe_result.new_recipe, "iron-plate")
            
            -- Verify recipe is set
            local assembler = game.get_entity_by_unit_number(assembler_unit_number)
            TestAssertions.assert_recipe_set(assembler, "iron-plate")
            
            -- Step 6: Insert materials into assembler
            local assembler_set_item_result = remote.call("actions", "entity.inventory.set_item", {
                agent_id = context.agent.player_index,
                unit_number = assembler_unit_number,
                item = "iron-ore",
                count = 3,
                inventory_type = "input"
            })
            
            TestAssertions.assert_not_nil(assembler_set_item_result)
            TestAssertions.assert_equal(assembler_set_item_result.inserted, 3)
            
            -- Verify assembler has input materials
            TestAssertions.assert_inventory_contains(assembler, defines.inventory.assembling_machine_input, "iron-ore", 3)
            
            -- Step 7: Set inventory limit on assembler output
            local set_limit_result = remote.call("actions", "entity.inventory.set_limit", {
                agent_id = context.agent.player_index,
                unit_number = assembler_unit_number,
                inventory_type = "output",
                limit = 2
            })
            
            TestAssertions.assert_not_nil(set_limit_result)
            TestAssertions.assert_equal(set_limit_result.new_limit, 2)
            
            -- Verify limit is set
            local output_inventory = assembler.get_inventory(defines.inventory.assembling_machine_output)
            TestAssertions.assert_equal(output_inventory.get_bar(), 2)
            
            -- Step 8: Wait for production (simulate by manually adding output)
            output_inventory.insert({name = "iron-plate", count = 2})
            
            -- Step 9: Extract output from assembler
            local get_item_result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = context.agent.player_index,
                unit_number = assembler_unit_number,
                item = "iron-plate",
                count = 2,
                inventory_type = "output"
            })
            
            TestAssertions.assert_not_nil(get_item_result)
            TestAssertions.assert_equal(get_item_result.total_transferred, 2)
            
            -- Verify agent has the output
            TestAssertions.assert_agent_has_items(context.agent, {["iron-plate"] = 2})
            
            -- Step 10: Rotate the assembler
            local rotate_result = remote.call("actions", "entity.rotate", {
                agent_id = context.agent.player_index,
                unit_number = assembler_unit_number,
                direction = "east"
            })
            
            TestAssertions.assert_not_nil(rotate_result)
            TestAssertions.assert_entity_direction(assembler, defines.direction.east)
            
            -- Step 11: Pick up the assembler
            local pickup_result = remote.call("actions", "entity.pickup", {
                agent_id = context.agent.player_index,
                unit_number = assembler_unit_number
            })
            
            TestAssertions.assert_not_nil(pickup_result)
            TestAssertions.assert_equal(pickup_result.entity_name, "assembling-machine-1")
            
            -- Verify agent has the assembler
            TestAssertions.assert_agent_has_items(context.agent, {["assembling-machine-1"] = 1})
            
            -- Verify assembler is removed
            TestAssertions.assert_entity_exists(assembler_unit_number) -- Should fail since entity is destroyed
        end,
        
        test_workflow_with_failures = function(context)
            -- Test error handling in workflow
            
            -- Try to place entity at occupied position
            local chest = TestHelpers.create_test_chest(context.surface, {x=10, y=10})
            
            local success, error = pcall(function()
                remote.call("actions", "entity.place", {
                    agent_id = context.agent.player_index,
                    entity_type = "wooden-chest",
                    position = {x=10, y=10}
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "Position occupied")
            
            -- Try to insert items without having them
            local success2, error2 = pcall(function()
                remote.call("actions", "entity.inventory.set_item", {
                    agent_id = context.agent.player_index,
                    unit_number = chest.unit_number,
                    item = "steel-plate",
                    count = 10,
                    inventory_type = "chest"
                })
            end)
            
            TestAssertions.assert_equal(success2, false)
            TestAssertions.assert_contains(error2, "does not have enough items")
            
            -- Try to set recipe on non-recipe entity
            local success3, error3 = pcall(function()
                remote.call("actions", "entity.set_recipe", {
                    agent_id = context.agent.player_index,
                    unit_number = chest.unit_number,
                    recipe = "iron-plate"
                })
            end)
            
            TestAssertions.assert_equal(success3, false)
            TestAssertions.assert_contains(error3, "does not support recipes")
        end,
        
        test_inventory_management_workflow = function(context)
            -- Test complex inventory management
            
            -- Create multiple chests
            local chest1 = TestHelpers.create_test_chest(context.surface, {x=5, y=5}, {
                ["iron-plate"] = 20,
                ["copper-plate"] = 15
            })
            
            local chest2 = TestHelpers.create_test_chest(context.surface, {x=10, y=10})
            
            -- Transfer items between chests via agent
            local get_result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = context.agent.player_index,
                unit_number = chest1.unit_number,
                item = "iron-plate",
                count = 10,
                inventory_type = "chest"
            })
            
            TestAssertions.assert_not_nil(get_result)
            TestAssertions.assert_equal(get_result.total_transferred, 10)
            
            local set_result = remote.call("actions", "entity.inventory.set_item", {
                agent_id = context.agent.player_index,
                unit_number = chest2.unit_number,
                item = "iron-plate",
                count = 10,
                inventory_type = "chest"
            })
            
            TestAssertions.assert_not_nil(set_result)
            TestAssertions.assert_equal(set_result.inserted, 10)
            
            -- Verify transfer completed
            TestAssertions.assert_inventory_contains(chest1, defines.inventory.chest, "iron-plate", 10)
            TestAssertions.assert_inventory_contains(chest2, defines.inventory.chest, "iron-plate", 10)
            
            -- Test batch operations
            local batch_get_result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = context.agent.player_index,
                unit_number = chest1.unit_number,
                item = {
                    ["iron-plate"] = 5,
                    ["copper-plate"] = 8
                },
                inventory_type = "chest"
            })
            
            TestAssertions.assert_not_nil(batch_get_result)
            TestAssertions.assert_equal(batch_get_result.total_transferred, 13)
            
            -- Test ALL_ITEMS operation
            local all_items_result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = context.agent.player_index,
                unit_number = chest2.unit_number,
                item = "ALL_ITEMS",
                inventory_type = "chest"
            })
            
            TestAssertions.assert_not_nil(all_items_result)
            TestAssertions.assert_equal(all_items_result.total_transferred, 10)
        end,
        
        test_agent_movement_coordination = function(context)
            -- Test agent movement during workflow
            
            -- Place entities at different positions
            local chest1 = TestHelpers.create_test_chest(context.surface, {x=20, y=20}, {
                ["iron-plate"] = 10
            })
            
            local chest2 = TestHelpers.create_test_chest(context.surface, {x=25, y=25})
            
            -- Agent should be able to reach both positions
            local walk_result1 = remote.call("actions", "agent.walk", {
                agent_id = context.agent.player_index,
                x = 20,
                y = 20
            })
            
            TestAssertions.assert_not_nil(walk_result1)
            
            -- Get items from first chest
            local get_result = remote.call("actions", "entity.inventory.get_item", {
                agent_id = context.agent.player_index,
                unit_number = chest1.unit_number,
                item = "iron-plate",
                count = 5,
                inventory_type = "chest"
            })
            
            TestAssertions.assert_not_nil(get_result)
            
            -- Walk to second chest
            local walk_result2 = remote.call("actions", "agent.walk", {
                agent_id = context.agent.player_index,
                x = 25,
                y = 25
            })
            
            TestAssertions.assert_not_nil(walk_result2)
            
            -- Place items in second chest
            local set_result = remote.call("actions", "entity.inventory.set_item", {
                agent_id = context.agent.player_index,
                unit_number = chest2.unit_number,
                item = "iron-plate",
                count = 5,
                inventory_type = "chest"
            })
            
            TestAssertions.assert_not_nil(set_result)
        end
    },
    
    teardown = function(context)
        -- Clean up test artifacts
        TestHelpers.clear_test_area(context.surface, context.test_area)
    end
}
