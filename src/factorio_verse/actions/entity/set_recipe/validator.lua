local GameState = require("GameState")

--- Validate that entity type supports recipes
--- @param params table
--- @return boolean, string|nil
local function validate_entity_supports_recipes(params)
    if not params.position or type(params.position.x) ~= "number" or type(params.position.y) ~= "number" then
        return true -- Let other validators handle missing parameters
    end
    
    local entity_name = params.entity_name
    if not entity_name then
        return true -- Let other validators handle missing parameters
    end
    
    local position = { x = params.position.x, y = params.position.y }
    local entity = game.surfaces[1].find_entity(entity_name, position)
    if not entity or not entity.valid then
        return true -- Let validate_entity_exists handle this
    end
    
    -- Check standard entity types
    local supported_types = {"assembling-machine", "furnace", "rocket-silo"}
    local is_supported = false
    for _, entity_type in ipairs(supported_types) do
        if entity.type == entity_type then
            is_supported = true
            break
        end
    end
    
    -- Also check if entity has crafting_categories (for modded entities)
    if not is_supported and entity.prototype and entity.prototype.crafting_categories then
        is_supported = true
    end
    
    if not is_supported then
        return false, "Entity type does not support recipes: " .. entity.type
    end
    
    return true
end

--- Validate recipe exists and is compatible
--- @param params table
--- @return boolean, string|nil
local function validate_recipe_compatibility(params)
    if not params.recipe then
        return true -- Skip if recipe not provided
    end
    
    if not params.position or type(params.position.x) ~= "number" or type(params.position.y) ~= "number" then
        return true -- Let other validators handle missing parameters
    end
    
    local entity_name = params.entity_name
    if not entity_name then
        return true -- Let other validators handle missing parameters
    end
    
    local position = { x = params.position.x, y = params.position.y }
    local entity = game.surfaces[1].find_entity(entity_name, position)
    if not entity or not entity.valid then
        return true -- Let validate_entity_exists handle this
    end
    
    -- Validate recipe exists
    local recipe_proto = prototypes and prototypes.recipe and prototypes.recipe[params.recipe]
    if not recipe_proto then
        return false, "Recipe not found: " .. params.recipe
    end
    
    -- Check recipe compatibility with entity
    local entity_categories = entity.prototype.crafting_categories
    if entity_categories then
        local recipe_category = recipe_proto.category or "crafting"
        local is_compatible = false
        for category_name, _ in pairs(entity_categories) do
            if category_name == recipe_category then
                is_compatible = true
                break
            end
        end
        if not is_compatible then
            return false, "Recipe '" .. params.recipe .. "' (category: " .. recipe_category .. 
                          ") is not compatible with entity"
        end
    end
    
    return true
end

--- Validate overwrite permission
--- @param params table
--- @return boolean, string|nil
local function validate_overwrite_permission(params)
    if not params.position or type(params.position.x) ~= "number" or type(params.position.y) ~= "number" then
        return true -- Let other validators handle missing parameters
    end
    
    local entity_name = params.entity_name
    if not entity_name then
        return true -- Let other validators handle missing parameters
    end
    
    local position = { x = params.position.x, y = params.position.y }
    local entity = game.surfaces[1].find_entity(entity_name, position)
    if not entity or not entity.valid then
        return true -- Let validate_entity_exists handle this
    end
    
    -- Only check overwrite if recipe is being set (not cleared)
    if not params.recipe then
        return true
    end
    
    local current_recipe = entity.get_recipe()
    local current_recipe_name = current_recipe and current_recipe.name or nil
    
    -- If entity has a recipe and overwrite is not allowed
    if current_recipe_name and not params.overwrite then
        return false, "Entity already has recipe '" .. current_recipe_name .. "'. Set overwrite=true to replace it."
    end
    
    return true
end

return { validate_entity_supports_recipes, validate_recipe_compatibility, validate_overwrite_permission }
