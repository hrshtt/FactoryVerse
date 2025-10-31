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

    if type(params.entity_name) ~= "string" or params.entity_name == "" then
        return false, "entity_name must be a non-empty string"
    end

    if type(params.position) ~= "table" or type(params.position.x) ~= "number" or type(params.position.y) ~= "number" then
        return false, "position must be a table with numeric x and y"
    end

    if params.orient_towards ~= nil then
        if type(params.orient_towards) ~= "table" then
            return false, "orient_towards must be a table if provided"
        end
        if params.orient_towards.entity_name ~= nil and type(params.orient_towards.entity_name) ~= "string" then
            return false, "orient_towards.entity_name must be a string if provided"
        end
        if params.orient_towards.position ~= nil then
            local pos = params.orient_towards.position
            if type(pos) ~= "table" or type(pos.x) ~= "number" or type(pos.y) ~= "number" then
                return false, "orient_towards.position must be {x:number,y:number}"
            end
        end
    end

    return true
end

local function can_place_at_location(params)
    local gs = GameState:new()
    local surface = game.surfaces[1]
    if not surface then
        return false, "no surface available"
    end

    local direction = params.direction
    if type(direction) == "string" and GameState.aliases and GameState.aliases.direction then
        direction = GameState.aliases.direction[direction]
    end

    local agent = gs:agent():get_agent(params.agent_id)
    local force = params.force or (agent and agent.force) or nil

    local can_place = surface.can_place_entity{
        name = params.entity_name,
        position = params.position,
        direction = direction,
        force = force
    }

    if not can_place then
        return false, "cannot place entity at position"
    end
    return true
end

local function validate_item_in_inventory(params)
    local gs = GameState:new()
    local ok = gs:agent():check_item_in_inventory(params.agent_id, params.entity_name)
    if ok ~= true then
        -- If ok is a GameStateError, extract its message
        local error_msg = "agent does not have required item in inventory"
        if type(ok) == "table" and ok.message then
            error_msg = error_msg .. " (" .. ok.message .. ")"
        end
        return false, error_msg
    end
    return true
end

validator_registry:register("entity.place", validate_params)
validator_registry:register("entity.place", can_place_at_location)
validator_registry:register("entity.place", validate_item_in_inventory)

return validator_registry


