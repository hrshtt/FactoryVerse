local Action = require("types.Action")

--- @class SetRecipeParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field position_x number X coordinate of the target entity
--- @field position_y number Y coordinate of the target entity
--- @field entity_name string Entity prototype name
--- @field recipe string|nil Recipe name to set (nil to clear recipe)
--- @field overwrite boolean|nil Whether to allow overwriting existing recipe
local SetRecipeParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    position_x = { type = "number", required = true },
    position_y = { type = "number", required = true },
    entity_name = { type = "string", required = true },
    recipe = { type = "string", required = false },
    overwrite = { type = "boolean", required = false, default = false }
})

--- @class SetRecipeAction : Action
local SetRecipeAction = Action:new("entity.set_recipe", SetRecipeParams)

--- @param params SetRecipeParams
--- @return table result Data about the recipe change
function SetRecipeAction:run(params)
    local p = self:_pre_run(params)
    ---@cast p SetRecipeParams

    local position = { x = p.position_x, y = p.position_y }
    local entity = game.surfaces[1].find_entity(p.entity_name, position)
    if not entity or not entity.valid then
        error("Entity not found or invalid")
    end

    -- Check if entity type supports recipes
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
        error("Entity type does not support recipes: " .. entity.type)
    end

    -- Get current recipe
    local current_recipe = entity.get_recipe()
    local current_recipe_name = current_recipe and current_recipe.name or nil

    -- Handle recipe clearing (nil)
    if not p.recipe then
        if current_recipe_name then
            entity.set_recipe(nil)
            return self:_post_run({
                position = position,
                entity_name = p.entity_name,
                entity_type = entity.type,
                previous_recipe = current_recipe_name,
                new_recipe = nil,
                action = "cleared",
                affected_positions = { { position = position, entity_name = p.entity_name, entity_type = entity.type } }
            }, p)
        else
            return self:_post_run({
                position = position,
                entity_name = p.entity_name,
                entity_type = entity.type,
                previous_recipe = nil,
                new_recipe = nil,
                action = "no_op",
                message = "Entity already has no recipe",
                affected_positions = { { position = position, entity_name = p.entity_name, entity_type = entity.type } }
            }, p)
        end
    end

    -- Validate recipe exists
    local recipe_proto = prototypes and prototypes.recipe and prototypes.recipe[p.recipe]
    if not recipe_proto then
        error("Recipe not found: " .. p.recipe)
    end

    -- Check if recipe is compatible with entity
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
            local categories_str = ""
            for category_name, _ in pairs(entity_categories) do
                if categories_str ~= "" then categories_str = categories_str .. ", " end
                categories_str = categories_str .. category_name
            end
            error("Recipe '" .. p.recipe .. "' (category: " .. recipe_category .. 
                  ") is not compatible with entity (categories: " .. categories_str .. ")")
        end
    end

    -- Check if recipe is already set
    if current_recipe_name == p.recipe then
        return self:_post_run({
            position = position,
            entity_name = p.entity_name,
            entity_type = entity.type,
            previous_recipe = current_recipe_name,
            new_recipe = p.recipe,
            action = "no_op",
            message = "Entity already has this recipe",
            affected_positions = { { position = position, entity_name = p.entity_name, entity_type = entity.type } }
        }, p)
    end

    -- Check if overwrite is needed
    if current_recipe_name and not p.overwrite then
        error("Entity already has recipe '" .. current_recipe_name .. "'. Set overwrite=true to replace it.")
    end

    -- Set the recipe
    local success = entity.set_recipe(p.recipe)
    if not success then
        error("Failed to set recipe: " .. p.recipe)
    end

    local result = {
        position = position,
        entity_name = p.entity_name,
        entity_type = entity.type,
        previous_recipe = current_recipe_name,
        new_recipe = p.recipe,
        action = "set",
        affected_positions = { { position = position, entity_name = p.entity_name, entity_type = entity.type } }
    }
    
    return self:_post_run(result, p)
end

return { action = SetRecipeAction, params = SetRecipeParams }
