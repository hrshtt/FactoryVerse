local GameState = require("GameState")

--- Check if recipe is hand-craftable
--- @param recipe_proto table
--- @return boolean
local function is_hand_craftable(recipe_proto)
    if not recipe_proto then return false end
    local cat = recipe_proto.category or "crafting"
    return cat == "crafting" or cat == "advanced-crafting"
end

--- Validate basic parameters
--- @param params table
--- @return boolean, string|nil
local function validate_params(params)
    if type(params) ~= "table" then 
        return false, "params must be a table" 
    end
    if type(params.agent_id) ~= "number" then 
        return false, "agent_id must be number" 
    end
    if type(params.recipe) ~= "string" or params.recipe == "" then 
        return false, "recipe must be non-empty string" 
    end
    if params.count ~= nil and (type(params.count) ~= "number" or params.count <= 0) then
        return false, "count must be positive number if provided"
    end
    return true
end

--- Validate recipe exists and is hand-craftable
--- @param params table
--- @return boolean, string|nil
local function validate_recipe(params)
    if not params.recipe then return true end  -- Let other validators handle missing recipe
    
    local recipe_proto = (prototypes and prototypes.recipe and prototypes.recipe[params.recipe])
    if not recipe_proto then
        error("Unknown recipe: " .. tostring(params.recipe))
    end
    
    if not is_hand_craftable(recipe_proto) then
        error("Recipe not hand-craftable: " .. params.recipe .. " (category: " .. tostring(recipe_proto.category) .. ")")
    end
    
    -- Check for fluid ingredients (characters cannot hand-craft fluid recipes)
    for _, ing in ipairs(recipe_proto.ingredients or {}) do
        if ing.type == "fluid" then
            error("Recipe contains fluid ingredients: " .. params.recipe .. " (characters cannot hand-craft fluid recipes)")
        end
    end
    
    return true
end

--- Validate recipe is enabled for agent's force
--- @param params table
--- @return boolean, string|nil
local function validate_recipe_enabled(params)
    if not params.agent_id or not params.recipe then
        return true  -- Let other validators handle missing params
    end
    
    local gs = GameState:new()
    local agent = gs.agent:get_agent(params.agent_id)
    if not agent or not agent.valid then
        return true  -- Let other validators handle invalid agent
    end
    
    local force_recipe = agent.force and agent.force.recipes and agent.force.recipes[params.recipe] or nil
    if not (force_recipe and force_recipe.enabled) then
        error("Recipe not enabled for force: " .. params.recipe)
    end
    
    return true
end

--- Validate agent can craft the recipe (has ingredients)
--- @param params table
--- @return boolean, string|nil
local function validate_craftable(params)
    if not params.agent_id or not params.recipe then
        return true  -- Let other validators handle missing params
    end
    
    local gs = GameState:new()
    local agent = gs.agent:get_agent(params.agent_id)
    if not agent or not agent.valid then
        return true  -- Let other validators handle invalid agent
    end
    
    if agent.type ~= "character" then
        return true  -- Let other validators handle non-character
    end
    
    local recipe_proto = (prototypes and prototypes.recipe and prototypes.recipe[params.recipe])
    if not recipe_proto then
        return true  -- Let validate_recipe handle missing recipe
    end
    
    -- Use Factorio's built-in craftable count check
    local craftable_count = agent.get_craftable_count(recipe_proto)
    if craftable_count <= 0 then
        return false, "Cannot craft recipe: insufficient ingredients or recipe not available (craftable_count: " .. craftable_count .. ")"
    end
    
    return true
end

--- Validate crafting queue has space
--- @param params table
--- @return boolean, string|nil
local function validate_queue_space(params)
    if not params.agent_id then
        return true  -- Let other validators handle missing agent_id
    end
    
    local gs = GameState:new()
    local agent = gs.agent:get_agent(params.agent_id)
    if not agent or not agent.valid then
        return true  -- Let other validators handle invalid agent
    end
    
    if agent.type ~= "character" then
        return true  -- Let other validators handle non-character
    end
    
    -- Characters typically have max queue size of 3
    local max_queue_size = 3
    if agent.crafting_queue_size >= max_queue_size then
        return false, string.format("Crafting queue is full (size: %d, max: %d)", 
            agent.crafting_queue_size, max_queue_size)
    end
    
    return true
end

--- Validate no concurrent crafting job for this agent
--- Also cleans up stale tracking entries if crafting has completed
--- @param params table
--- @return boolean, string|nil
local function validate_no_concurrent_crafting(params)
    if not params.agent_id then
        return true  -- Let other validators handle missing agent_id
    end
    
    storage.craft_in_progress = storage.craft_in_progress or {}
    local tracking = storage.craft_in_progress[params.agent_id]
    
    if not tracking then
        return true  -- No tracking entry, allow crafting
    end
    
    -- Check if agent is still valid
    local gs = GameState:new()
    local agent = gs.agent:get_agent(params.agent_id)
    if not agent or not agent.valid or agent.type ~= "character" then
        -- Agent invalid, clean up stale entry
        storage.craft_in_progress[params.agent_id] = nil
        return true
    end
    
    -- Check if crafting is actually still in progress
    -- If queue size decreased from start, or queue is empty and progress is 0, crafting finished
    local current_queue_size = agent.crafting_queue_size or 0
    local start_queue_size = tracking.start_queue_size or 0
    
    -- If queue size decreased, crafting has completed (recipe removed from queue)
    if current_queue_size < start_queue_size then
        -- Crafting completed, clean up stale entry
        log(string.format("[craft_enqueue] Cleaning up completed craft tracking for agent %d (queue size: %d -> %d)", 
            params.agent_id, start_queue_size, current_queue_size))
        storage.craft_in_progress[params.agent_id] = nil
        return true
    end
    
    -- If queue is empty and no progress, crafting finished
    if current_queue_size == 0 and (agent.crafting_queue_progress or 0) == 0 then
        log(string.format("[craft_enqueue] Cleaning up completed craft tracking for agent %d (queue empty)", 
            params.agent_id))
        storage.craft_in_progress[params.agent_id] = nil
        return true
    end
    
    -- Crafting is still in progress
    local action_id = tracking.action_id or "unknown"
    return false, string.format("Agent %d is already crafting (action_id: %s). Wait for current craft to complete.", 
        params.agent_id, action_id)
end

return { 
    validate_params, 
    validate_recipe, 
    validate_recipe_enabled, 
    validate_craftable, 
    validate_queue_space, 
    validate_no_concurrent_crafting 
}

