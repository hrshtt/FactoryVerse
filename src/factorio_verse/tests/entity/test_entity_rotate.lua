local TestHelpers = require("core.test.TestHelpers")
local TestAssertions = require("core.test.TestAssertions")

return {
    name = "entity.rotate",
    
    setup = function(context)
        -- Create test surface area
        context.surface = game.surfaces[1]
        context.test_area = TestHelpers.create_test_area({x=0, y=0}, 20)
        context.agent = TestHelpers.spawn_agent(context.surface, {x=0, y=0})
        
        -- Place a rotatable entity (inserter)
        context.entity = TestHelpers.spawn_entity(context.surface, "inserter", {x=2, y=2})
        context.unit_number = context.entity.unit_number
    end,
    
    tests = {
        test_rotate_to_specific_direction = function(context)
            -- Execute rotate action
            local result = remote.call("actions", "entity.rotate", {
                agent_id = context.agent.player_index,
                unit_number = context.unit_number,
                direction = "north"
            })
            
            -- Validate result
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_entity_direction(context.entity, defines.direction.north)
        end,
        
        test_rotate_cycle = function(context)
            -- Test rotation cycle (45 degrees)
            local original_direction = context.entity.direction
            
            local result = remote.call("actions", "entity.rotate", {
                agent_id = context.agent.player_index,
                unit_number = context.unit_number
            })
            
            -- Should rotate 45 degrees clockwise
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_not_equal(context.entity.direction, original_direction)
        end,
        
        test_rotate_no_op = function(context)
            -- Set entity to north first
            context.entity.direction = defines.direction.north
            
            -- Try rotating to same direction
            local result = remote.call("actions", "entity.rotate", {
                agent_id = context.agent.player_index,
                unit_number = context.unit_number,
                direction = "north"
            })
            
            -- Should be marked as no-op
            TestAssertions.assert_equal(result.no_op, true)
            TestAssertions.assert_contains(result.message, "already in requested direction")
        end,
        
        test_non_rotatable_entity = function(context)
            -- Place non-rotatable entity (assembler)
            local assembler = TestHelpers.spawn_entity(context.surface, "assembling-machine-1", {x=5, y=5})
            
            -- Try rotating - should fail validation
            local success, error = pcall(function()
                remote.call("actions", "entity.rotate", {
                    agent_id = context.agent.player_index,
                    unit_number = assembler.unit_number,
                    direction = "north"
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "does not support rotation")
        end,
        
        test_invalid_direction = function(context)
            -- Try rotating with invalid direction
            local success, error = pcall(function()
                remote.call("actions", "entity.rotate", {
                    agent_id = context.agent.player_index,
                    unit_number = context.unit_number,
                    direction = "invalid_direction"
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "Invalid direction value")
        end,
        
        test_numeric_direction = function(context)
            -- Test with numeric direction
            local result = remote.call("actions", "entity.rotate", {
                agent_id = context.agent.player_index,
                unit_number = context.unit_number,
                direction = defines.direction.east
            })
            
            TestAssertions.assert_not_nil(result)
            TestAssertions.assert_entity_direction(context.entity, defines.direction.east)
        end,
        
        test_entity_not_found = function(context)
            -- Try rotating non-existent entity
            local success, error = pcall(function()
                remote.call("actions", "entity.rotate", {
                    agent_id = context.agent.player_index,
                    unit_number = 99999,
                    direction = "north"
                })
            end)
            
            TestAssertions.assert_equal(success, false)
            TestAssertions.assert_contains(error, "Entity not found")
        end
    },
    
    teardown = function(context)
        -- Clean up test artifacts
        TestHelpers.clear_test_area(context.surface, context.test_area)
    end
}
