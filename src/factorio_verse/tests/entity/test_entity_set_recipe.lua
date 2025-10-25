local TestHelpers = require("core.test.TestHelpers")
local TestAssertions = require("core.test.TestAssertions")

return {
    name = "entity.set_recipe",
    
    setup = function(context)
        -- Create test surface area
        context.surface = game.surfaces[1]
        context.test_area = TestHelpers.create_test_area({x=0, y=0}, 20)
        context.agent = TestHelpers.spawn_agent(context.surface, {x=0, y=0})
        
        -- Create an assembler for testing
        context.assembler = TestHelpers.create_test_assembler(context.surface, {x=2, y=2})
        context.unit_number = context.assembler.unit_number
    end,
    
    tests = {
        test_set_recipe_on_assembler = function(context)
            -- Execute set_recipe action
            local result = remote.call("actions", "entity.set_recipe", {
                agent_id = context.agent.player_index,
                unit_number = context.unit_number,
                recipe = "iron-plate"
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.new_recipe, "iron-plate")
            TestAssertions.assert_equal(result.action, "set")
            
            -- Check recipe is actually set
            TestAssertions.assert_recipe_set(context.assembler, "iron-plate")
        end,
        
        test_recipe_compatibility_validation = function(context)
            -- Try setting an incompatible recipe
            local success, error = pcall(function()
                remote.call("actions", "entity.set_recipe", {
                    agent_id = context.agent.player_index,
                    unit_number = context.unit_number,
                    recipe = "non-existent-recipe"
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "Recipe not found")
        end,
        
        test_overwrite_protection = function(context)
            -- Set initial recipe
            context.assembler.set_recipe("iron-plate")
            
            -- Try setting different recipe without overwrite
            local success, error = pcall(function()
                remote.call("actions", "entity.set_recipe", {
                    agent_id = context.agent.player_index,
                    unit_number = context.unit_number,
                    recipe = "copper-plate"
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "already has recipe")
            TestAssertions.assert_contains(error, "Set overwrite=true")
        end,
        
        test_overwrite_allowed = function(context)
            -- Set initial recipe
            context.assembler.set_recipe("iron-plate")
            
            -- Set different recipe with overwrite
            local result = remote.call("actions", "entity.set_recipe", {
                agent_id = context.agent.player_index,
                unit_number = context.unit_number,
                recipe = "copper-plate",
                overwrite = true
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.previous_recipe, "iron-plate")
            TestAssertions.assert_equal(result.new_recipe, "copper-plate")
            TestAssertions.assert_equal(result.action, "set")
            
            -- Check recipe is actually changed
            TestAssertions.assert_recipe_set(context.assembler, "copper-plate")
        end,
        
        test_clear_recipe = function(context)
            -- Set initial recipe
            context.assembler.set_recipe("iron-plate")
            
            -- Clear recipe
            local result = remote.call("actions", "entity.set_recipe", {
                agent_id = context.agent.player_index,
                unit_number = context.unit_number,
                recipe = nil
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.previous_recipe, "iron-plate")
            TestAssertions.assert_nil(result.new_recipe)
            TestAssertions.assert_equal(result.action, "cleared")
            
            -- Check recipe is actually cleared
            TestAssertions.assert_recipe_set(context.assembler, nil)
        end,
        
        test_clear_recipe_no_op = function(context)
            -- Don't set any recipe initially
            
            -- Try clearing recipe
            local result = remote.call("actions", "entity.set_recipe", {
                agent_id = context.agent.player_index,
                unit_number = context.unit_number,
                recipe = nil
            })
            
            -- Should be no-op
            TestAssertions.assert_equal(result.action, "no_op")
            TestAssertions.assert_contains(result.message, "already has no recipe")
        end,
        
        test_non_recipe_entity = function(context)
            -- Create a non-recipe entity (chest)
            local chest = TestHelpers.create_test_chest(context.surface, {x=5, y=5})
            
            -- Try setting recipe
            local success, error = pcall(function()
                remote.call("actions", "entity.set_recipe", {
                    agent_id = context.agent.player_index,
                    unit_number = chest.unit_number,
                    recipe = "iron-plate"
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "does not support recipes")
        end,
        
        test_recipe_already_set_no_op = function(context)
            -- Set recipe
            context.assembler.set_recipe("iron-plate")
            
            -- Try setting same recipe
            local result = remote.call("actions", "entity.set_recipe", {
                agent_id = context.agent.player_index,
                unit_number = context.unit_number,
                recipe = "iron-plate"
            })
            
            -- Should be no-op
            TestAssertions.assert_equal(result.action, "no_op")
            TestAssertions.assert_contains(result.message, "already has this recipe")
        end,
        
        test_entity_not_found = function(context)
            -- Try setting recipe on non-existent entity
            local success, error = pcall(function()
                remote.call("actions", "entity.set_recipe", {
                    agent_id = context.agent.player_index,
                    unit_number = 99999,
                    recipe = "iron-plate"
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "Entity not found")
        end,
        
        test_furnace_recipe = function(context)
            -- Create a furnace for testing
            local furnace = TestHelpers.spawn_entity(context.surface, "stone-furnace", {x=5, y=5})
            
            -- Set recipe on furnace
            local result = remote.call("actions", "entity.set_recipe", {
                agent_id = context.agent.player_index,
                unit_number = furnace.unit_number,
                recipe = "iron-plate"
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_equal(result.new_recipe, "iron-plate")
            TestAssertions.assert_recipe_set(furnace, "iron-plate")
        end
    },
    
    teardown = function(context)
        -- Clean up test artifacts
        TestHelpers.clear_test_area(context.surface, context.test_area)
    end
}
