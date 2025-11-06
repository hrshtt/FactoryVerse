local GameState = require("GameState")
local helpers = require("game_state.agent.helpers")

--- Validate that the given (x, y) is a resource tile of the correct type
--- @param params table
--- @return boolean
local function validate_resource_tile(params)
    local resource_name = params.resource_name
    -- if not resource_name then
    --     error("Missing required param: resource_name")
    -- end
    -- if not params.x or not params.y then
    --     error("Missing required params: x and y")
    -- end

    local surface = game.surfaces[1]

    local tile_entities = surface.find_entities_filtered{
        area = {{params.x, params.y}, {params.x + 1, params.y + 1}},
        type = "resource"
    }

    local found_resource = nil
    for _, ent in ipairs(tile_entities) do
        if ent.name == resource_name then
            found_resource = ent
            break
        end
    end

    if not found_resource then
        error(string.format("No resource tile of type '%s' at (%d, %d)", resource_name, params.x, params.y))
    end

    return true
end

--- Validate that the agent can reach the resource (only if walk_if_unreachable is false)
--- @param params table
--- @return boolean, string|nil
local function validate_resource_reachable(params)
    -- Skip validation if walk_if_unreachable is true (agent will walk to resource)
    -- Note: walk_if_unreachable defaults to false, so nil or false means validate
    if params.walk_if_unreachable == true then
        return true
    end

    -- Skip if agent_id not provided
    if not params.agent_id then
        return true
    end

    -- Skip if position not provided
    if not params.x or not params.y or not params.resource_name then
        return true -- Let other validators handle this
    end

    local gs = GameState:new()
    local agent = gs.agent:get_agent(params.agent_id)
    if not agent or not agent.valid then
        return true -- Let other validators handle agent validation
    end

    local surface = game.surfaces[1]
    local resource = helpers.find_resource_entity(surface, {x = params.x, y = params.y}, params.resource_name)
    if not resource or not resource.valid then
        return true -- Let validate_resource_tile handle this
    end

    -- Check if agent can reach the resource using shared helper (same logic as action)
    local reachable = helpers.can_reach_entity(agent, resource, true)  -- true = use resource-specific reach
    
    if not reachable then
        return false, string.format("Agent %d cannot reach resource '%s' at (%d, %d). Set walk_if_unreachable=true to allow walking to resource.", params.agent_id, params.resource_name, params.x, params.y)
    end

    return true
end

return { validate_resource_tile, validate_resource_reachable }
