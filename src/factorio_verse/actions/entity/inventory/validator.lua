local GameState = require("GameState")

--- Find entity by name within agent's build_distance radius
--- @param params table - must include agent_id, entity_name, optional position
--- @return boolean, string|nil
local function validate_entity_in_range(params)
    if not params.agent_id or not params.entity_name then
        return true -- Let other validators handle missing parameters
    end
    
    local gs = GameState:new()
    local agent = gs.agent:get_agent(params.agent_id)
    if not agent or not agent.valid then
        return true -- Let other validators handle agent validation
    end
    
    local agent_pos = agent.position
    local build_distance = agent.build_distance or 10
    local entity_name = params.entity_name
    local surface = game.surfaces[1]
    
    -- Search for entities within build_distance radius
    local search_filter = {
        position = agent_pos,
        radius = build_distance,
        name = entity_name
    }
    
    local entities = surface.find_entities_filtered(search_filter)
    
    -- Filter to only valid entities
    local valid_entities = {}
    for _, entity in ipairs(entities) do
        if entity and entity.valid then
            table.insert(valid_entities, entity)
        end
    end
    
    -- If position provided, try to find exact match first
    if params.position and type(params.position.x) == "number" and type(params.position.y) == "number" then
        local target_pos = { x = params.position.x, y = params.position.y }
        local exact_entity = surface.find_entity(entity_name, target_pos)
        if exact_entity and exact_entity.valid then
            -- Verify it's within build_distance
            local dx = exact_entity.position.x - agent_pos.x
            local dy = exact_entity.position.y - agent_pos.y
            local dist_sq = dx * dx + dy * dy
            if dist_sq <= build_distance * build_distance then
                return true -- Found exact match within range
            end
        end
    end
    
    -- No entities found
    if #valid_entities == 0 then
        return false, "Entity '" .. entity_name .. "' not found within build_distance (" .. 
                      build_distance .. ") of agent. Provide position to search at specific location."
    end
    
    -- Multiple entities found without position
    if #valid_entities > 1 and not params.position then
        return false, "Multiple entities '" .. entity_name .. "' found within build_distance. " ..
                      "Provide position parameter to specify which entity to use."
    end
    
    return true
end

return { validate_entity_in_range }
