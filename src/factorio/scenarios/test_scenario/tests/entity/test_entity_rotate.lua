-- Test entity.rotate action
-- Tests the mod's entity rotation API by calling it like agents would

return {
    name = "entity.rotate",
    
    setup = function(context)
        -- Get main surface
        context.surface = game.surfaces[1]
        
        -- Create agent via admin_api - returns table of created agents
        local agents = remote.call("helpers", "create_agent_characters", 1, true)
        if not agents or #agents == 0 then
            error("Failed to create test agent")
        end
        context.agent = agents[1]
        
        -- Place a rotatable entity (inserter) directly using Factorio API
        context.entity = context.surface.create_entity({
            name = "inserter",
            position = {x=2, y=2},
            force = game.forces.player
        })
        context.position = context.entity.position
        context.entity_name = context.entity.name
        
        -- Debug: verify entity exists in game context
        log("TEST DEBUG: Created entity " .. context.entity.name .. " at position {" .. context.position.x .. "," .. context.position.y .. "}")
        log("TEST DEBUG: Entity surface: " .. context.surface.name)
        log("TEST DEBUG: Game surfaces count: " .. #game.surfaces)
        for i, surf in pairs(game.surfaces) do
            log("TEST DEBUG: Surface[" .. i .. "]: " .. surf.name)
        end
        
        -- Try looking it up on the specific surface by position
        local lookup_test = context.surface.find_entity(context.entity_name, context.position)
        log("TEST DEBUG: Lookup test result: " .. tostring(lookup_test))
        
        -- Try looking it up on the specific surface
        local entities_on_surface = context.surface.find_entities_filtered({})
        log("TEST DEBUG: All entities on surface: " .. #entities_on_surface)
        
        local found_by_position = nil
        for _, entity in ipairs(entities_on_surface) do
            if entity.position.x == context.position.x and entity.position.y == context.position.y then
                found_by_position = entity
                break
            end
        end
        log("TEST DEBUG: Entity found by iterating: " .. tostring(found_by_position))
        
        -- Try finding by position instead
        local at_position = context.surface.find_entities_filtered({
            position = {x=2, y=2},
            radius = 0.5
        })
        log("TEST DEBUG: Entities at creation position: " .. #at_position)
        if #at_position > 0 then
            log("TEST DEBUG: Entity at position: name=" .. at_position[1].name .. ", pos={" .. at_position[1].position.x .. "," .. at_position[1].position.y .. "}")
        end
    end,
    
    tests = {
        test_rotate_to_specific_direction = function(context)
            -- Execute rotate action
            local result = remote.call("actions", "entity.rotate", {
                agent_id = 1,
                position_x = context.position.x,
                position_y = context.position.y,
                entity_name = context.entity_name,
                direction = "north"
            })
            
            -- Validate result
            if not result then
                error("Rotate returned nil")
            end
            if context.entity.direction ~= defines.direction.north then
                error("Entity not rotated to north. Got: " .. tostring(context.entity.direction))
            end
        end,
        
        test_rotate_cycle = function(context)
            -- Test rotation to specific direction
            local original_direction = context.entity.direction
            log("TEST: Original direction = " .. tostring(original_direction))
            
            -- Rotate to south (opposite of north)
            local target_direction = (original_direction + 4) % 8  -- 4 is opposite direction
            
            local result = remote.call("actions", "entity.rotate", {
                agent_id = 1,
                position_x = context.position.x,
                position_y = context.position.y,
                entity_name = context.entity_name,
                direction = target_direction
            })
            
            if not result then
                error("Rotate returned nil")
            end
            log("TEST: Result new_direction = " .. tostring(result.new_direction))
            
            -- Look up entity again after action to check direction
            local updated_entity = context.surface.find_entity(context.entity_name, context.position)
            if not updated_entity then
                error("Entity not found after rotate action")
            end
            log("TEST: Updated entity direction = " .. tostring(updated_entity.direction))
            if updated_entity.direction ~= target_direction then
                error("Entity direction not set to target (target=" .. target_direction .. ", actual=" .. updated_entity.direction .. ")")
            end
        end,
        
        test_rotate_no_op = function(context)
            -- Set entity to north first
            context.entity.direction = defines.direction.north
            
            -- Try rotating to same direction
            local result = remote.call("actions", "entity.rotate", {
                agent_id = 1,
                position_x = context.position.x,
                position_y = context.position.y,
                entity_name = context.entity_name,
                direction = "north"
            })
            
            -- Should be marked as no-op
            if not result.no_op then
                error("Expected no_op to be true")
            end
        end,
        
        test_non_rotatable_entity = function(context)
            -- Place non-rotatable entity (assembler)
            local assembler = context.surface.create_entity({
                name = "assembling-machine-1",
                position = {x=5, y=5},
                force = game.forces.player
            })
            
            -- Try rotating - should fail validation
            local success, error = pcall(function()
                remote.call("actions", "entity.rotate", {
                    agent_id = 1,
                    position_x = assembler.position.x,
                    position_y = assembler.position.y,
                    entity_name = assembler.name,
                    direction = "north"
                })
            end)
            
            if success then
                error("Expected rotation to fail for non-rotatable entity")
            end
        end,
        
        test_entity_not_found = function(context)
            -- Try rotating non-existent entity
            local success, error = pcall(function()
                remote.call("actions", "entity.rotate", {
                    agent_id = 1,
                    position_x = 99999,
                    position_y = 99999,
                    entity_name = "inserter",
                    direction = "north"
                })
            end)
            
            if success then
                error("Expected rotation to fail for non-existent entity")
            end
        end
    },
    
    teardown = function(context)
        -- Clean up test artifacts - destroy the entity
        if context.entity and context.entity.valid then
            context.entity.destroy()
        end
    end
}
