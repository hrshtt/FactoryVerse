--- factorio_verse/game_state/GameContext.lua
--- GameContext: Pure resolution functions for converting parameter references to game objects.
--- No state, no caching - just resolution logic.

local GameContext = {}

--- Resolve agent LuaEntity from agent_id
--- @param params table - must contain agent_id
--- @param game_state GameState - game state instance
--- @return LuaEntity agent character entity
function GameContext.resolve_agent(params, game_state)
    local agent = game_state.agent:get_agent(params.agent_id)
    if not agent or not agent.valid then
        error("GameContext: Agent not found or invalid: " .. tostring(params.agent_id))
    end
    return agent
end

--- Resolve entity LuaEntity and prototype
--- @param params table - must contain entity_name, optional position
--- @param agent LuaEntity - agent character (for range checking)
--- @return LuaEntity entity, table prototype
function GameContext.resolve_entity(params, agent)
    local entity_name = params.entity_name
    local surface = game.surfaces[1]
    local agent_pos = agent.position
    local build_distance = agent.build_distance or 10
    
    -- Validate prototype exists
    local proto = prototypes.entity[entity_name]
    if not proto then
        error("GameContext: Unknown entity prototype: " .. entity_name)
    end
    
    local entity = nil
    
    -- If position provided, try exact lookup
    if params.position and type(params.position.x) == "number" and type(params.position.y) == "number" then
        entity = surface.find_entity(entity_name, params.position)
        if entity and entity.valid then
            -- Verify within build_distance
            local dx = entity.position.x - agent_pos.x
            local dy = entity.position.y - agent_pos.y
            local dist_sq = dx * dx + dy * dy
            if dist_sq > build_distance * build_distance then
                error("GameContext: Entity at position out of range (distance: " .. 
                      math.sqrt(dist_sq) .. ", max: " .. build_distance .. ")")
            end
            return entity, proto
        end
    end
    
    -- No position or exact lookup failed - search by radius
    local entities = surface.find_entities_filtered({
        position = agent_pos,
        radius = build_distance,
        name = entity_name
    })
    
    -- Filter valid entities
    local valid_entities = {}
    for _, e in ipairs(entities) do
        if e and e.valid then
            table.insert(valid_entities, e)
        end
    end
    
    if #valid_entities == 0 then
        error("GameContext: Entity '" .. entity_name .. "' not found within build_distance (" .. 
              build_distance .. ") of agent")
    elseif #valid_entities > 1 then
        error("GameContext: Multiple entities '" .. entity_name .. "' found within build_distance. " ..
              "Provide position parameter to specify which entity.")
    end
    
    return valid_entities[1], proto
end

--- Resolve recipe prototype (force-specific)
--- @param params table - must contain recipe_name
--- @param agent LuaEntity - agent character (for force access)
--- @return table recipe prototype
function GameContext.resolve_recipe(params, agent)
    local recipe_name = params.recipe_name
    local recipe = agent.force.recipes[recipe_name]
    if not recipe then
        error("GameContext: Unknown or unavailable recipe for force: " .. recipe_name)
    end
    return recipe
end

--- Resolve technology prototype (force-specific)
--- @param params table - must contain tech_name
--- @param agent LuaEntity - agent character (for force access)
--- @return table technology prototype
function GameContext.resolve_technology(params, agent)
    local tech_name = params.tech_name
    local tech = agent.force.technologies[tech_name]
    if not tech then
        error("GameContext: Unknown or unavailable technology for force: " .. tech_name)
    end
    return tech
end

--- Resolve inventory from entity
--- @param entity LuaEntity - entity to get inventory from
--- @param inventory_index number - defines.inventory constant (e.g., defines.inventory.chest)
--- @return LuaInventory inventory
function GameContext.resolve_inventory(entity, inventory_index)
    local inv = entity.get_inventory(inventory_index)
    if not inv then
        error("GameContext: Entity does not have inventory at index " .. tostring(inventory_index))
    end
    return inv
end

return GameContext

