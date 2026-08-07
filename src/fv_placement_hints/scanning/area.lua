--- Area Scanning Module
--- Provides placement validation and area scanning for entities
---
--- This module replicates what human players see when placing entities:
--- green tiles for valid placement, red for invalid.

local M = {}

local geometry = require("utils.geometry")
local entity_lookup = require("utils.entity_lookup")

-- ============================================================================
-- PLACEMENT VALIDATION
-- ============================================================================

--- Validate if a single position is valid for placement
--- @param entity_name string Entity prototype name
--- @param position table {x, y}
--- @param direction number|nil Direction (0=N, 4=E, 8=S, 12=W)
--- @param ghost boolean|nil Use ghost build check (default: false)
--- @return table {valid: bool, reason: string|nil}
function M.validate_placement(entity_name, position, direction, ghost)
    local proto = prototypes.entity[entity_name]
    if not proto then
        return {
            valid = false,
            reason = "unknown_prototype",
            message = "Unknown entity prototype: " .. tostring(entity_name),
        }
    end

    local surface = game.surfaces[1]
    local build_check = ghost and defines.build_check_type.manual_ghost or defines.build_check_type.manual

    local params = {
        name = entity_name,
        position = position,
        direction = direction,
        force = "player",
        build_check_type = build_check,
    }

    local can_place = surface.can_place_entity(params)

    if can_place then
        return {
            valid = true,
        }
    else
        -- TODO: Determine specific reason for failure
        -- This would require additional checks for:
        -- - collision with existing entities
        -- - wrong terrain type
        -- - missing resources (for drills)
        -- - missing water (for offshore pumps)
        return {
            valid = false,
            reason = "placement_blocked",
        }
    end
end

--- Batch validate multiple positions
--- @param entity_name string Entity prototype name
--- @param positions table Array of {x, y} positions
--- @param directions table|nil Array of directions (parallel to positions) or nil
--- @param ghost boolean|nil Use ghost build check (default: false)
--- @return table Array of booleans (parallel to positions)
function M.validate_positions(entity_name, positions, directions, ghost)
    local proto = prototypes.entity[entity_name]
    if not proto then
        -- Return all false for invalid prototype
        local results = {}
        for i = 1, #positions do
            results[i] = false
        end
        return results
    end

    local surface = game.surfaces[1]
    local build_check = ghost and defines.build_check_type.manual_ghost or defines.build_check_type.manual

    local results = {}
    for i, position in ipairs(positions) do
        local direction = directions and directions[i] or nil

        local params = {
            name = entity_name,
            position = position,
            direction = direction,
            force = "player",
            build_check_type = build_check,
        }

        results[i] = surface.can_place_entity(params)
    end

    return results
end

-- ============================================================================
-- AREA SCANNING
-- ============================================================================

--- Get valid placements in an area
--- @param entity_name string Entity prototype name
--- @param area table {left_top: {x,y}, right_bottom: {x,y}}
--- @param options table|nil {include_directions: bool, ghost: bool, max_results: number}
--- @return table Array of {position, direction, valid}
function M.get_valid_placements(entity_name, area, options)
    options = options or {}
    local include_directions = options.include_directions or false
    local ghost = options.ghost or false
    local max_results = options.max_results or nil

    local proto = prototypes.entity[entity_name]
    if not proto then
        return {
            error = "Unknown entity prototype: " .. tostring(entity_name),
            positions = {},
        }
    end

    local surface = game.surfaces[1]
    local build_check = ghost and defines.build_check_type.manual_ghost or defines.build_check_type.manual
    local is_directional = entity_lookup.entity_is_directional(entity_name)

    local positions = {}
    local count = 0

    -- Iterate over all tiles in area
    for pos in geometry.iter_area_tiles(area) do
        if max_results and count >= max_results then
            break
        end

        if is_directional and include_directions then
            -- Test all cardinal directions
            for _, direction in ipairs(geometry.CARDINAL_DIRECTIONS) do
                local params = {
                    name = entity_name,
                    position = pos,
                    direction = direction,
                    force = "player",
                    build_check_type = build_check,
                }

                if surface.can_place_entity(params) then
                    count = count + 1
                    table.insert(positions, {
                        position = {x = pos.x, y = pos.y},
                        direction = direction,
                        direction_name = geometry.DIRECTION_NAMES[direction],
                        valid = true,
                    })

                    if max_results and count >= max_results then
                        break
                    end
                end
            end
        else
            -- Test without direction or with first valid direction
            local direction = nil
            local valid = false

            if is_directional then
                -- Find first valid direction
                for _, dir in ipairs(geometry.CARDINAL_DIRECTIONS) do
                    local params = {
                        name = entity_name,
                        position = pos,
                        direction = dir,
                        force = "player",
                        build_check_type = build_check,
                    }

                    if surface.can_place_entity(params) then
                        direction = dir
                        valid = true
                        break
                    end
                end
            else
                -- Non-directional entity
                local params = {
                    name = entity_name,
                    position = pos,
                    force = "player",
                    build_check_type = build_check,
                }
                valid = surface.can_place_entity(params)
            end

            if valid then
                count = count + 1
                local result = {
                    position = {x = pos.x, y = pos.y},
                    valid = true,
                }
                if direction then
                    result.direction = direction
                    result.direction_name = geometry.DIRECTION_NAMES[direction]
                end
                table.insert(positions, result)
            end
        end
    end

    return {
        entity_name = entity_name,
        area = area,
        positions = positions,
        count = count,
    }
end

--- Get valid placements on resource tiles (for mining drills, pumpjacks)
--- @param entity_name string Entity prototype name
--- @param area table {left_top: {x,y}, right_bottom: {x,y}}
--- @param options table|nil {max_results: number}
--- @return table Array of {position, direction, resource_name, resource_amount}
function M.get_resource_placements(entity_name, area, options)
    options = options or {}
    local max_results = options.max_results or nil

    if not entity_lookup.entity_requires_resources(entity_name) then
        return {
            error = "Entity does not require resources: " .. tostring(entity_name),
            positions = {},
        }
    end

    local surface = game.surfaces[1]
    local build_check = defines.build_check_type.manual

    -- Find all resources in area
    local resources = surface.find_entities_filtered({
        area = area,
        type = "resource",
    })

    local positions = {}
    local count = 0
    local seen_positions = {}  -- Avoid duplicates

    for _, resource in ipairs(resources) do
        if max_results and count >= max_results then
            break
        end

        local pos = resource.position
        local pos_key = pos.x .. "," .. pos.y

        if not seen_positions[pos_key] then
            seen_positions[pos_key] = true

            local params = {
                name = entity_name,
                position = pos,
                force = "player",
                build_check_type = build_check,
            }

            if surface.can_place_entity(params) then
                count = count + 1
                table.insert(positions, {
                    position = {x = pos.x, y = pos.y},
                    resource_name = resource.name,
                    resource_amount = resource.amount,
                    valid = true,
                })
            end
        end
    end

    return {
        entity_name = entity_name,
        area = area,
        positions = positions,
        count = count,
    }
end

--- Get valid placements for water-requiring entities (offshore pumps)
--- @param entity_name string Entity prototype name
--- @param area table {left_top: {x,y}, right_bottom: {x,y}}
--- @param options table|nil {max_results: number}
--- @return table Array of {position, direction, approach_position}
function M.get_water_placements(entity_name, area, options)
    options = options or {}
    local max_results = options.max_results or nil

    if not entity_lookup.entity_requires_water(entity_name) then
        return {
            error = "Entity does not require water: " .. tostring(entity_name),
            positions = {},
        }
    end

    local surface = game.surfaces[1]
    local build_check = defines.build_check_type.manual

    local positions = {}
    local count = 0
    local approach_offsets = {
        {x = 0, y = -4}, {x = 4, y = 0},
        {x = -4, y = 0}, {x = 0, y = 4},
        {x = 3, y = -3}, {x = -3, y = -3},
        {x = 3, y = 3}, {x = -3, y = 3},
    }

    -- Iterate over all tiles in area
    for pos in geometry.iter_area_tiles(area) do
        if max_results and count >= max_results then
            break
        end

        -- Return the entity center Factorio will persist after placement,
        -- rather than the integer tile coordinate used by this area scan.
        local placement_position = geometry.snap_to_tile_center(pos)

        -- Test all cardinal directions for offshore pump
        for _, direction in ipairs(geometry.CARDINAL_DIRECTIONS) do
            local params = {
                name = entity_name,
                position = placement_position,
                direction = direction,
                force = "player",
                build_check_type = build_check,
            }

            if surface.can_place_entity(params) then
                -- The pump anchor can overlap water and is not a walking target.
                -- Find a standable character position close enough to build from,
                -- preferring points outside the pump footprint on every side.
                local approach_position = nil
                for _, offset in ipairs(approach_offsets) do
                    local search_start = {
                        x = placement_position.x + offset.x,
                        y = placement_position.y + offset.y,
                    }
                    approach_position = surface.find_non_colliding_position(
                        "character", search_start, 2, 0.5
                    )
                    if approach_position then
                        break
                    end
                end

                -- Only expose sites that the embodied actor can sensibly
                -- approach; a valid-but-inaccessible anchor is not actionable.
                if approach_position then
                    count = count + 1
                    table.insert(positions, {
                        position = {
                            x = placement_position.x,
                            y = placement_position.y,
                        },
                        direction = direction,
                        direction_name = geometry.DIRECTION_NAMES[direction],
                        approach_position = {
                            x = approach_position.x,
                            y = approach_position.y,
                        },
                        valid = true,
                    })
                    break  -- Only add once per position (first valid direction)
                end
            end
        end
    end

    return {
        entity_name = entity_name,
        area = area,
        positions = positions,
        count = count,
    }
end

--- Get detailed placement cue for a specific position
--- @param entity_name string Entity prototype name
--- @param position table {x, y}
--- @param direction number|nil Direction to check
--- @return table Rich placement info
function M.get_placement_cue(entity_name, position, direction)
    local proto = prototypes.entity[entity_name]
    if not proto then
        return {
            valid = false,
            reason = "unknown_prototype",
            message = "Unknown entity prototype: " .. tostring(entity_name),
        }
    end

    local surface = game.surfaces[1]
    local is_directional = entity_lookup.entity_is_directional(entity_name)

    local result = {
        entity_name = entity_name,
        position = position,
        valid = false,
        valid_directions = {},
        colliding_entities = {},
        footprint = geometry.get_entity_footprint(entity_name, position, direction),
    }

    -- Test requested direction or all cardinal directions
    local directions_to_test = {}
    if direction then
        table.insert(directions_to_test, direction)
    elseif is_directional then
        directions_to_test = geometry.CARDINAL_DIRECTIONS
    end
    -- Note: For non-directional entities, directions_to_test stays empty

    if #directions_to_test > 0 then
        -- Test each direction for directional entities
        for _, dir in ipairs(directions_to_test) do
            local params = {
                name = entity_name,
                position = position,
                direction = dir,
                force = "player",
                build_check_type = defines.build_check_type.manual,
            }

            if surface.can_place_entity(params) then
                result.valid = true
                table.insert(result.valid_directions, {
                    direction = dir,
                    direction_name = geometry.DIRECTION_NAMES[dir],
                })
            end
        end
    else
        -- Non-directional entity: test without direction
        local params = {
            name = entity_name,
            position = position,
            force = "player",
            build_check_type = defines.build_check_type.manual,
        }

        if surface.can_place_entity(params) then
            result.valid = true
        end
    end

    -- If not valid, find colliding entities
    if not result.valid then
        local footprint = result.footprint
        if footprint.bounding_box then
            local entities = surface.find_entities_filtered({
                area = footprint.bounding_box,
            })

            for _, entity in ipairs(entities) do
                if entity.valid and entity.name ~= "character" then
                    table.insert(result.colliding_entities, {
                        name = entity.name,
                        type = entity.type,
                        position = {x = entity.position.x, y = entity.position.y},
                    })
                end
            end
        end

        -- Determine reason
        if #result.colliding_entities > 0 then
            result.reason = "collision"
        elseif entity_lookup.entity_requires_resources(entity_name) then
            result.reason = "no_resources"
        elseif entity_lookup.entity_requires_water(entity_name) then
            result.reason = "no_water"
        else
            result.reason = "terrain"
        end
    end

    return result
end

return M
