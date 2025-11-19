-- Test entity.set_recipe action
local TestHelpers = require("__factorio_verse__.core.test.TestHelpers")

return {
    name = "entity.set_recipe",
    
    setup = function(context)
        context.surface = game.surfaces[1]
        
        -- Create agent via admin_api - returns table of created agents
        local agents = remote.call("helpers", "create_agent_characters", 1, true)
        if not agents or #agents == 0 then
            error("Failed to create test agent")
        end
        context.agent = agents[1]
        
        -- Create an assembler for testing
        context.assembler = TestHelpers.create_test_assembler(context.surface, {x=2, y=2})
        context.position = context.assembler.position
        context.entity_name = context.assembler.name
    end,
    
    tests = {
        test_set_recipe_on_assembler = function(context)
            -- Execute set_recipe action
            local result = remote.call("actions", "entity.set_recipe", {
                agent_id = 1,
                position_x = context.position.x,
                position_y = context.position.y,
                entity_name = context.entity_name,
                recipe = "electronic-circuit"
            })
            
            if not result then
                error("set_recipe returned nil")
            end
            if result.new_recipe ~= "electronic-circuit" then
                error("Expected new_recipe to be electronic-circuit, got: " .. tostring(result.new_recipe))
            end
            if context.assembler.get_recipe().name ~= "electronic-circuit" then
                error("Assembler recipe not actually set")
            end
        end,
        
        test_recipe_compatibility_validation = function(context)
            -- Try setting an incompatible recipe
            local success, error = pcall(function()
                remote.call("actions", "entity.set_recipe", {
                    agent_id = 1,
                    position_x = context.position.x,
                    position_y = context.position.y,
                    entity_name = context.entity_name,
                    recipe = "non-existent-recipe"
                })
            end)
            
            if success then
                error("Expected set_recipe to fail for non-existent recipe")
            end
        end,
        
        test_overwrite_protection = function(context)
            -- Set initial recipe (crafting recipe compatible with assembler)
            context.assembler.set_recipe("electronic-circuit")
            
            -- Try setting different recipe without overwrite
            local success, error = pcall(function()
                remote.call("actions", "entity.set_recipe", {
                    agent_id = 1,
                    position_x = context.position.x,
                    position_y = context.position.y,
                    entity_name = context.entity_name,
                    recipe = "copper-cable"
                })
            end)
            
            if success then
                error("Expected set_recipe to fail when overwrite=false and recipe already set")
            end
        end,
        
        test_overwrite_allowed = function(context)
            -- Set initial recipe (crafting recipe)
            context.assembler.set_recipe("electronic-circuit")
            
            -- Set different recipe with overwrite
            local result = remote.call("actions", "entity.set_recipe", {
                agent_id = 1,
                position_x = context.position.x,
                position_y = context.position.y,
                entity_name = context.entity_name,
                recipe = "copper-cable",
                overwrite = true
            })
            
            if not result then
                error("set_recipe with overwrite returned nil")
            end
            if result.previous_recipe ~= "electronic-circuit" then
                error("Expected previous_recipe to be electronic-circuit")
            end
            if result.new_recipe ~= "copper-cable" then
                error("Expected new_recipe to be copper-cable")
            end
        end
    },
    
    teardown = function(context)
        -- Cleanup handled by game
    end
}
