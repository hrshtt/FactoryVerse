local ValidatorRegistry = require("core.action.ValidatorRegistry")
local GameState = require("core.game_state.GameState")

local validator_registry = ValidatorRegistry:new()

--- Validate that entity is minable
--- @param params table
--- @return boolean, string|nil
local function validate_entity_minable(params)
    -- Support both position_x/position_y and position table
    local pos_x = params.position_x or (params.position and params.position.x)
    local pos_y = params.position_y or (params.position and params.position.y)
    local entity_name = params.entity_name
    
    if not entity_name or type(pos_x) ~= "number" or type(pos_y) ~= "number" then
        return true -- Let other validators handle missing parameters
    end
    
    local position = { x = pos_x, y = pos_y }
    local entity = game.surfaces[1].find_entity(entity_name, position)
    if not entity or not entity.valid then
        return true -- Let validate_entity_exists handle this
    end
    
    if not entity.minable then
        return false, "Entity is not minable"
    end
    
    return true
end

--- Validate that agent can reach the entity
--- @param params table
--- @return boolean, string|nil
local function validate_agent_reachable(params)
    -- Support both position_x/position_y and position table
    local pos_x = params.position_x or (params.position and params.position.x)
    local pos_y = params.position_y or (params.position and params.position.y)
    
    if not params.agent_id or not params.entity_name or type(pos_x) ~= "number" or type(pos_y) ~= "number" then
        return true -- Skip if parameters not provided
    end
    
    local position = { x = pos_x, y = pos_y }
    local entity = game.surfaces[1].find_entity(params.entity_name, position)
    if not entity or not entity.valid then
        return true -- Let validate_entity_exists handle this
    end
    
    local gs = GameState:new()
    local agent = gs:agent_state():get_agent(params.agent_id)
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

--- Validate that agent has sufficient inventory space
--- @param params table
--- @return boolean, string|nil
local function validate_agent_inventory_space(params)
    -- Support both position_x/position_y and position table
    local pos_x = params.position_x or (params.position and params.position.x)
    local pos_y = params.position_y or (params.position and params.position.y)
    
    if not params.agent_id or not params.entity_name or type(pos_x) ~= "number" or type(pos_y) ~= "number" then
        return true -- Skip if parameters not provided
    end
    
    local position = { x = pos_x, y = pos_y }
    local entity = game.surfaces[1].find_entity(params.entity_name, position)
    if not entity or not entity.valid then
        return true -- Let validate_entity_exists handle this
    end
    
    local gs = GameState:new()
    local agent = gs:agent_state():get_agent(params.agent_id)
    if not agent then
        return true -- Let other validators handle agent validation
    end
    
    local agent_inventory = agent.get_inventory(defines.inventory.character_main)
    if not agent_inventory then
        return false, "Agent inventory not found"
    end
    
    -- Check if agent has space for the entity itself
    local can_insert_entity = agent_inventory.can_insert({name = entity.name, count = 1})
    if can_insert_entity < 1 then
        return false, "Agent inventory insufficient space for entity: " .. entity.name
    end
    
    return true
end

-- Register validators for entity.pickup
validator_registry:register("entity.pickup", validate_entity_minable)
validator_registry:register("entity.pickup", validate_agent_reachable)
validator_registry:register("entity.pickup", validate_agent_inventory_space)

return validator_registry
