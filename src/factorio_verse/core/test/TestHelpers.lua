--- @class TestHelpers
--- Common test utilities for FactoryVerse testing
local TestHelpers = {}
TestHelpers.__index = TestHelpers

--- Create a new TestHelpers instance
--- @return TestHelpers
function TestHelpers:new()
    local instance = {}
    setmetatable(instance, self)
    return instance
end

--- Spawn a test agent at the specified position
--- @param surface LuaSurface
--- @param position MapPosition
--- @return LuaPlayer
function TestHelpers.spawn_agent(surface, position)
    local player = game.create_force("test_force")
    local character = surface.create_entity({
        name = "character",
        position = position,
        force = player
    })
    
    -- Create a player for the character
    local player_index = game.players[1] -- Use existing player for testing
    if not player_index then
        error("No players available for testing")
    end
    player_index.character = character
    player_index.force = player
    
    return player_index
end

--- Spawn an entity at the specified position
--- @param surface LuaSurface
--- @param entity_name string
--- @param position MapPosition
--- @param force LuaForce|nil
--- @return LuaEntity
function TestHelpers.spawn_entity(surface, entity_name, position, force)
    force = force or game.forces.player
    
    local entity = surface.create_entity({
        name = entity_name,
        position = position,
        force = force
    })
    
    return entity
end

--- Find a nearby mineable resource
--- @param surface LuaSurface
--- @param position MapPosition
--- @param resource_type string|nil
--- @return LuaEntity?
function TestHelpers.get_nearby_resource(surface, position, resource_type)
    local search_area = {
        {position.x - 10, position.y - 10},
        {position.x + 10, position.y + 10}
    }
    
    local resources = surface.find_entities_filtered({
        area = search_area,
        type = "resource"
    })
    
    if resource_type then
        for _, resource in ipairs(resources) do
            if resource.name == resource_type then
                return resource
            end
        end
    else
        return resources[1] -- Return first resource found
    end
    
    return nil
end

--- Validate inventory contents against expected items
--- @param entity LuaEntity
--- @param inventory_type defines.inventory
--- @param expected_contents table<string, number>
--- @return boolean, string|nil
function TestHelpers.validate_inventory(entity, inventory_type, expected_contents)
    local inventory = entity.get_inventory(inventory_type)
    if not inventory then
        return false, "Entity does not have inventory type: " .. tostring(inventory_type)
    end
    
    local actual_contents = inventory.get_contents()
    
    for item_name, expected_count in pairs(expected_contents) do
        local actual_count = actual_contents[item_name] or 0
        if actual_count ~= expected_count then
            return false, "Expected " .. expected_count .. " " .. item_name .. 
                         ", got " .. actual_count
        end
    end
    
    -- Check for unexpected items
    for item_name, actual_count in pairs(actual_contents) do
        if not expected_contents[item_name] and actual_count > 0 then
            return false, "Unexpected item in inventory: " .. item_name .. " (count: " .. actual_count .. ")"
        end
    end
    
    return true
end

--- Clear all entities in a test area
--- @param surface LuaSurface
--- @param area table<MapPosition, MapPosition>
function TestHelpers.clear_test_area(surface, area)
    local entities = surface.find_entities_filtered({
        area = area,
        type = {"character", "resource", "container", "assembling-machine", "inserter", "furnace"}
    })
    
    for _, entity in ipairs(entities) do
        if entity.valid then
            entity.destroy()
        end
    end
end

--- Wait for a specified number of ticks (for async testing)
--- @param ticks number
--- @return boolean
function TestHelpers.wait_ticks(ticks)
    -- In Factorio, we can't actually wait during test execution
    -- This is a placeholder for future async test support
    return true
end

--- Get agent inventory
--- @param agent LuaPlayer
--- @return LuaInventory?
function TestHelpers.get_agent_inventory(agent)
    return agent.get_inventory(defines.inventory.character_main)
end

--- Give items to an agent
--- @param agent LuaPlayer
--- @param items table<string, number>
--- @return boolean
function TestHelpers.give_agent_items(agent, items)
    local inventory = TestHelpers.get_agent_inventory(agent)
    
    for item_name, count in pairs(items) do
        local inserted = inventory.insert({name = item_name, count = count})
        if inserted < count then
            return false
        end
    end
    
    return true
end

--- Clear agent inventory
--- @param agent LuaPlayer
function TestHelpers.clear_agent_inventory(agent)
    local inventory = TestHelpers.get_agent_inventory(agent)
    inventory.clear()
end

--- Find entities of a specific type in an area
--- @param surface LuaSurface
--- @param area table<MapPosition, MapPosition>
--- @param entity_type string|nil
--- @param entity_name string|nil
--- @return table<LuaEntity>
function TestHelpers.find_entities_in_area(surface, area, entity_type, entity_name)
    local filter = {area = area}
    
    if entity_type then
        filter.type = entity_type
    end
    
    if entity_name then
        filter.name = entity_name
    end
    
    return surface.find_entities_filtered(filter)
end

--- Create a test chest with items
--- @param surface LuaSurface
--- @param position MapPosition
--- @param items table<string, number>|nil
--- @return LuaEntity
function TestHelpers.create_test_chest(surface, position, items)
    local chest = TestHelpers.spawn_entity(surface, "wooden-chest", position)
    
    if items then
        local inventory = chest.get_inventory(defines.inventory.chest)
        for item_name, count in pairs(items) do
            inventory.insert({name = item_name, count = count})
        end
    end
    
    return chest
end

--- Create a test assembler
--- @param surface LuaSurface
--- @param position MapPosition
--- @param recipe string|nil
--- @return LuaEntity
function TestHelpers.create_test_assembler(surface, position, recipe)
    local assembler = TestHelpers.spawn_entity(surface, "assembling-machine-1", position)
    
    if recipe then
        assembler.set_recipe(recipe)
    end
    
    return assembler
end

--- Get entity at specific position
--- @param surface LuaSurface
--- @param position MapPosition
--- @return LuaEntity?
function TestHelpers.get_entity_at_position(surface, position)
    local entities = surface.find_entities_filtered({
        position = position,
        radius = 0.1
    })
    
    return entities[1]
end

--- Check if position is clear (no entities)
--- @param surface LuaSurface
--- @param position MapPosition
--- @return boolean
function TestHelpers.is_position_clear(surface, position)
    local entities = surface.find_entities_filtered({
        position = position,
        radius = 0.1
    })
    
    return #entities == 0
end

--- Create a test area around a position
--- @param center MapPosition
--- @param radius number
--- @return table<MapPosition, MapPosition>
function TestHelpers.create_test_area(center, radius)
    return {
        {center.x - radius, center.y - radius},
        {center.x + radius, center.y + radius}
    }
end

return TestHelpers:new()
