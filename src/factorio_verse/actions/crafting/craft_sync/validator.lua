local GameState = require("core.game_state.GameState")

local function is_hand_craftable(recipe_proto)
    if not recipe_proto then return false end
    local cat = recipe_proto.category or "crafting"
    return cat == "crafting" or cat == "advanced-crafting"
end

local function validate_params(params)
    if type(params) ~= "table" then return false, "params must be a table" end
    if type(params.agent_id) ~= "number" then return false, "agent_id must be number" end
    if type(params.recipe) ~= "string" or params.recipe == "" then return false, "recipe must be non-empty string" end
    if params.count ~= nil and (type(params.count) ~= "number" or params.count <= 0) then
        return false, "count must be positive number if provided"
    end
    local recipe_proto = (prototypes and prototypes.recipe and prototypes.recipe[params.recipe])
    if not recipe_proto then
        error("Unknown recipe: " .. tostring(params.recipe))
    end

    if not is_hand_craftable(recipe_proto) then
        error("Recipe not hand-craftable: " .. params.recipe)
    end

    -- Ensure recipe is enabled for the agent's force
    local gs = GameState:new()
    local agent = gs:agent():get_agent(params.agent_id)
    local force_recipe = agent.force and agent.force.recipes and agent.force.recipes[params.recipe] or nil
    if not (force_recipe and force_recipe.enabled) then
        error("Recipe not enabled for force: " .. params.recipe)
    end
    return true
end

return { validate_params }


