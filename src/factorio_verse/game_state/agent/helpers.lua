--- Shared helper functions for agent activities (walking, mining, etc.)
--- These utilities are used by both walking and mining modules

local math = math
local ipairs = ipairs

local M = {}

-- ============================================================================
-- AGENT CONTROL HELPERS
-- ============================================================================

--- Get the control entity (character) for an agent
--- @param agent_id number
--- @return LuaEntity|nil
function M.get_control_for_agent(agent_id)
    local agents = storage.agent_characters
    if agents and agents[agent_id] and agents[agent_id].valid then
        return agents[agent_id]
    end
    return nil
end

-- ============================================================================
-- DISTANCE AND GEOMETRY HELPERS
-- ============================================================================

--- Calculate squared distance between two positions
--- @param a {x:number, y:number}
--- @param b {x:number, y:number}
--- @return number
function M.dist_sq(a, b)
    local dx, dy = (a.x - b.x), (a.y - b.y)
    return dx*dx + dy*dy
end

--- Check if control can reach entity
--- @param control LuaEntity
--- @param entity LuaEntity
--- @return boolean
--- @diagnostic disable: undefined-field
function M.can_reach_entity(control, entity)
    if not (control and control.valid and entity and entity.valid) then return false end
    local proto = control.prototype
    -- character_reach_distance may not exist on all prototypes, use safe access with fallback
    local reach = 0.5  -- default reach distance
    if proto then
        -- Use pcall to safely access prototype field (may not exist on all entity types)
        local ok, reach_value = pcall(function() 
            return proto.character_reach_distance 
        end)
        if ok and reach_value then
            reach = reach_value
        end
    end
    -- Convert positions to {x, y} format if needed (handle MapPosition array format)
    local control_pos = control.position
    local entity_pos = entity.position
    local cp = { x = control_pos.x or control_pos[1] or 0, y = control_pos.y or control_pos[2] or 0 }
    local ep = { x = entity_pos.x or entity_pos[1] or 0, y = entity_pos.y or entity_pos[2] or 0 }
    local dist_sq_val = M.dist_sq(cp, ep)
    return dist_sq_val <= (reach * reach)
end
--- @diagnostic enable: undefined-field

-- ============================================================================
-- RESOURCE HELPERS
-- ============================================================================

--- Find resource entity at position
--- @param surface LuaSurface
--- @param position {x:number, y:number}
--- @param resource_name string
--- @return LuaEntity|nil
function M.find_resource_entity(surface, position, resource_name)
    if not (surface and position and resource_name) then return nil end
    -- Try exact entity-at-position lookup first
    local ok_ent, ent = pcall(function() return surface.find_entity(resource_name, position) end)
    if ok_ent and ent and ent.valid and ent.type == "resource" then
        return ent
    end
    -- Fallback: search in a reasonable radius and pick the nearest
    local search_radius = 2.5
    local entities = surface.find_entities_filtered{
        position = position,
        radius = search_radius,
        type = "resource",
        name = resource_name
    }
    if not entities or #entities == 0 then return nil end
    local px, py = position.x, position.y
    local best, best_d2 = nil, math.huge
    for _, e in ipairs(entities) do
        if e and e.valid then
            local dx, dy = e.position.x - px, e.position.y - py
            local d2 = dx*dx + dy*dy
            if d2 < best_d2 then
                best, best_d2 = e, d2
            end
        end
    end
    return best
end

--- Get resource products from resource entity
--- @param resource LuaEntity
--- @return string[]|nil products
--- @return boolean requires_fluid
function M.get_resource_products(resource)
    if not (resource and resource.valid) then return nil, false end
    local ok_props, props = pcall(function() return resource.prototype and resource.prototype.mineable_properties end)
    if not ok_props or not props then return { resource.name }, false end
    local requires_fluid = (props.required_fluid and (props.fluid_amount or 0) > 0) or false
    local names = {}
    if props.products and type(props.products) == "table" then
        for _, prod in ipairs(props.products) do
            if prod and prod.name then table.insert(names, prod.name) end
        end
    elseif props.product then
        table.insert(names, props.product)
    end
    if #names == 0 then table.insert(names, resource.name) end
    return names, requires_fluid
end

-- ============================================================================
-- INVENTORY HELPERS
-- ============================================================================

--- Get total count of items from a list of item names
--- @param actor LuaEntity|LuaPlayer|LuaControl
--- @param names string[]
--- @return number
function M.get_actor_items_total(actor, names)
    if not names or #names == 0 then return 0 end
    if not actor or not actor.valid then return 0 end
    local total = 0
    if actor.get_main_inventory then
        local inv = actor.get_main_inventory()
        if not inv then return 0 end
        local contents = inv.get_contents and inv.get_contents() or {}
        for _, n in ipairs(names) do total = total + (contents[n] or 0) end
        return total
    end
    if actor.get_inventory then
        local inv = actor.get_inventory(defines.inventory.character_main)
        if not inv then return 0 end
        local contents = inv.get_contents and inv.get_contents() or {}
        for _, n in ipairs(names) do total = total + (contents[n] or 0) end
        return total
    end
    return 0
end

--- Get count of a specific item
--- @param actor LuaEntity|LuaPlayer|LuaControl
--- @param name string
--- @return number
function M.get_actor_item_count(actor, name)
    if not (actor and actor.valid and name) then return 0 end
    if actor.get_main_inventory then
        local inv = actor.get_main_inventory()
        if not inv then return 0 end
        return (inv.get_item_count and inv.get_item_count(name)) or 0
    end
    if actor.get_inventory then
        local inv = actor.get_inventory(defines.inventory.character_main)
        if not inv then return 0 end
        return (inv.get_item_count and inv.get_item_count(name)) or 0
    end
    return 0
end

return M

