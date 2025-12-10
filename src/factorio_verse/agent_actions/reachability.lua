--- Agent reachability action methods
--- Methods operate directly on Agent instances (self)
--- State is stored in self.reachable (entities, resources, dirty, last_updated_tick)
--- These methods are mixed into the Agent class at module level
---
--- Provides two modes:
--- 1. Position keys only (get_reachable) - for fast reachability checks
--- 2. Full entity data (get_reachable_full) - for rich snapshots with volatile state

local ReachabilityActions = {}

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
    
    -- Add status if available
    if entity.status then
        data.status = entity.status
    end
    
    -- Add recipe if applicable (assemblers, furnaces, chemical plants)
    local recipe = entity.get_recipe and entity.get_recipe()
    if recipe then
        data.recipe = recipe.name
    end
    
    -- Add fuel count if has fuel inventory
    local fuel_inv = entity.get_inventory(defines.inventory.fuel)
    if fuel_inv then
        data.fuel_count = get_fuel_count(entity)
    end
    
    -- Add input/output contents for machines
    if entity.type == "assembling-machine" or entity.type == "furnace" then
        data.input_contents = get_inventory_contents(entity, defines.inventory.assembling_machine_input)
            or get_inventory_contents(entity, defines.inventory.furnace_source)
            or {}
        data.output_contents = get_inventory_contents(entity, defines.inventory.assembling_machine_output)
            or get_inventory_contents(entity, defines.inventory.furnace_result)
            or {}
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
    
    -- Add amount for resources
    if entity.amount then
        data.amount = entity.amount
    end
    
    -- Add mineable products
    if entity.prototype and entity.prototype.mineable_properties then
        data.products = entity.prototype.mineable_properties.products
    end
    
    return data
end

--- Serialize ghost entity to data structure
--- @param ghost LuaEntity Ghost entity (type="entity-ghost")
--- @return table|nil Ghost data, or nil if invalid
local function serialize_ghost(ghost)
    if not (ghost and ghost.valid) then
        return nil
    end
    
    local data = {
        name = ghost.name,  -- "entity-ghost"
        type = ghost.type,  -- "entity-ghost"
        position = { x = ghost.position.x, y = ghost.position.y },
        position_key = position_key(ghost.position.x, ghost.position.y),
        ghost_name = ghost.ghost_name,  -- The entity this ghost represents
    }
    
    -- Add direction if available
    if ghost.direction then
        data.direction = ghost.direction
    end
    
    return data
end

-- ============================================================================
-- REACHABILITY PROCESSING
-- ============================================================================

--- Process reachability cache update
--- Called on each tick, only recomputes if dirty flag is set
--- Populates self.reachable.entities and self.reachable.resources with position keys
function ReachabilityActions.process_reachable(self)
    -- Skip if not dirty
    if not self.reachable.dirty then
        return
    end
    
    -- Skip if agent entity is invalid
    if not (self.character and self.character.valid) then
        return
    end
    
    local position = self.character.position
    local surface = self.character.surface or game.surfaces[1]
    
    -- Clear existing cache
    self.reachable.entities = {}
    self.reachable.resources = {}
    
    -- Find resources within resource_reach_distance
    local resource_reach = self.character.resource_reach_distance
    
    -- Resources (ore patches)
    local resources = surface.find_entities_filtered({
        position = position,
        radius = resource_reach,
        type = "resource"
    })
    for _, resource in ipairs(resources) do
        if resource and resource.valid then
            local key = position_key(resource.position.x, resource.position.y)
            self.reachable.resources[key] = true
        end
    end
    
    -- Trees
    local trees = surface.find_entities_filtered({
        position = position,
        radius = resource_reach,
        type = "tree"
    })
    for _, tree in ipairs(trees) do
        if tree and tree.valid then
            local key = position_key(tree.position.x, tree.position.y)
            self.reachable.resources[key] = true
        end
    end
    
    -- Simple entities (rocks)
    local rocks = surface.find_entities_filtered({
        position = position,
        radius = resource_reach,
        type = "simple-entity"
    })
    for _, rock in ipairs(rocks) do
        if rock and rock.valid then
            local key = position_key(rock.position.x, rock.position.y)
            self.reachable.resources[key] = true
        end
    end
    
    -- Find other entities within build reach_distance
    local build_reach = self.character.reach_distance
    local other_entities = surface.find_entities_filtered({
        position = position,
        radius = build_reach
    })
    
    for _, entity in ipairs(other_entities) do
        if entity and entity.valid
            and entity.type ~= "resource"
            and entity.type ~= "tree"
            and entity.type ~= "simple-entity"
            and entity ~= self.character then
            -- Exclude tree stumps and other tree-related corpses
            local is_tree_corpse = (entity.type == "corpse" and
                (string.find(entity.name, "stump") or
                    string.find(entity.name, "tree")))
            if not is_tree_corpse then
                local key = position_key(entity.position.x, entity.position.y)
                self.reachable.entities[key] = true
            end
        end
    end
    
    -- Mark as clean and update tick
    self.reachable.dirty = false
    self.reachable.last_updated_tick = game.tick
end

-- ============================================================================
-- REACHABILITY QUERIES
-- ============================================================================

--- Get reachability cache (position keys only)
--- @param attach_ghosts boolean|nil Whether to include ghosts in response (default: true)
--- @return table Reachability data with entities, resources, and last_updated_tick
function ReachabilityActions.get_reachable_keys(self, attach_ghosts)
    -- Default attach_ghosts to true
    if attach_ghosts == nil then
        attach_ghosts = true
    end
    
    -- Ensure cache is fresh before returning
    if self.reachable.dirty then
        self:process_reachable()
    end
    
    local result = {
        entities = self.reachable.entities,
        resources = self.reachable.resources,
        last_updated_tick = self.reachable.last_updated_tick,
    }
    
    -- Add ghosts position keys if requested
    if attach_ghosts and self.character and self.character.valid then
        local position = self.character.position
        local surface = self.character.surface or game.surfaces[1]
        local build_reach = self.character.reach_distance
        
        local ghosts = surface.find_entities_filtered({
            position = position,
            radius = build_reach,
            type = "entity-ghost"
        })
        
        local ghosts_keys = {}
        for _, ghost in ipairs(ghosts) do
            if ghost and ghost.valid then
                local key = position_key(ghost.position.x, ghost.position.y)
                ghosts_keys[key] = true
            end
        end
        result.ghosts = ghosts_keys
    end
    
    return result
end

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
        position = position,
        radius = resource_reach,
        type = "resource"
    })
    for _, resource in ipairs(resources) do
        local data = serialize_resource(resource)
        if data then
            table.insert(resources_data, data)
        end
    end
    
    -- Trees
    local trees = surface.find_entities_filtered({
        position = position,
        radius = resource_reach,
        type = "tree"
    })
    for _, tree in ipairs(trees) do
        local data = serialize_resource(tree)
        if data then
            table.insert(resources_data, data)
        end
    end
    
    -- Simple entities (rocks)
    local rocks = surface.find_entities_filtered({
        position = position,
        radius = resource_reach,
        type = "simple-entity"
    })
    for _, rock in ipairs(rocks) do
        local data = serialize_resource(rock)
        if data then
            table.insert(resources_data, data)
        end
    end
    
    -- Find other entities within build reach_distance
    local build_reach = self.character.reach_distance
    local other_entities = surface.find_entities_filtered({
        position = position,
        radius = build_reach
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
            if not is_tree_corpse then
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
                local data = serialize_ghost(ghost)
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

--- Mark reachability cache as dirty (needs recomputation)
--- Called by external events (entity build/destroy) and internal state changes
function ReachabilityActions.mark_reachable_dirty(self)
    self.reachable.dirty = true
end

return ReachabilityActions

