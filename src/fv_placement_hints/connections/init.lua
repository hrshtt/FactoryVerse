--- Connections Module
--- Aggregates all connection solving functionality
---
--- Connection solving finds valid positions to place entities that connect to existing entities:
--- - Item drop: drill → chest/belt
--- - Fluid: machine → pipe
--- - Inserter: between two entities
--- - Electric: pole → pole

local M = {}

local geometry = require("utils.geometry")
local entity_lookup = require("utils.entity_lookup")
local scanning = require("scanning.area")

-- ============================================================================
-- ITEM DROP CONNECTIONS
-- ============================================================================

--- Get valid positions to connect item output (drill → chest/belt)
--- Uses engine-provided entity.drop_position rather than prototype calculations
--- @param source_name string Source entity name
--- @param source_position table Source entity position {x, y}
--- @param target_name string Target entity name to place
--- @param options table|nil {max_results: number, ghost: bool}
--- @return table Array of {position, direction, perpendicular_offset}
function M.get_item_drop_connections(source_name, source_position, target_name, options)
    options = options or {}
    local max_results = options.max_results or 20
    local ghost = options.ghost or false

    -- Get source entity output info from engine
    local source_info = entity_lookup.get_entity_output_info(source_name, source_position)
    if not source_info.entity_found then
        return {
            error = "Source entity not found at position",
            source_name = source_name,
            source_position = source_position,
            positions = {},
        }
    end

    if not source_info.drop_position then
        return {
            error = "Source entity has no drop_position",
            source_name = source_name,
            positions = {},
        }
    end

    local drop_pos = source_info.drop_position
    local source_bbox = source_info.bounding_box
    local source_direction = source_info.direction or defines.direction.north

    -- Get target prototype info
    local target_proto = prototypes.entity[target_name]
    if not target_proto then
        return {
            error = "Unknown target entity prototype: " .. tostring(target_name),
            positions = {},
        }
    end

    local target_cbox = target_proto.collision_box
    local target_half_w = (target_cbox.right_bottom.x - target_cbox.left_top.x) / 2
    local target_half_h = (target_cbox.right_bottom.y - target_cbox.left_top.y) / 2

    local surface = game.surfaces[1]
    local build_check = ghost and defines.build_check_type.manual_ghost or defines.build_check_type.manual

    -- Identify the drop tile (the 1x1 tile containing the drop position)
    -- Tile (n, m) has center (n + 0.5, m + 0.5) and covers [n, n+1) × [m, m+1)
    local drop_tile_x = math.floor(drop_pos.x)
    local drop_tile_y = math.floor(drop_pos.y)

    -- Get target entity tile dimensions
    local target_tile_w = target_proto.tile_width or math.ceil(target_half_w * 2)
    local target_tile_h = target_proto.tile_height or math.ceil(target_half_h * 2)

    -- Generate candidate positions using footprint intersection model:
    -- For a w×h entity to cover tile (tx, ty), its top-left corner must be at:
    --   x in [tx - w + 1, tx]  (so rightmost column covers tx)
    --   y in [ty - h + 1, ty]  (so bottom row covers ty)
    -- Entity center = top_left + (w/2, h/2), snapped to tile grid
    local candidates = {}

    for corner_x = drop_tile_x - target_tile_w + 1, drop_tile_x do
        for corner_y = drop_tile_y - target_tile_h + 1, drop_tile_y do
            -- Entity center for a w×h entity with top-left at (corner_x, corner_y)
            -- is at (corner_x + w/2, corner_y + h/2)
            local candidate_pos = {
                x = corner_x + target_tile_w / 2,
                y = corner_y + target_tile_h / 2,
            }

            -- Check if candidate footprint overlaps with source entity footprint
            local candidate_bbox = geometry.bbox_from_center(candidate_pos, target_half_w, target_half_h)
            if not geometry.bbox_overlap(candidate_bbox, source_bbox) then
                -- Calculate perpendicular offset for alignment quality
                -- Use drop_pos so offset=0 means perfect alignment with item output
                local perp_offset = geometry.perpendicular_offset(
                    drop_pos,
                    source_direction,
                    candidate_pos
                )

                -- Calculate distance to drop position for tiebreaking
                local dist_to_drop = geometry.distance(candidate_pos, drop_pos)

                table.insert(candidates, {
                    position = candidate_pos,
                    perpendicular_offset = perp_offset,
                    distance_to_drop = dist_to_drop,
                })
            end
        end
    end

    -- Sort by perpendicular offset (best alignment first), then by distance to drop (closest first)
    table.sort(candidates, function(a, b)
        if a.perpendicular_offset ~= b.perpendicular_offset then
            return a.perpendicular_offset < b.perpendicular_offset
        end
        return a.distance_to_drop < b.distance_to_drop
    end)

    -- Validate candidates and return valid ones
    local positions = {}
    local count = 0

    for _, candidate in ipairs(candidates) do
        if count >= max_results then
            break
        end

        local params = {
            name = target_name,
            position = candidate.position,
            force = "player",
            build_check_type = build_check,
        }

        if surface.can_place_entity(params) then
            count = count + 1
            table.insert(positions, {
                position = candidate.position,
                perpendicular_offset = candidate.perpendicular_offset,
                distance_to_drop = candidate.distance_to_drop,
                valid = true,
            })
        end
    end

    return {
        source_name = source_name,
        source_position = source_position,
        drop_position = drop_pos,
        target_name = target_name,
        positions = positions,
        count = count,
    }
end

-- ============================================================================
-- FLUID CONNECTIONS
-- ============================================================================

--- Get valid positions to connect fluid pipes to a machine
--- @param source_name string Source entity name with fluidbox
--- @param source_position table Source entity position {x, y}
--- @param target_name string Target entity name (pipe, pump, etc.)
--- @param options table|nil {max_results: number, ghost: bool}
--- @return table Array of {position, direction, connection_index, connection_type}
function M.get_fluid_connections(source_name, source_position, target_name, options)
    options = options or {}
    local max_results = options.max_results or 20
    local ghost = options.ghost or false

    -- Get fluid connection points from engine
    local conn_info = entity_lookup.get_fluid_connection_points(source_name, source_position)
    if not conn_info.entity_found then
        return {
            error = "Source entity not found at position",
            source_name = source_name,
            source_position = source_position,
            positions = {},
        }
    end

    if #conn_info.connections == 0 then
        return {
            error = "Source entity has no fluid connections",
            source_name = source_name,
            positions = {},
        }
    end

    local surface = game.surfaces[1]
    local build_check = ghost and defines.build_check_type.manual_ghost or defines.build_check_type.manual

    local positions = {}
    local count = 0
    local seen = {}

    -- ------------------------------------------------------------------
    -- Geometry-aware path (fixes PLACE-1, certified L4.4): a candidate
    -- center must be offset so one of the TARGET's OWN fluid connection
    -- cells lands on the source connection's partner cell, facing back.
    -- The old code tried the target's CENTER at the connection point ±1
    -- tile, which structurally yields zero candidates for any multi-tile
    -- target (steam-engine, boiler, ...). Target offsets are probed from
    -- the engine itself (temporary create per direction), so this never
    -- guesses prototype rotation semantics.
    -- ------------------------------------------------------------------

    -- Live world-space source connections (own cell + partner cell + flow).
    local source_conns = {}
    local source_entity = entity_lookup.find_entity(source_name, source_position)
    if source_entity and source_entity.valid and source_entity.fluidbox then
        for fb_index = 1, #source_entity.fluidbox do
            local ok, pipe_conns = pcall(function()
                return source_entity.fluidbox.get_pipe_connections(fb_index)
            end)
            if ok and pipe_conns then
                for conn_index, pc in ipairs(pipe_conns) do
                    if pc.position and pc.target_position then
                        table.insert(source_conns, {
                            own = pc.position,
                            partner = pc.target_position,
                            flow_direction = pc.flow_direction or "input-output",
                            fluidbox_index = fb_index,
                            connection_index = conn_index,
                        })
                    end
                end
            end
        end
    end

    -- Probe the target's own connection offsets per placeable direction.
    local function probe_target_offsets()
        local tproto = prototypes.entity[target_name]
        if not tproto or not tproto.fluidbox_prototypes or #tproto.fluidbox_prototypes == 0 then
            return nil
        end
        local staging = surface.find_non_colliding_position(target_name, source_position, 64, 1)
        if not staging then
            return nil
        end
        local by_direction = {}
        local any = false
        for _, dir in ipairs({
            defines.direction.north,
            defines.direction.east,
            defines.direction.south,
            defines.direction.west,
        }) do
            local ok, temp = pcall(function()
                return surface.create_entity{
                    name = target_name,
                    position = staging,
                    direction = dir,
                    force = "player",
                    create_build_effect_smoke = false,
                }
            end)
            if ok and temp and temp.valid then
                local actual_dir = temp.direction
                if not by_direction[actual_dir] then
                    local center = temp.position
                    local conns = {}
                    if temp.fluidbox then
                        for i = 1, #temp.fluidbox do
                            local ok2, pcs = pcall(function()
                                return temp.fluidbox.get_pipe_connections(i)
                            end)
                            if ok2 and pcs then
                                for _, pc in ipairs(pcs) do
                                    if pc.position and pc.target_position then
                                        table.insert(conns, {
                                            own = {x = pc.position.x - center.x, y = pc.position.y - center.y},
                                            partner = {x = pc.target_position.x - center.x, y = pc.target_position.y - center.y},
                                            flow_direction = pc.flow_direction or "input-output",
                                        })
                                        any = true
                                    end
                                end
                            end
                        end
                    end
                    by_direction[actual_dir] = conns
                end
                temp.destroy()
            end
        end
        if any then return by_direction end
        return nil
    end

    local function flows_compatible(a, b)
        -- A strict output cannot feed a strict output, nor input an input.
        if a == "output" and b == "output" then return false end
        if a == "input" and b == "input" then return false end
        return true
    end

    local target_offsets = (#source_conns > 0) and probe_target_offsets() or nil

    if target_offsets then
        for _, sc in ipairs(source_conns) do
            if count >= max_results then break end
            for dir, tconns in pairs(target_offsets) do
                if count >= max_results then break end
                for _, tc in ipairs(tconns) do
                    if count >= max_results then break end
                    if flows_compatible(sc.flow_direction, tc.flow_direction) then
                        -- Target center such that its connection cell lands
                        -- on the source connection's partner cell...
                        local cx = sc.partner.x - tc.own.x
                        local cy = sc.partner.y - tc.own.y
                        -- ...and points back at the source's own cell.
                        if math.abs(cx + tc.partner.x - sc.own.x) < 0.01
                            and math.abs(cy + tc.partner.y - sc.own.y) < 0.01 then
                            local key = cx .. "," .. cy .. "," .. dir
                            if not seen[key] then
                                seen[key] = true
                                if surface.can_place_entity{
                                    name = target_name,
                                    position = {x = cx, y = cy},
                                    direction = dir,
                                    force = "player",
                                    build_check_type = build_check,
                                } then
                                    count = count + 1
                                    table.insert(positions, {
                                        position = {x = cx, y = cy},
                                        direction = dir,
                                        connection_index = sc.connection_index,
                                        fluidbox_index = sc.fluidbox_index,
                                        flow_direction = sc.flow_direction,
                                        valid = true,
                                    })
                                end
                            end
                        end
                    end
                end
            end
        end
    end

    -- Legacy center/adjacent fallback: keeps pre-existing behavior for
    -- sources/targets the probe path cannot handle (no live source entity,
    -- unprobeable target like offshore-pump on land, missing API fields).
    if count == 0 then
        for _, conn in ipairs(conn_info.connections) do
            if count >= max_results then
                break
            end

            local conn_pos = conn.position

            -- Try placing target at the connection point first
            local params = {
                name = target_name,
                position = conn_pos,
                force = "player",
                build_check_type = build_check,
            }

            if surface.can_place_entity(params) then
                count = count + 1
                table.insert(positions, {
                    position = conn_pos,
                    connection_index = conn.connection_index,
                    fluidbox_index = conn.fluidbox_index,
                    flow_direction = conn.flow_direction,
                    valid = true,
                })
            else
                -- Try adjacent positions (connection point might be inside collision box)
                for _, dir_vec in pairs(geometry.DIRECTION_VECTORS) do
                    if count >= max_results then
                        break
                    end

                    local adjacent_pos = {
                        x = conn_pos.x + dir_vec.x,
                        y = conn_pos.y + dir_vec.y,
                    }

                    params.position = adjacent_pos
                    if surface.can_place_entity(params) then
                        count = count + 1
                        table.insert(positions, {
                            position = adjacent_pos,
                            connection_index = conn.connection_index,
                            fluidbox_index = conn.fluidbox_index,
                            flow_direction = conn.flow_direction,
                            offset_from_connection = dir_vec,
                            valid = true,
                        })
                    end
                end
            end
        end
    end

    return {
        source_name = source_name,
        source_position = source_position,
        target_name = target_name,
        positions = positions,
        count = count,
    }
end

-- ============================================================================
-- INSERTER PLACEMENT
-- ============================================================================

--- Get valid inserter placements between two entities
--- @param pickup_name string Entity to pick up from
--- @param pickup_position table Pickup entity position {x, y}
--- @param drop_name string Entity to drop into
--- @param drop_position table Drop entity position {x, y}
--- @param inserter_name string|nil Inserter type (default: "inserter")
--- @return table Array of {position, direction}
function M.get_inserter_placements(pickup_name, pickup_position, drop_name, drop_position, inserter_name)
    inserter_name = inserter_name or "inserter"

    -- Verify inserter prototype exists
    local inserter_proto = prototypes.entity[inserter_name]
    if not inserter_proto or inserter_proto.type ~= "inserter" then
        return {
            error = "Invalid inserter prototype: " .. tostring(inserter_name),
            positions = {},
        }
    end

    -- Get inserter reach from prototype
    local pickup_reach = inserter_proto.inserter_pickup_position
    local drop_reach = inserter_proto.inserter_drop_position

    if not pickup_reach or not drop_reach then
        return {
            error = "Inserter prototype missing pickup/drop position",
            positions = {},
        }
    end

    -- Find the two entities
    local pickup_entity = entity_lookup.find_entity(pickup_name, pickup_position)
    local drop_entity = entity_lookup.find_entity(drop_name, drop_position)

    if not pickup_entity or not pickup_entity.valid then
        return {
            error = "Pickup entity not found",
            positions = {},
        }
    end

    if not drop_entity or not drop_entity.valid then
        return {
            error = "Drop entity not found",
            positions = {},
        }
    end

    local surface = game.surfaces[1]
    local positions = {}
    local candidates_in_reach = 0  -- Track how many pass reach check
    local candidates_blocked = 0   -- Track how many fail placement check

    -- Calculate search area between the two entities
    local min_x = math.min(pickup_position.x, drop_position.x) - 2
    local max_x = math.max(pickup_position.x, drop_position.x) + 2
    local min_y = math.min(pickup_position.y, drop_position.y) - 2
    local max_y = math.max(pickup_position.y, drop_position.y) + 2

    -- Test positions in the search area
    for x = math.floor(min_x), math.floor(max_x) do
        for y = math.floor(min_y), math.floor(max_y) do
            local inserter_pos = {x = x + 0.5, y = y + 0.5}

            -- Test each cardinal direction
            for _, direction in ipairs(geometry.CARDINAL_DIRECTIONS) do
                -- Calculate where inserter would pickup from
                local rotated_pickup = geometry.rotate_vector(
                    {x = pickup_reach[1], y = pickup_reach[2]},
                    direction
                )
                local actual_pickup = geometry.add_offset(inserter_pos, rotated_pickup)

                -- Calculate where inserter would drop to
                local rotated_drop = geometry.rotate_vector(
                    {x = drop_reach[1], y = drop_reach[2]},
                    direction
                )
                local actual_drop = geometry.add_offset(inserter_pos, rotated_drop)

                -- Check if pickup position is near pickup entity
                local pickup_dist = geometry.distance(actual_pickup, pickup_position)
                -- Check if drop position is near drop entity
                local drop_dist = geometry.distance(actual_drop, drop_position)

                -- Allow 1.5 tile tolerance for reach
                if pickup_dist <= 1.5 and drop_dist <= 1.5 then
                    candidates_in_reach = candidates_in_reach + 1

                    -- Validate inserter placement
                    local params = {
                        name = inserter_name,
                        position = inserter_pos,
                        direction = direction,
                        force = "player",
                        build_check_type = defines.build_check_type.manual,
                    }

                    if surface.can_place_entity(params) then
                        table.insert(positions, {
                            position = inserter_pos,
                            direction = direction,
                            direction_name = geometry.DIRECTION_NAMES[direction],
                            pickup_position = actual_pickup,
                            drop_position = actual_drop,
                            valid = true,
                        })
                    else
                        candidates_blocked = candidates_blocked + 1
                    end
                end
            end
        end
    end

    -- Determine error if no valid positions found
    local error_msg = nil
    if #positions == 0 then
        if candidates_in_reach == 0 then
            error_msg = "Inserter cannot reach between these entities (gap too large for " .. inserter_name .. ")"
        else
            error_msg = "All " .. candidates_blocked .. " valid inserter positions are blocked by other entities"
        end
    end

    return {
        pickup_entity = {name = pickup_name, position = pickup_position},
        drop_entity = {name = drop_name, position = drop_position},
        inserter_name = inserter_name,
        positions = positions,
        count = #positions,
        candidates_in_reach = candidates_in_reach,
        candidates_blocked = candidates_blocked,
        error = error_msg,
    }
end

-- ============================================================================
-- ELECTRIC POLE CONNECTIONS
-- ============================================================================

--- Get valid pole positions to connect to an existing pole
--- @param source_name string Source pole entity name
--- @param source_position table Source pole position {x, y}
--- @param pole_name string Pole type to place
--- @param search_area table Area to search {left_top, right_bottom}
--- @param options table|nil {max_results: number}
--- @return table Array of {position, wire_distance, entities_in_supply_area}
function M.get_pole_connections(source_name, source_position, pole_name, search_area, options)
    options = options or {}
    local max_results = options.max_results or 20

    -- Get source pole info
    local source_info = entity_lookup.get_pole_info(source_name, source_position)
    if not source_info.entity_found then
        return {
            error = "Source pole not found at position",
            source_name = source_name,
            source_position = source_position,
            positions = {},
        }
    end

    -- Get target pole prototype info
    local pole_proto = prototypes.entity[pole_name]
    if not pole_proto then
        return {
            error = "Unknown pole prototype: " .. tostring(pole_name),
            positions = {},
        }
    end

    local target_wire_distance = pole_proto.get_max_wire_distance()
    local target_supply_distance = pole_proto.get_supply_area_distance()

    -- Max connection distance is min of both poles' wire distances
    local max_wire_distance = math.min(
        source_info.maximum_wire_distance or 10,
        target_wire_distance or 10
    )

    local surface = game.surfaces[1]

    -- Collect candidates within wire distance
    local candidates = {}

    for pos in geometry.iter_area_tiles(search_area) do
        local candidate_pos = {x = pos.x + 0.5, y = pos.y + 0.5}
        local distance = geometry.distance(source_position, candidate_pos)

        if distance > 0 and distance <= max_wire_distance then
            table.insert(candidates, {
                position = candidate_pos,
                wire_distance = distance,
            })
        end
    end

    -- Sort by distance (closest first)
    table.sort(candidates, function(a, b)
        return a.wire_distance < b.wire_distance
    end)

    -- Validate candidates
    local positions = {}
    local count = 0

    for _, candidate in ipairs(candidates) do
        if count >= max_results then
            break
        end

        local params = {
            name = pole_name,
            position = candidate.position,
            force = "player",
            build_check_type = defines.build_check_type.manual,
        }

        if surface.can_place_entity(params) then
            -- Count entities that would be in supply area
            local supply_area = geometry.bbox_from_center(
                candidate.position,
                target_supply_distance,
                target_supply_distance
            )

            local entities_in_supply = surface.count_entities_filtered({
                area = supply_area,
                force = "player",
            })

            count = count + 1
            table.insert(positions, {
                position = candidate.position,
                wire_distance = candidate.wire_distance,
                wire_distance_utilization = candidate.wire_distance / max_wire_distance,
                entities_in_supply_area = entities_in_supply,
                valid = true,
            })
        end
    end

    return {
        source_name = source_name,
        source_position = source_position,
        pole_name = pole_name,
        max_wire_distance = max_wire_distance,
        positions = positions,
        count = count,
    }
end

return M
