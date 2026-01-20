--- Entity Lookup Utilities
--- Provides engine-level entity information without requiring prototype reimplementation
---
--- Key principle: Use entity properties (drop_position, fluidbox, bounding_box) directly
--- from the engine rather than calculating from prototypes.

local M = {}

-- ============================================================================
-- ENTITY LOOKUP
-- ============================================================================

--- Find an entity by name and position
--- @param entity_name string Entity prototype name
--- @param position table Position {x, y}
--- @return LuaEntity|nil The entity, or nil if not found
function M.find_entity(entity_name, position)
    if not entity_name or not position then
        return nil
    end

    local surface = game.surfaces[1]
    return surface.find_entity(entity_name, position)
end

--- Find entities of a type in an area
--- @param entity_type string Entity type (e.g., "resource", "mining-drill")
--- @param area table Area {left_top, right_bottom}
--- @return table Array of entities
function M.find_entities_by_type(entity_type, area)
    local surface = game.surfaces[1]
    return surface.find_entities_filtered({
        area = area,
        type = entity_type,
    })
end

--- Find entities by name in an area
--- @param entity_name string Entity prototype name
--- @param area table Area {left_top, right_bottom}
--- @return table Array of entities
function M.find_entities_by_name(entity_name, area)
    local surface = game.surfaces[1]
    return surface.find_entities_filtered({
        area = area,
        name = entity_name,
    })
end

-- ============================================================================
-- ENTITY OUTPUT INFORMATION
-- ============================================================================

--- Get output/drop information for an entity
--- Uses engine-provided entity.drop_position rather than prototype calculations
--- @param entity_name string Entity prototype name
--- @param position table Entity position {x, y}
--- @return table {drop_position, direction, bounding_box, entity_found}
function M.get_entity_output_info(entity_name, position)
    local entity = M.find_entity(entity_name, position)

    if not entity or not entity.valid then
        -- Entity not found - return prototype-based fallback info
        local proto = prototypes.entity[entity_name]
        if not proto then
            return {
                entity_found = false,
                error = "Unknown entity prototype: " .. tostring(entity_name),
            }
        end

        return {
            entity_found = false,
            prototype_name = entity_name,
            collision_box = proto.collision_box,
            tile_width = proto.tile_width,
            tile_height = proto.tile_height,
        }
    end

    -- Entity found - use engine-provided values
    local result = {
        entity_found = true,
        name = entity.name,
        position = {x = entity.position.x, y = entity.position.y},
        direction = entity.direction,
        bounding_box = {
            left_top = {x = entity.bounding_box.left_top.x, y = entity.bounding_box.left_top.y},
            right_bottom = {x = entity.bounding_box.right_bottom.x, y = entity.bounding_box.right_bottom.y},
        },
    }

    -- Get drop position if entity has one (mining drills, etc.)
    if entity.drop_position then
        result.drop_position = {x = entity.drop_position.x, y = entity.drop_position.y}
    end

    -- Get drop target if there's an entity at the drop position
    if entity.drop_target then
        result.drop_target = {
            name = entity.drop_target.name,
            position = {x = entity.drop_target.position.x, y = entity.drop_target.position.y},
        }
    end

    return result
end

-- ============================================================================
-- FLUID CONNECTION INFORMATION
-- ============================================================================

--- Get fluid connection points for an entity with a fluidbox
--- Returns absolute map positions for each connection, calculated from prototype data
--- @param entity_name string Entity prototype name
--- @param position table Entity position {x, y}
--- @return table {connections: array, entity_found: bool}
function M.get_fluid_connection_points(entity_name, position)
    local entity = M.find_entity(entity_name, position)

    if not entity or not entity.valid then
        return {
            entity_found = false,
            connections = {},
            error = "Entity not found at position",
        }
    end

    local proto = prototypes.entity[entity_name]
    if not proto or not proto.fluidbox_prototypes then
        return {
            entity_found = true,
            connections = {},
            error = "Entity has no fluidbox prototypes",
        }
    end

    local connections = {}
    local entity_pos = entity.position
    local entity_dir = entity.direction

    -- Map direction to positions array index (1-indexed)
    -- North=0 -> 1, East=4 -> 2, South=8 -> 3, West=12 -> 4
    local dir_index = (entity_dir / 4) + 1

    -- Get runtime fluidbox info for flow direction
    local runtime_connections = {}
    if entity.fluidbox and #entity.fluidbox > 0 then
        for fb_index = 1, #entity.fluidbox do
            local pipe_conns = entity.fluidbox.get_pipe_connections(fb_index)
            if pipe_conns then
                runtime_connections[fb_index] = pipe_conns
            end
        end
    end

    -- Use prototype fluidbox data to get correct positions
    for fb_index, fb_proto in ipairs(proto.fluidbox_prototypes) do
        local production_type = fb_proto.production_type  -- "input", "output", "input-output", "none"

        if fb_proto.pipe_connections then
            for conn_index, conn in ipairs(fb_proto.pipe_connections) do
                -- Get relative position based on entity direction
                local rel_pos
                if conn.positions and #conn.positions >= dir_index then
                    -- Use direction-specific position
                    rel_pos = conn.positions[dir_index]
                elseif conn.position then
                    -- Use single position (same for all directions)
                    rel_pos = conn.position
                else
                    rel_pos = {x = 0, y = 0}
                end

                -- Fallback for entities with (0,0) positions: calculate edge from bounding box
                -- This handles entities like offshore-pump where prototype positions are all zeros
                local abs_pos
                if rel_pos.x == 0 and rel_pos.y == 0 then
                    -- Calculate connection position at entity edge based on entity direction
                    local bbox = entity.bounding_box
                    local half_w = (bbox.right_bottom.x - bbox.left_top.x) / 2
                    local half_h = (bbox.right_bottom.y - bbox.left_top.y) / 2

                    -- Determine which direction the connection is on
                    -- For output connections (like offshore pump), output is OPPOSITE to entity facing direction
                    -- (pump faces INTO water, outputs to the opposite side toward land)
                    local conn_dir = entity_dir
                    if production_type == "output" then
                        -- Opposite direction: add 8 (180 degrees) and wrap
                        conn_dir = (entity_dir + 8) % 16
                    end

                    if conn_dir == defines.direction.north then
                        abs_pos = {x = entity_pos.x, y = entity_pos.y - half_h}
                    elseif conn_dir == defines.direction.east then
                        abs_pos = {x = entity_pos.x + half_w, y = entity_pos.y}
                    elseif conn_dir == defines.direction.south then
                        abs_pos = {x = entity_pos.x, y = entity_pos.y + half_h}
                    elseif conn_dir == defines.direction.west then
                        abs_pos = {x = entity_pos.x - half_w, y = entity_pos.y}
                    else
                        abs_pos = {x = entity_pos.x, y = entity_pos.y}
                    end
                else
                    -- Use prototype-provided relative position
                    abs_pos = {
                        x = entity_pos.x + rel_pos.x,
                        y = entity_pos.y + rel_pos.y,
                    }
                end

                -- Get flow direction from runtime if available, otherwise from production_type
                local flow_direction = production_type
                if runtime_connections[fb_index] and runtime_connections[fb_index][conn_index] then
                    flow_direction = runtime_connections[fb_index][conn_index].flow_direction or production_type
                end

                table.insert(connections, {
                    fluidbox_index = fb_index,
                    connection_index = conn_index,
                    position = abs_pos,
                    relative_position = rel_pos,
                    flow_direction = flow_direction,
                    connection_direction = conn.direction,
                })
            end
        end
    end

    return {
        entity_found = true,
        name = entity.name,
        position = {x = entity_pos.x, y = entity_pos.y},
        direction = entity_dir,
        connections = connections,
    }
end

-- ============================================================================
-- INSERTER INFORMATION
-- ============================================================================

--- Get inserter pickup and drop positions
--- @param entity_name string Inserter prototype name
--- @param position table Entity position {x, y}
--- @return table {pickup_position, drop_position, entity_found}
function M.get_inserter_positions(entity_name, position)
    local entity = M.find_entity(entity_name, position)

    if not entity or not entity.valid then
        return {
            entity_found = false,
            error = "Entity not found at position",
        }
    end

    -- Verify it's an inserter
    if entity.type ~= "inserter" then
        return {
            entity_found = true,
            error = "Entity is not an inserter: " .. entity.type,
        }
    end

    return {
        entity_found = true,
        name = entity.name,
        position = {x = entity.position.x, y = entity.position.y},
        direction = entity.direction,
        pickup_position = {x = entity.pickup_position.x, y = entity.pickup_position.y},
        drop_position = {x = entity.drop_position.x, y = entity.drop_position.y},
        pickup_target = entity.pickup_target and {
            name = entity.pickup_target.name,
            position = {x = entity.pickup_target.position.x, y = entity.pickup_target.position.y},
        } or nil,
        drop_target = entity.drop_target and {
            name = entity.drop_target.name,
            position = {x = entity.drop_target.position.x, y = entity.drop_target.position.y},
        } or nil,
    }
end

-- ============================================================================
-- ELECTRIC POLE INFORMATION
-- ============================================================================

--- Get electric pole network information
--- @param entity_name string Pole prototype name
--- @param position table Entity position {x, y}
--- @return table {supply_area, wire_reach, connected_poles, entities_powered}
function M.get_pole_info(entity_name, position)
    local entity = M.find_entity(entity_name, position)

    if not entity or not entity.valid then
        -- Return prototype info as fallback
        local proto = prototypes.entity[entity_name]
        if proto then
            return {
                entity_found = false,
                maximum_wire_distance = proto.get_max_wire_distance(),
                supply_area_distance = proto.get_supply_area_distance(),
            }
        end
        return {
            entity_found = false,
            error = "Entity not found and unknown prototype",
        }
    end

    local proto = prototypes.entity[entity_name]
    local result = {
        entity_found = true,
        name = entity.name,
        position = {x = entity.position.x, y = entity.position.y},
        maximum_wire_distance = proto.get_max_wire_distance(),
        supply_area_distance = proto.get_supply_area_distance(),
    }

    -- Get connected poles via copper wire (Factorio 2.0 API)
    local connected_poles = {}
    local copper_connector = entity.get_wire_connector(defines.wire_connector_id.pole_copper, false)
    if copper_connector then
        local connections = copper_connector.real_connections
        if connections then
            for _, conn in ipairs(connections) do
                local target = conn.target
                if target and target.owner and target.owner.valid then
                    table.insert(connected_poles, {
                        name = target.owner.name,
                        position = {x = target.owner.position.x, y = target.owner.position.y},
                    })
                end
            end
        end
    end
    result.connected_poles = connected_poles

    -- Get electric network info
    if entity.electric_network_id then
        result.electric_network_id = entity.electric_network_id
    end

    return result
end

-- ============================================================================
-- PROTOTYPE HELPERS
-- ============================================================================

--- Check if an entity prototype requires resources for placement (mining drills)
--- @param entity_name string Entity prototype name
--- @return boolean
function M.entity_requires_resources(entity_name)
    if string.find(entity_name, "mining%-drill") then
        return true
    end
    if entity_name == "pumpjack" then
        return true
    end
    return false
end

--- Check if an entity prototype requires water for placement (offshore pumps)
--- @param entity_name string Entity prototype name
--- @return boolean
function M.entity_requires_water(entity_name)
    return entity_name == "offshore-pump"
end

--- Check if an entity is directional (needs direction for placement)
--- @param entity_name string Entity prototype name
--- @return boolean
function M.entity_is_directional(entity_name)
    -- Check prototype flags
    local proto = prototypes.entity[entity_name]
    if not proto then
        return false
    end

    -- Entities with these types are typically directional
    local directional_types = {
        ["transport-belt"] = true,
        ["underground-belt"] = true,
        ["splitter"] = true,
        ["loader"] = true,
        ["inserter"] = true,
        ["mining-drill"] = true,
        ["offshore-pump"] = true,
        ["pump"] = true,
        ["boiler"] = true,
        ["generator"] = true,
        ["assembling-machine"] = true,
        ["furnace"] = true,
        ["lab"] = true,
    }

    return directional_types[proto.type] or false
end

return M
