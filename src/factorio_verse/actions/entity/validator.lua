local ValidatorRegistry = require("core.action.ValidatorRegistry")
local GameState = require("core.game_state.GameState")

local validator_registry = ValidatorRegistry:new()

--- Validate that entity exists and is valid
--- @param params table
--- @return boolean, string|nil
local function validate_entity_exists(params)
    if type(params.unit_number) ~= "number" then
        return false, "unit_number must be a number"
    end
    
    local entity = game.get_entity_by_unit_number(params.unit_number)
    if not entity or not entity.valid then
        return false, "Entity not found or invalid"
    end
    
    return true
end

--- Validate that agent can reach the entity (optional check)
--- @param params table
--- @return boolean, string|nil
local function validate_entity_reachable(params)
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

-- Register validators for all entity actions
validator_registry:register("entity.*", validate_entity_exists)
-- Note: reachability check is optional and can be enabled per action if needed
-- validator_registry:register("entity.*", validate_entity_reachable)

return validator_registry
