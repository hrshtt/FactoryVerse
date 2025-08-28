local ValidatorRegistry = require("core.action.ValidatorRegistry")
local GameState = require("core.game_state.GameState")

local validator_registry = ValidatorRegistry:new()

local function validate_params(params)
    if type(params) ~= "table" then
        return false, "params must be a table"
    end

    if type(params.agent_id) ~= "number" then
        return false, "agent_id must be a number"
    end

    if type(params.name) ~= "string" or params.name == "" then
        return false, "name must be a non-empty string"
    end

    if type(params.position) ~= "table" or type(params.position.x) ~= "number" or type(params.position.y) ~= "number" then
        return false, "position must be a table with numeric x and y"
    end

    return true
end

local function can_place_at_location(params)
    local gs = GameState:new()
    local surface = gs.surface
    if not surface then
        return false, "no surface available"
    end

    local direction = params.direction
    if type(direction) == "string" and GameState.aliases and GameState.aliases.direction then
        direction = GameState.aliases.direction[direction]
    end

    local can_place = surface.can_place_entity{
        name = params.name,
        position = params.position,
        direction = direction,
        force = params.force or (gs.agent:get_agent(params.agent_id) and gs.agent:get_agent(params.agent_id).force) or nil
    }

    if not can_place then
        return false, "cannot place entity at position"
    end
    return true
end

local function validate_item_in_inventory(params)
    local gs = GameState:new()
    local has_item = gs.agent:check_item_in_inventory(params.agent_id, params.item_name)
    if not has_item then
        return false, "agent does not have item in inventory"
    end
    return true
end

validator_registry:register("entity.place", validate_params)
validator_registry:register("entity.place", can_place_at_location)
validator_registry:register("entity.place", validate_item_in_inventory)

return validator_registry


