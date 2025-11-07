local GameState = require("GameState")

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

--- Validate recipe exists in prototypes
--- @param params table
--- @return boolean, string|nil
local function validate_recipe_exists(params)
    if not params.recipe then return true end  -- Let other validators handle missing recipe
    
    local recipe_proto = (prototypes and prototypes.recipe and prototypes.recipe[params.recipe])
    if not recipe_proto then
        error("Unknown recipe: " .. tostring(params.recipe))
    end
    
    return true
end

--- Validate agent has crafting to cancel (either tracking entry or queue has items)
--- @param params table
--- @return boolean, string|nil
local function validate_has_crafting(params)
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
    
    -- Check if there's a tracking entry
    storage.craft_in_progress = storage.craft_in_progress or {}
    local tracking = storage.craft_in_progress[params.agent_id]
    
    -- Check if queue has items
    local queue_size = agent.crafting_queue_size or 0
    
    -- Must have either tracking OR queue items
    if not tracking and queue_size == 0 then
        return false, string.format("Agent %d has no crafting to cancel (no tracking entry and queue is empty)", 
            params.agent_id)
    end
    
    return true
end

--- Validate recipe matches tracking (if tracking exists)
--- @param params table
--- @return boolean, string|nil
local function validate_recipe_matches_tracking(params)
    if not params.agent_id or not params.recipe then
        return true  -- Let other validators handle missing params
    end
    
    storage.craft_in_progress = storage.craft_in_progress or {}
    local tracking = storage.craft_in_progress[params.agent_id]
    
    if not tracking then
        return true  -- No tracking entry, skip this validation
    end
    
    if tracking.recipe ~= params.recipe then
        return false, string.format("Recipe '%s' does not match tracked recipe '%s' for agent %d", 
            params.recipe, tracking.recipe, params.agent_id)
    end
    
    return true
end

return { 
    validate_params, 
    validate_recipe_exists, 
    validate_has_crafting, 
    validate_recipe_matches_tracking 
}

