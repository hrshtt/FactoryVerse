local GameState = require("GameState")

--- Validate that entity is minable
--- @param params table
--- @return boolean, string|nil
local function validate_entity_minable(params)
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
    
    if not entity.minable then
        return false, "Entity is not minable"
    end
    
    return true
end

--- Validate that agent has sufficient inventory space
--- @param params table
--- @return boolean, string|nil
local function validate_agent_inventory_space(params)
    if not params.agent_id or not params.entity_name or not params.position or type(params.position.x) ~= "number" or type(params.position.y) ~= "number" then
        return true -- Skip if parameters not provided
    end
    
    local position = { x = params.position.x, y = params.position.y }
    local entity = game.surfaces[1].find_entity(params.entity_name, position)
    if not entity or not entity.valid then
        return true -- Let validate_entity_exists handle this
    end
    
    local gs = GameState:new()
    local agent = gs.agent:get_agent(params.agent_id)
    if not agent then
        return true -- Let other validators handle agent validation
    end
    
    local agent_inventory = agent.get_inventory(defines.inventory.character_main)
    if not agent_inventory then
        return false, "Agent inventory not found"
    end
    
    -- Check if agent has space for the entity itself
    local can_insert_entity = agent_inventory.can_insert({name = entity.name, count = 1})
    if not can_insert_entity then
        return false, "Agent inventory insufficient space for entity: " .. entity.name
    end
    
    return true
end

-- Return validators for entity.pickup
return { validate_entity_minable, validate_agent_inventory_space }
