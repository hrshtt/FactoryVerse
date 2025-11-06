local GameState = require("GameState")

--- Validate that entity exists and is valid
--- @param params table - must include position_x, position_y or position table
--- @return boolean, string|nil
local function validate_entity_exists(params)
    -- Support both position_x/position_y and position table
    local pos_x = params.position_x or (params.position and params.position.x)
    local pos_y = params.position_y or (params.position and params.position.y)
    
    if type(pos_x) ~= "number" or type(pos_y) ~= "number" then
        return true -- Skip if position not provided (let other validators handle it)
    end
    
    -- Support optional entity_name parameter for more precise lookup
    local entity_name = params.entity_name
    
    local position = { x = pos_x, y = pos_y }
    local entity
    
    if entity_name then
        entity = game.surfaces[1].find_entity(entity_name, position)
    else
        -- Find any entity at position (less precise, fallback)
        local entities = game.surfaces[1].find_entities_filtered({ position = position, limit = 1 })
        entity = entities and entities[1] or nil
    end
    
    if not entity or not entity.valid then
        log("DEBUG: Entity at position {" .. pos_x .. "," .. pos_y .. "} not found or invalid")
        return false, "Entity not found or invalid"
    end
    
    return true
end

--- Validate that agent can reach the entity (optional check)
--- @param params table - must include position_x, position_y and agent_id
--- @return boolean, string|nil
local function validate_entity_reachable(params)
    -- Support both position_x/position_y and position table
    local pos_x = params.position_x or (params.position and params.position.x)
    local pos_y = params.position_y or (params.position and params.position.y)
    
    if not params.agent_id or type(pos_x) ~= "number" or type(pos_y) ~= "number" then
        return true -- Skip if parameters not provided
    end
    
    local position = { x = pos_x, y = pos_y }
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
    local agent = gs:agent():get_agent(params.agent_id)
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
