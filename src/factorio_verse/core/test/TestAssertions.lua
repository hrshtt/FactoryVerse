--- @class TestAssertions
--- Custom assertions for Factorio-specific validation
local TestAssertions = {}
TestAssertions.__index = TestAssertions

--- Create a new TestAssertions instance
--- @return TestAssertions
function TestAssertions:new()
    local instance = {}
    setmetatable(instance, self)
    return instance
end

--- Basic assertion: values are equal
--- @param actual any
--- @param expected any
--- @param message string|nil
function TestAssertions.assert_equal(actual, expected, message)
    if actual ~= expected then
        local error_msg = message or ("Expected " .. tostring(expected) .. ", got " .. tostring(actual))
        error(error_msg)
    end
end

--- Basic assertion: value is not nil
--- @param value any
--- @param message string|nil
function TestAssertions.assert_not_nil(value, message)
    if value == nil then
        local error_msg = message or "Expected non-nil value"
        error(error_msg)
    end
end

--- Basic assertion: value is nil
--- @param value any
--- @param message string|nil
function TestAssertions.assert_nil(value, message)
    if value ~= nil then
        local error_msg = message or ("Expected nil, got " .. tostring(value))
        error(error_msg)
    end
end

--- Basic assertion: value is true
--- @param value any
--- @param message string|nil
function TestAssertions.assert_true(value, message)
    if value ~= true then
        local error_msg = message or ("Expected true, got " .. tostring(value))
        error(error_msg)
    end
end

--- Basic assertion: value is false
--- @param value any
--- @param message string|nil
function TestAssertions.assert_false(value, message)
    if value ~= false then
        local error_msg = message or ("Expected false, got " .. tostring(value))
        error(error_msg)
    end
end

--- Basic assertion: string contains substring
--- @param str string
--- @param substring string
--- @param message string|nil
function TestAssertions.assert_contains(str, substring, message)
    if not string.find(str, substring, 1, true) then
        local error_msg = message or ("Expected string to contain '" .. substring .. "', got: " .. str)
        error(error_msg)
    end
end

--- Factorio-specific: entity exists and is valid
--- @param position table - {x, y} entity position
--- @param entity_name string - entity prototype name
--- @param message string|nil
function TestAssertions.assert_entity_exists(position, entity_name, message)
    local entity = game.surfaces[1].find_entity(entity_name, position)
    if not entity or not entity.valid then
        local error_msg = message or ("Entity '" .. tostring(entity_name) .. "' at position {" .. tostring(position.x) .. ", " .. tostring(position.y) .. "} does not exist or is invalid")
        error(error_msg)
    end
end

--- Factorio-specific: entity at specific position
--- @param surface LuaSurface
--- @param position MapPosition
--- @param entity_name string|nil
--- @param message string|nil
function TestAssertions.assert_entity_at_position(surface, position, entity_name, message)
    local entities = surface.find_entities_filtered({
        position = position,
        radius = 0.1
    })
    
    if #entities == 0 then
        local error_msg = message or ("No entity found at position " .. tostring(position.x) .. ", " .. tostring(position.y))
        error(error_msg)
    end
    
    if entity_name then
        local found = false
        for _, entity in ipairs(entities) do
            if entity.name == entity_name then
                found = true
                break
            end
        end
        
        if not found then
            local error_msg = message or ("Entity '" .. entity_name .. "' not found at position " .. tostring(position.x) .. ", " .. tostring(position.y))
            error(error_msg)
        end
    end
end

--- Factorio-specific: inventory contains specific items
--- @param entity LuaEntity
--- @param inventory_type defines.inventory
--- @param item_name string
--- @param count number
--- @param message string|nil
function TestAssertions.assert_inventory_contains(entity, inventory_type, item_name, count, message)
    local inventory = entity.get_inventory(inventory_type)
    if not inventory then
        local error_msg = message or ("Entity does not have inventory type: " .. tostring(inventory_type))
        error(error_msg)
    end
    
    local actual_count = inventory.get_item_count(item_name)
    if actual_count < count then
        local error_msg = message or ("Expected at least " .. count .. " " .. item_name .. 
                                     " in inventory, got " .. actual_count)
        error(error_msg)
    end
end

--- Factorio-specific: recipe is set on entity
--- @param entity LuaEntity
--- @param recipe_name string|nil
--- @param message string|nil
function TestAssertions.assert_recipe_set(entity, recipe_name, message)
    local current_recipe = entity.get_recipe()
    local current_recipe_name = current_recipe and current_recipe.name or nil
    
    if recipe_name == nil then
        if current_recipe_name ~= nil then
            local error_msg = message or ("Expected no recipe, got: " .. tostring(current_recipe_name))
            error(error_msg)
        end
    else
        if current_recipe_name ~= recipe_name then
            local error_msg = message or ("Expected recipe '" .. recipe_name .. "', got: " .. tostring(current_recipe_name))
            error(error_msg)
        end
    end
end

--- Factorio-specific: entity has specific direction
--- @param entity LuaEntity
--- @param direction number|string
--- @param message string|nil
function TestAssertions.assert_entity_direction(entity, direction, message)
    local expected_direction
    if type(direction) == "string" then
        -- Convert string direction to defines.direction
        local direction_map = {
            north = defines.direction.north,
            northeast = defines.direction.northeast,
            east = defines.direction.east,
            southeast = defines.direction.southeast,
            south = defines.direction.south,
            southwest = defines.direction.southwest,
            west = defines.direction.west,
            northwest = defines.direction.northwest
        }
        expected_direction = direction_map[direction]
        if not expected_direction then
            error("Invalid direction string: " .. direction)
        end
    else
        expected_direction = direction
    end
    
    if entity.direction ~= expected_direction then
        local error_msg = message or ("Expected direction " .. tostring(expected_direction) .. 
                                     ", got " .. tostring(entity.direction))
        error(error_msg)
    end
end

--- Factorio-specific: agent is at specific position (with tolerance)
--- @param agent LuaPlayer
--- @param expected_position MapPosition
--- @param tolerance number|nil
--- @param message string|nil
function TestAssertions.assert_agent_position(agent, expected_position, tolerance, message)
    tolerance = tolerance or 0.1
    
    if not agent.character then
        local error_msg = message or "Agent has no character"
        error(error_msg)
    end
    
    local actual_position = agent.character.position
    local distance = math.sqrt(
        (actual_position.x - expected_position.x)^2 + 
        (actual_position.y - expected_position.y)^2
    )
    
    if distance > tolerance then
        local error_msg = message or ("Expected agent at position " .. 
                                     tostring(expected_position.x) .. ", " .. tostring(expected_position.y) .. 
                                     " (tolerance: " .. tolerance .. "), got " .. 
                                     tostring(actual_position.x) .. ", " .. tostring(actual_position.y))
        error(error_msg)
    end
end

--- Factorio-specific: entity is minable
--- @param entity LuaEntity
--- @param message string|nil
function TestAssertions.assert_entity_minable(entity, message)
    if not entity.minable then
        local error_msg = message or ("Entity '" .. entity.name .. "' is not minable")
        error(error_msg)
    end
end

--- Factorio-specific: entity supports rotation
--- @param entity LuaEntity
--- @param message string|nil
function TestAssertions.assert_entity_rotatable(entity, message)
    if not entity.supports_direction then
        local error_msg = message or ("Entity '" .. entity.name .. "' does not support rotation")
        error(error_msg)
    end
end

--- Factorio-specific: inventory supports bar/limit
--- @param entity LuaEntity
--- @param inventory_type defines.inventory
--- @param message string|nil
function TestAssertions.assert_inventory_supports_bar(entity, inventory_type, message)
    local inventory = entity.get_inventory(inventory_type)
    if not inventory then
        local error_msg = message or ("Entity does not have inventory type: " .. tostring(inventory_type))
        error(error_msg)
    end
    
    if not inventory.supports_bar then
        local error_msg = message or ("Inventory does not support setting limits")
        error(error_msg)
    end
end

--- Factorio-specific: agent has specific items
--- @param agent LuaPlayer
--- @param items table<string, number>
--- @param message string|nil
function TestAssertions.assert_agent_has_items(agent, items, message)
    local inventory = agent.get_inventory(defines.inventory.character_main)
    if not inventory then
        local error_msg = message or "Agent has no inventory"
        error(error_msg)
    end
    
    for item_name, expected_count in pairs(items) do
        local actual_count = inventory.get_item_count(item_name)
        if actual_count < expected_count then
            local error_msg = message or ("Agent expected " .. expected_count .. " " .. item_name .. 
                                         ", got " .. actual_count)
            error(error_msg)
        end
    end
end

--- Factorio-specific: surface has no entities in area
--- @param surface LuaSurface
--- @param area table<MapPosition, MapPosition>
--- @param message string|nil
function TestAssertions.assert_area_empty(surface, area, message)
    local entities = surface.find_entities_filtered({area = area})
    if #entities > 0 then
        local error_msg = message or ("Expected empty area, found " .. #entities .. " entities")
        error(error_msg)
    end
end

return TestAssertions:new()
