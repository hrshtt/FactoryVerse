local GameState = require("GameState")

--- Validate that entity exists and is valid
--- @param params table - must include position table
--- @return boolean, string|nil
local function validate_entity_exists(params)
    if not params.position or type(params.position.x) ~= "number" or type(params.position.y) ~= "number" then
        return true -- Skip if position not provided (let other validators handle it)
    end
    
    -- Support optional entity_name parameter for more precise lookup
    local entity_name = params.entity_name
    
    local position = { x = params.position.x, y = params.position.y }
    local entity
    
    if entity_name then
        entity = game.surfaces[1].find_entity(entity_name, position)
    else
        -- Find any entity at position (less precise, fallback)
        local entities = game.surfaces[1].find_entities_filtered({ position = position, limit = 1 })
        entity = entities and entities[1] or nil
    end
    
    if not entity or not entity.valid then
        log("DEBUG: Entity at position {" .. position.x .. "," .. position.y .. "} not found or invalid")
        return false, "Entity not found or invalid"
    end
    
    return true
end

--- Validate that agent can reach the entity (optional check)
--- @param params table - must include position and agent_id
--- @return boolean, string|nil
local function validate_entity_reachable(params)
    if not params.agent_id or not params.position or type(params.position.x) ~= "number" or type(params.position.y) ~= "number" then
        return true -- Skip if parameters not provided
    end
    
    local position = { x = params.position.x, y = params.position.y }
    local entity_name = params.entity_name
    local entity
    
    if entity_name then
        entity = game.surfaces[1].find_entity(entity_name, position)
    else
        local entities = game.surfaces[1].find_entities_filtered({ position = position, limit = 1 })
        entity = entities and entities[1] or nil
    end
    
    if not entity or not entity.valid then
        return true -- Let validate_entity_exists handle this
    end
    
    local gs = GameState:new()
    local agent = gs.agent:get_agent(params.agent_id)
    if not agent then
        return true -- Let other validators handle agent validation
    end
    
    -- Use WalkHelper for reachability check
    local walk_helper = require("actions.agent.walk.helper")
    local reachable = walk_helper:is_reachable(agent, position)
    if not reachable then
        return false, "Agent cannot reach entity"
    end
    
    return true
end

-- Return validators for all entity actions
return { validate_entity_exists }
-- Note: reachability check is optional and can be enabled per action if needed
-- return { validate_entity_exists, validate_entity_reachable }
