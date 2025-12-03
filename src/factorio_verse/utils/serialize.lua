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

    -- Base identity and spatial properties
    out.unit_number = entity.unit_number
    out.name = entity.name
    out.type = entity.type
    out.force = (entity.force and entity.force.name) or nil
    out.position = entity.position
    out.direction = entity.direction
    out.direction_name = utils.direction_to_name(entity.direction and tonumber(tostring(entity.direction)) or nil)
    out.orientation = entity.orientation
    out.orientation_name = utils.orientation_to_name(entity.orientation)

    -- Electric network id
    if entity.electric_network_id ~= nil then
        out.electric_network_id = entity.electric_network_id
    end

    -- Tile dimensions from prototype
    if proto then
        if proto.tile_width ~= nil then out.tile_width = proto.tile_width end
        if proto.tile_height ~= nil then out.tile_height = proto.tile_height end
    end

    -- Crafting / recipe (gate to crafting machines only)
    local is_crafter = (entity.type == "assembling-machine" or entity.type == "furnace")
    if not is_crafter and proto and proto.crafting_categories then
        is_crafter = true
    end

    if is_crafter then
        local r = entity.get_recipe()
        if r then out.recipe = r.name end
    end

    -- Bounding box
    local bb = entity.bounding_box
    if bb and bb.left_top and bb.right_bottom then
        out.bounding_box = {
            min_x = bb.left_top.x,
            min_y = bb.left_top.y,
            max_x = bb.right_bottom.x,
            max_y = bb.right_bottom.y
        }
    end
end

--- Serialize belt-specific data
--- @param entity LuaEntity
--- @param out table Output table to populate
local function _serialize_belt_data(entity, out)
    -- Belt item lines
    local item_lines = {}
    local max_index = 0
    local v = (entity.get_max_transport_line_index and entity.get_max_transport_line_index()) or 0
    max_index = (type(v) == "number" and v > 0) and v or 0

    for li = 1, max_index do
        local tl = entity.get_transport_line and entity.get_transport_line(li) or nil
        if tl then
            local contents = tl.get_contents and tl.get_contents() or nil
            if contents and next(contents) ~= nil then
                item_lines[#item_lines + 1] = { index = li, items = contents }
            end
        end
    end

    -- Belt neighbours (inputs/outputs)
    local inputs_ids, outputs_ids = {}, {}
    local bn = entity.belt_neighbours
    if bn then
        if bn.inputs then
            for _, n in ipairs(bn.inputs) do
                if n and n.valid and n.unit_number then inputs_ids[#inputs_ids + 1] = n.unit_number end
            end
        end
        if bn.outputs then
            for _, n in ipairs(bn.outputs) do
                if n and n.valid and n.unit_number then outputs_ids[#outputs_ids + 1] = n.unit_number end
            end
        end
    end

    -- Underground belt pairing
    local underground_other = nil
    local belt_to_ground_type = nil
    if entity.type == "underground-belt" then
        belt_to_ground_type = entity.belt_to_ground_type
        local un = entity.neighbours
        if un and un.valid and un.unit_number then underground_other = un.unit_number end
    end

    out.belt_data = {
        item_lines = item_lines,
        belt_neighbours = ((#inputs_ids > 0 or #outputs_ids > 0) and { inputs = inputs_ids, outputs = outputs_ids }) or nil,
        belt_to_ground_type = belt_to_ground_type,
        underground_neighbour_unit = underground_other
    }
end

--- Serialize pipe-specific data
--- @param entity LuaEntity
--- @param out table Output table to populate
local function _serialize_pipe_data(entity, out)
    local inputs_ids, outputs_ids = {}, {}
    local fb = entity.fluidbox
    if fb then
        for k = 1, #fb do
            local connections = fb.get_connections and fb.get_connections(k) or {}
            for _, conn in ipairs(connections) do
                if conn.owner and conn.owner.valid and conn.owner.unit_number then
                    local conn_entity = conn.owner
                    local conn_unit = conn_entity.unit_number

                    -- Categorize connections based on entity type and relative position
                    if conn_entity.type == "pipe" or conn_entity.type == "pipe-to-ground" then
                        if conn_entity.position and entity.position then
                            local dx = conn_entity.position.x - entity.position.x
                            local dy = conn_entity.position.y - entity.position.y
                            if dx > 0 or dy > 0 then
                                inputs_ids[#inputs_ids + 1] = conn_unit
                            else
                                outputs_ids[#outputs_ids + 1] = conn_unit
                            end
                        else
                            inputs_ids[#inputs_ids + 1] = conn_unit
                        end
                    else
                        inputs_ids[#inputs_ids + 1] = conn_unit
                    end
                end
            end
        end
    end

    out.pipe_data = {
        pipe_neighbours = ((#inputs_ids > 0 or #outputs_ids > 0) and { inputs = inputs_ids, outputs = outputs_ids }) or nil
    }
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
    if pt and pt.valid and pt.unit_number then ins.pickup_target_unit = pt.unit_number end
    local dt = entity.drop_target
    if dt and dt.valid and dt.unit_number then ins.drop_target_unit = dt.unit_number end
    if next(ins) ~= nil then out.inserter = ins end
end

--- Serialize entity data for JSON storage
--- Direct LuaEntity access - no resolution overhead (for bulk operations)
--- @param entity LuaEntity
--- @return table|nil Serialized entity data or nil if invalid
function M.serialize_entity(entity)
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
    end

    -- Inserter IO (pickup/drop positions and resolved targets)
    if entity.type == "inserter" then
        _serialize_inserter_data(entity, out)
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
        local success, inventory = pcall(function()
            return entity.get_inventory(inventory_type)
        end)

        if success and inventory and inventory.valid then
            local contents = inventory.get_contents()
            if contents and next(contents) ~= nil then
                inventories[inventory_name] = contents
            end
        end
    end

    return inventories
end

return M

