--- factorio_verse/utils/serialize.lua
--- Pure serialization utilities for entities and inventories
--- Stateless functions - no module state, reusable across modules

local utils = require("utils.utils")

local M = {}

-- ============================================================================
-- COMPONENT TYPE DETERMINATION
-- ============================================================================

--- Determine component type for an entity
--- @param entity_type string Entity type from Factorio API
--- @param entity_name string Entity prototype name
--- @return string Component type ("belts", "pipes", "poles", "entities")
function M.get_component_type(entity_type, entity_name)
    -- Belt types
    if entity_type == "transport-belt" or entity_type == "underground-belt" or
        entity_type == "splitter" or entity_type == "loader" or
        entity_type == "loader-1x1" or entity_type == "linked-belt" then
        return "belts"
    end

    -- Pipe types
    if entity_type == "pipe" or entity_type == "pipe-to-ground" then
        return "pipes"
    end

    -- Electric pole types
    if entity_type == "electric-pole" or entity_type == "power-switch" or
        entity_type == "substation" then
        return "poles"
    end

    if entity_type == "mining-drill" then
        return "mining-drill"
    end

    -- Default to entities for all other player-placed entities
    return "entities"
end

-- ============================================================================
-- ENTITY SERIALIZATION
-- ============================================================================

--- Serialize base properties common to all entities
--- @param entity LuaEntity
--- @param out table Output table to populate
local function _serialize_base_properties(entity, out)
    local proto = entity.prototype

    -- Cache frequently accessed properties for performance
    local pos = entity.position
    local dir = entity.direction
    local orient = entity.orientation

    -- Base identity and spatial properties
    -- Key removed - using composite (name, position) in database
    out.name = entity.name
    out.type = entity.type
    out.force = (entity.force and entity.force.name) or nil
    out.position = pos
    out.direction = dir
    out.direction_name = utils.direction_to_name(dir and tonumber(tostring(dir)) or nil)
    out.orientation = orient
    out.orientation_name = utils.orientation_to_name(orient)

    -- Electric network id
    if entity.electric_network_id ~= nil then
        out.electric_network_id = entity.electric_network_id
    end

    -- Tile dimensions from prototype
    local tile_width = 1
    local tile_height = 1
    if proto then
        if proto.tile_width ~= nil then
            out.tile_width = proto.tile_width
            tile_width = proto.tile_width
        end
        if proto.tile_height ~= nil then
            out.tile_height = proto.tile_height
            tile_height = proto.tile_height
        end
    end

    -- Anchor tile: the tile containing the entity's center
    out.anchor_tile = {
        x = math.floor(pos.x),
        y = math.floor(pos.y)
    }

    -- Footprint tiles: all tiles occupied by this entity
    -- For asymmetric entities (width != height), swap dimensions for EAST/WEST
    local effective_width = tile_width
    local effective_height = tile_height
    if dir and (dir == defines.direction.east or dir == defines.direction.west) then
        if tile_width ~= tile_height then
            effective_width, effective_height = tile_height, tile_width
        end
    end

    local half_w = effective_width / 2
    local half_h = effective_height / 2

    local min_x = math.floor(pos.x - half_w)
    local max_x = math.floor(pos.x + half_w - 0.001)  -- epsilon for exact boundaries
    local min_y = math.floor(pos.y - half_h)
    local max_y = math.floor(pos.y + half_h - 0.001)

    local tiles = {}
    for x = min_x, max_x do
        for y = min_y, max_y do
            tiles[#tiles + 1] = {x = x, y = y}
        end
    end
    out.footprint_tiles = tiles

    -- Crafting / recipe (gate to crafting machines only)
    -- Only call get_recipe() on entity types that actually support it
    -- According to Factorio API: assembling-machine, furnace, rocket-silo
    local is_crafter = (entity.type == "assembling-machine" or 
                        entity.type == "furnace" or 
                        entity.type == "rocket-silo")

    if is_crafter then
        local r = entity.get_recipe()
        if r then
            out.recipe = r.name
        end
        local ok_speed, crafting_speed = pcall(function() return entity.crafting_speed end)
        if ok_speed and crafting_speed ~= nil then
            out.crafting_speed = crafting_speed
        end
    end

    -- Bounding box
    local bb = entity.selection_box
    if bb and bb.left_top and bb.right_bottom then
        out.bounding_box = {
            min_x = bb.left_top.x,
            min_y = bb.left_top.y,
            max_x = bb.right_bottom.x,
            max_y = bb.right_bottom.y
        }
    end
end

--- Serialize mining-drill specific data
--- @param entity LuaEntity
--- @param out table Output table to populate
local function _serialize_mining_drill_data(entity, out)
    local mining_area = entity.mining_area
    if mining_area then
        out.mining_area = mining_area
    end
    local mining_target = entity.mining_target
    if mining_target and mining_target.valid then
        out.mining_target = mining_target.name
    elseif mining_area and entity.surface then
        -- on_built_entity can fire before Factorio assigns mining_target.
        -- Preserve a semantic component row by recording the first currently
        -- minable resource prototype in the engine-provided mining area; a
        -- later full configuration upsert replaces it with the active target.
        local resources = entity.surface.find_entities_filtered{
            area = mining_area,
            type = "resource"
        }
        for _, resource in pairs(resources) do
            if resource and resource.valid then
                out.mining_target = resource.name
                break
            end
        end
    end
end

--- Serialize belt-specific data
--- @param entity LuaEntity
--- @param out table Output table to populate
local function _serialize_belt_data(entity, out)
    -- Only event-backed structure goes to the map model (Constitution §10;
    -- API_AFFORDANCE §4.6). Items on the belt are simulation state and are read
    -- live; belt_neighbours is adjacency that is derived from (position, direction)
    -- at read time and was stale by construction when stored (TRANSPORT §2.1).
    local ok_speed, belt_speed = pcall(function() return entity.prototype.belt_speed end)
    if ok_speed and belt_speed ~= nil then
        out.belt_speed = belt_speed
    end

    -- Underground belt pairing: belt_to_ground_type is the one column the belt
    -- derivation needs to bridge a tunnel (TRANSPORT §2.2). underground_neighbour is
    -- still emitted because Python's BeltState reads it (transform.py); it is
    -- adjacency and goes when the derived component replaces it.
    local underground_other = nil
    local belt_to_ground_type = nil
    if entity.type == "underground-belt" then
        belt_to_ground_type = entity.belt_to_ground_type
        local un = entity.neighbours
        if un and un.valid and un.name and un.position then
            underground_other = {name = un.name, position = {x = un.position.x, y = un.position.y}}
        end
    end

    out.belt_data = {
        belt_to_ground_type = belt_to_ground_type,
        underground_neighbour = underground_other
    }
end

--- Serialize pipe-specific data
--- @param entity LuaEntity
--- @param out table Output table to populate
local function _serialize_pipe_data(entity, out)
    -- Ports as the engine reports them (get_pipe_connections), per fluidbox. No
    -- inputs/outputs split: pipes have production_type=none and every port is
    -- input-output, so the split an earlier version computed from dx > 0 was a
    -- fabrication (TRANSPORT §8.1). Ports are prototype geometry — structure, not
    -- simulation — and carry no neighbour identity, so nothing here goes stale
    -- when a neighbour is placed.
    local ports = {}
    local fb = entity.fluidbox
    if fb and fb.get_pipe_connections then
        for k = 1, #fb do
            local ok, conns = pcall(fb.get_pipe_connections, k)
            if ok and conns then
                for i, c in ipairs(conns) do
                    ports[#ports + 1] = {
                        fluidbox_index = k,
                        index = i,
                        position = c.position and {x = c.position.x, y = c.position.y} or nil,
                        target_position = c.target_position and {x = c.target_position.x, y = c.target_position.y} or nil,
                        flow_direction = c.flow_direction,
                        connection_type = c.connection_type,
                    }
                end
            end
        end
    end
    out.pipe_data = { ports = (#ports > 0) and ports or nil }
end

--- Serialize inserter-specific data
--- @param entity LuaEntity
--- @param out table Output table to populate
local function _serialize_inserter_data(entity, out)
    local ins = {
        pickup_position = entity.pickup_position,
        drop_position = entity.drop_position,
    }
    local pt = entity.pickup_target
    if pt and pt.valid and pt.name and pt.position then
        ins.pickup_target = {name = pt.name, position = {x = pt.position.x, y = pt.position.y}}
    end
    local dt = entity.drop_target
    if dt and dt.valid and dt.name and dt.position then
        ins.drop_target = {name = dt.name, position = {x = dt.position.x, y = dt.position.y}}
    end
    -- Filter contract (2.0 entity-level filters): durable config belongs in
    -- the snapshot so the DB can serve it (boundary rule: contracts yes,
    -- volatile state no)
    if (entity.filter_slot_count or 0) > 0 then
        ins.use_filters = entity.use_filters or false
        ins.filter_mode = entity.inserter_filter_mode
        local filters = {}
        for i = 1, entity.filter_slot_count do
            local f = entity.get_filter(i)
            if f then
                local fname = f.name
                if type(fname) == "table" then fname = fname.name end
                filters[#filters + 1] = { index = i, name = fname }
            end
        end
        if #filters > 0 then ins.filters = filters end
    end
    if next(ins) ~= nil then out.inserter = ins end
end

--- Serialize pole-specific data
--- @param entity LuaEntity
--- @param out table Output table to populate
local function _serialize_pole_data(entity, out)
    -- nil-safe: the "poles" component also matches power-switch, whose
    -- prototype lacks the pole distance getters
    local ok_wire, max_wire = pcall(function() return entity.prototype.get_max_wire_distance() end)
    if ok_wire then out.max_wire_distance = max_wire end
    local ok_supply, supply = pcall(function() return entity.prototype.get_supply_area_distance() end)
    if ok_supply then out.supply_area_distance = supply end

    -- Copper-wire neighbours (connected poles) as name+position refs.
    -- Factorio 2.0: entity.neighbours RAISES on poles — use the wire connector
    -- API (same pattern as fv_placement_hints/utils/entity_lookup.lua).
    local connected = {}
    local ok, copper = pcall(function()
        return entity.get_wire_connector(defines.wire_connector_id.pole_copper, false)
    end)
    if ok and copper then
        local conns = copper.real_connections
        if conns then
            for _, conn in ipairs(conns) do
                local target = conn.target
                if target and target.owner and target.owner.valid and target.owner.position then
                    connected[#connected + 1] = {
                        name = target.owner.name,
                        position = {x = target.owner.position.x, y = target.owner.position.y}
                    }
                end
            end
        end
    end

    out.pole_data = {
        connected_poles = ((#connected > 0) and connected) or nil
    }
end

--- Serialize entity data for JSON storage
--- Direct LuaEntity access - no resolution overhead (for bulk operations)
--- @param entity LuaEntity
--- @param builder_info table|nil Optional builder info {agent_id, player_id, label}
--- @return table|nil Serialized entity data or nil if invalid
function M.serialize_entity(entity, builder_info)
    if not (entity and entity.valid) then return nil end

    local out = {}

    -- Serialize base properties
    _serialize_base_properties(entity, out)

    -- Determine component type and serialize component-specific data
    local component_type = M.get_component_type(entity.type, entity.name)

    if component_type == "belts" then
        _serialize_belt_data(entity, out)
    elseif component_type == "pipes" then
        _serialize_pipe_data(entity, out)
    elseif component_type == "mining-drill" then
        _serialize_mining_drill_data(entity, out)
    elseif component_type == "poles" then
        _serialize_pole_data(entity, out)
    end

    -- Inserter IO (pickup/drop positions and resolved targets)
    if entity.type == "inserter" then
        _serialize_inserter_data(entity, out)
    end
    
    -- Add builder metadata if provided
    if builder_info then
        out.builder = builder_info
    end

    return out
end

-- ============================================================================
-- INVENTORY SERIALIZATION
-- ============================================================================

--- Serialize all inventories for an entity
--- Collects contents from all inventory types the entity supports
--- @param entity LuaEntity The entity to serialize inventories for
--- @return table Inventory contents by type name (e.g., {chest = {...}, input = {...}})
function M.serialize_entity_inventories(entity)
    if not (entity and entity.valid) then
        return {}
    end

    local inventories = {}
    local inventory_types = {
        chest = defines.inventory.chest,
        fuel = defines.inventory.fuel,
        burnt_result = defines.inventory.burnt_result,
        input = defines.inventory.assembling_machine_input,
        output = defines.inventory.assembling_machine_output,
        modules = defines.inventory.assembling_machine_modules,
        ammo = defines.inventory.turret_ammo,
        trunk = defines.inventory.car_trunk,
        cargo = defines.inventory.cargo_wagon,
    }

    for inventory_name, inventory_type in pairs(inventory_types) do
        local inventory = entity.get_inventory(inventory_type)

        if inventory and inventory.valid then
            local contents = inventory.get_contents()
            if contents and next(contents) ~= nil then
                inventories[inventory_name] = contents
            end
        end
    end

    return inventories
end

-- ============================================================================
-- GHOST SERIALIZATION
-- ============================================================================

--- Serialize ghost entity to data structure
--- @param ghost LuaEntity Ghost entity (type="entity-ghost")
--- @param builder_info table|nil Optional builder info {agent_id, player_id, label}
--- @return table|nil Ghost data, or nil if invalid
function M.serialize_ghost(ghost, builder_info)
    if not (ghost and ghost.valid) then
        return nil
    end

    local pos = ghost.position
    local dir = ghost.direction

    -- Generate position key (format: "x,y" with 1 decimal precision)
    local pos_key = string.format("%.1f,%.1f", pos.x, pos.y)

    local data = {
        name = ghost.name,  -- "entity-ghost"
        type = ghost.type,  -- "entity-ghost"
        position = { x = pos.x, y = pos.y },
        position_key = pos_key,
        ghost_name = ghost.ghost_name,  -- The entity this ghost represents
    }

    -- Add direction if available
    if dir then
        data.direction = dir
        data.direction_name = utils.direction_to_name(dir and tonumber(tostring(dir)) or nil)
    end

    -- Add force if available
    if ghost.force and ghost.force.name then
        data.force = ghost.force.name
    end

    -- Get tile dimensions from ghost prototype
    local ghost_proto = ghost.ghost_prototype
    local tile_width = 1
    local tile_height = 1
    if ghost_proto then
        if ghost_proto.tile_width then
            data.tile_width = ghost_proto.tile_width
            tile_width = ghost_proto.tile_width
        end
        if ghost_proto.tile_height then
            data.tile_height = ghost_proto.tile_height
            tile_height = ghost_proto.tile_height
        end
    end

    -- Anchor tile: the tile containing the ghost's center
    data.anchor_tile = {
        x = math.floor(pos.x),
        y = math.floor(pos.y)
    }

    -- Footprint tiles: all tiles occupied by this ghost
    -- For asymmetric entities (width != height), swap dimensions for EAST/WEST
    local effective_width = tile_width
    local effective_height = tile_height
    if dir and (dir == defines.direction.east or dir == defines.direction.west) then
        if tile_width ~= tile_height then
            effective_width, effective_height = tile_height, tile_width
        end
    end

    local half_w = effective_width / 2
    local half_h = effective_height / 2

    local min_x = math.floor(pos.x - half_w)
    local max_x = math.floor(pos.x + half_w - 0.001)
    local min_y = math.floor(pos.y - half_h)
    local max_y = math.floor(pos.y + half_h - 0.001)

    local tiles = {}
    for x = min_x, max_x do
        for y = min_y, max_y do
            tiles[#tiles + 1] = {x = x, y = y}
        end
    end
    data.footprint_tiles = tiles

    -- Add builder metadata if provided
    if builder_info then
        data.builder = builder_info
    end

    return data
end

return M
