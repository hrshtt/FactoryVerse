local ValidatorRegistry = require("core.action.ValidatorRegistry")
local GameState = require("core.game_state.GameState")

local validator_registry = ValidatorRegistry:new()

--- Validate that entity is minable
--- @param params table
--- @return boolean, string|nil
local function validate_entity_minable(params)
    if not params.unit_number then
        return true -- Let other validators handle missing unit_number
    end
    
    local entity = game.get_entity_by_unit_number(params.unit_number)
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
    if not params.agent_id or not params.unit_number then
        return true -- Skip if parameters not provided
    end
    
    local entity = game.get_entity_by_unit_number(params.unit_number)
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
    local reachable = walk_helper:is_reachable(agent, {x = entity.position.x, y = entity.position.y})
    if not reachable then
        return false, "Agent cannot reach entity"
    end
    
    return true
end

--- Validate that agent has sufficient inventory space
--- @param params table
--- @return boolean, string|nil
local function validate_agent_inventory_space(params)
    if not params.agent_id or not params.unit_number then
        return true -- Skip if parameters not provided
    end
    
    local entity = game.get_entity_by_unit_number(params.unit_number)
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
