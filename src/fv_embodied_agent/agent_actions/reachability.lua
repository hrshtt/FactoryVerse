--- Agent reachability action methods
--- Methods operate directly on Agent instances (self)
--- These methods are mixed into the Agent class at module level
---
--- Provides on-demand reachability queries with full entity data.
--- Used by Python reachable_snapshot() context manager.

local serialize = require("utils.serialize")
local utils = require("utils.utils")

local ReachabilityActions = {}

-- Module-local reverse lookup: defines.entity_status value -> lower_snake
-- name (e.g. NO_POWER -> "no_power"). Built once at require time (defines
-- is available at require time in control stage) — mirrors the existing
-- direction/direction_name pattern. Deliberately lower_snake (NOT hyphenated
-- like utils.status_to_name/direction_to_name) so it round-trips through
-- EntityStatus.to_lua_name()/from_lua_name() in factorio_types.py (C5:
-- engine names are lower_snake).
local ENTITY_STATUS_NAMES = {}
for status_name, status_value in pairs(defines.entity_status or {}) do
    ENTITY_STATUS_NAMES[status_value] = string.lower(status_name)
end

-- ============================================================================
-- HELPERS
-- ============================================================================

--- Generate position key for reachability lookup
--- @param x number X coordinate
--- @param y number Y coordinate
--- @return string Position key in format "x,y" (1 decimal precision)
local function position_key(x, y)
    return string.format("%.1f,%.1f", x, y)
end

--- Build an entity-boundary search area around the character.
--- Unlike a position+radius filter, an area filter includes entities whose
--- collision boxes intersect the area even when their centers fall outside it.
--- @param position MapPosition
--- @param reach number
--- @return BoundingBox
local function reach_area(position, reach)
    return {
        {position.x - reach, position.y - reach},
        {position.x + reach, position.y + reach},
    }
end

--- Get inventory contents as a simple table
--- @param entity LuaEntity
--- @param inventory_type defines.inventory
--- @return table|nil Contents {item_name = count, ...}
local function get_inventory_contents(entity, inventory_type)
    local inventory = entity.get_inventory(inventory_type)
    if not inventory then
        return nil
    end
    local contents = inventory.get_contents()
    -- Convert to simple table (contents is LuaItemStack[])
    local result = {}
    for _, item in pairs(contents) do
        result[item.name] = (result[item.name] or 0) + item.count
    end
    return result
end

--- Get fuel count from entity
--- @param entity LuaEntity
--- @return number Fuel count (0 if no fuel inventory)
local function get_fuel_count(entity)
    local fuel_inv = entity.get_inventory(defines.inventory.fuel)
    if not fuel_inv then
        return 0
    end
    local count = 0
    for i = 1, #fuel_inv do
        local stack = fuel_inv[i]
        if stack and stack.valid_for_read then
            count = count + stack.count
        end
    end
    return count
end

--- Serialize entity to rich data structure
--- @param entity LuaEntity
--- @return table|nil Entity data with volatile state, or nil if invalid
local function serialize_entity_full(entity)
    if not (entity and entity.valid) then
        return nil
    end
    
    local data = {
        name = entity.name,
        type = entity.type,
        position = { x = entity.position.x, y = entity.position.y },
        position_key = position_key(entity.position.x, entity.position.y),
    }
    
    -- Add direction if available (required for entities with directional outputs like mining drills, inserters)
    if entity.direction ~= nil then
        data.direction = entity.direction
        data.direction_name = utils.direction_to_name(entity.direction)
    end
    
    -- Add status if available (status_name mirrors direction/direction_name)
    if entity.status ~= nil then
        data.status = entity.status
        data.status_name = ENTITY_STATUS_NAMES[entity.status]
    end
    
    -- Add recipe if applicable (assemblers, furnaces, rocket silos)
    -- Only call get_recipe() on entity types that actually support it
    -- According to Factorio API: assembling-machine, furnace, rocket-silo
    local is_crafter = (entity.type == "assembling-machine" or 
                        entity.type == "furnace" or 
                        entity.type == "rocket-silo")
    
    if is_crafter then
        local recipe = entity.get_recipe()
        if recipe then
            data.recipe = recipe.name
        end
    end
    
    -- Add fuel count if has fuel inventory
    local fuel_inv = entity.get_inventory(defines.inventory.fuel)
    if fuel_inv then
        data.fuel_count = get_fuel_count(entity)
    end
    
    -- Add input/output contents for machines
    -- Factorio 2.0+: Use crafter_input/crafter_output for all crafting machines
    if entity.type == "assembling-machine" or entity.type == "furnace" or 
       entity.type == "chemical-plant" or entity.type == "oil-refinery" then
        data.input_contents = get_inventory_contents(entity, defines.inventory.crafter_input) or {}
        data.output_contents = get_inventory_contents(entity, defines.inventory.crafter_output) or {}
    end
    
    -- Add chest contents
    if entity.type == "container" or entity.type == "logistic-container" then
        data.contents = get_inventory_contents(entity, defines.inventory.chest) or {}
    end
    
    -- Add inserter held item
    if entity.type == "inserter" then
        local held = entity.held_stack
        if held and held.valid_for_read then
            data.held_item = { name = held.name, count = held.count }
        end
    end
    
    return data
end

--- Serialize resource to data structure
--- @param entity LuaEntity
--- @return table|nil Resource data, or nil if invalid
local function serialize_resource(entity)
    if not (entity and entity.valid) then
        return nil
    end
    
    local data = {
        name = entity.name,
        type = entity.type,
        position = { x = entity.position.x, y = entity.position.y },
        position_key = position_key(entity.position.x, entity.position.y),
    }
    
    -- Add amount for resources (only resource type entities have amount property)
    if entity.type == "resource" and entity.amount then
        data.amount = entity.amount
    end
    
    -- Add mineable products
    if entity.prototype and entity.prototype.mineable_properties then
        data.products = entity.prototype.mineable_properties.products
    end
    
    return data
end

-- ============================================================================
-- REACHABILITY QUERIES
-- ============================================================================

--- Get full reachability snapshot with entity data
--- Returns complete volatile state for all reachable entities/resources
--- Used by Python reachable_snapshot() context manager
--- @param attach_ghosts boolean|nil Whether to include ghosts in response (default: true)
--- @return table Full snapshot with entity data arrays
function ReachabilityActions.get_reachable(self, attach_ghosts)
    -- Default attach_ghosts to true
    if attach_ghosts == nil then
        attach_ghosts = true
    end
    
    -- Skip if agent entity is invalid
    if not (self.character and self.character.valid) then
        local result = {
            entities = {},
            resources = {},
            agent_position = nil,
            tick = game.tick,
        }
        if attach_ghosts then
            result.ghosts = {}
        end
        return result
    end
    
    local position = self.character.position
    local surface = self.character.surface or game.surfaces[1]
    
    local entities_data = {}
    local resources_data = {}
    local ghosts_data = {}
    
    -- Find resources within resource_reach_distance
    local resource_reach = self.character.resource_reach_distance
    
    -- Resources (ore patches)
    local resources = surface.find_entities_filtered({
        area = reach_area(position, resource_reach),
        type = "resource"
    })
    for _, resource in ipairs(resources) do
        if self.character.can_reach_entity(resource) then
            local data = serialize_resource(resource)
            if data then
                table.insert(resources_data, data)
            end
        end
    end
    
    -- Trees
    local trees = surface.find_entities_filtered({
        area = reach_area(position, resource_reach),
        type = "tree"
    })
    for _, tree in ipairs(trees) do
        if self.character.can_reach_entity(tree) then
            local data = serialize_resource(tree)
            if data then
                table.insert(resources_data, data)
            end
        end
    end
    
    -- Simple entities (rocks)
    local rocks = surface.find_entities_filtered({
        area = reach_area(position, resource_reach),
        type = "simple-entity"
    })
    for _, rock in ipairs(rocks) do
        if self.character.can_reach_entity(rock) then
            local data = serialize_resource(rock)
            if data then
                table.insert(resources_data, data)
            end
        end
    end
    
    -- Find other entities within build reach_distance
    local build_reach = self.character.reach_distance
    local other_entities = surface.find_entities_filtered({
        area = reach_area(position, build_reach)
    })
    
    for _, entity in ipairs(other_entities) do
        if entity and entity.valid
            and entity.type ~= "resource"
            and entity.type ~= "tree"
            and entity.type ~= "simple-entity"
            and entity.type ~= "entity-ghost"  -- Exclude ghosts from entities
            and entity ~= self.character then
            -- Exclude tree stumps and other tree-related corpses
            local is_tree_corpse = (entity.type == "corpse" and
                (string.find(entity.name, "stump") or
                    string.find(entity.name, "tree")))
            if not is_tree_corpse and self.character.can_reach_entity(entity) then
                local data = serialize_entity_full(entity)
                if data then
                    table.insert(entities_data, data)
                end
            end
        end
    end
    
    -- Find ghosts within build reach_distance (if requested)
    if attach_ghosts then
        local ghosts = surface.find_entities_filtered({
            position = position,
            radius = build_reach,
            type = "entity-ghost"
        })
        for _, ghost in ipairs(ghosts) do
            if ghost and ghost.valid then
                local data = serialize.serialize_ghost(ghost)
                if data then
                    table.insert(ghosts_data, data)
                end
            end
        end
    end
    
    local result = {
        entities = entities_data,
        resources = resources_data,
        agent_position = { x = position.x, y = position.y },
        tick = game.tick,
    }
    
    if attach_ghosts then
        result.ghosts = ghosts_data
    end
    
    return result
end

return ReachabilityActions
