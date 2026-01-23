--- Agent placement action methods
--- Methods operate directly on Agent instances (self)
--- These methods are mixed into the Agent class at module level

local custom_events = require("utils.custom_events")

local PlacementActions = {}

-- DEBUG FLAG
local DEBUG = false

--- Place an entity (sync)
--- @param self Agent
--- @param entity_name string Entity prototype name
--- @param position table Position {x, y}
--- @param direction number Direction (4=east, 6=west, 8=south, 10=north)
--- @param ghost boolean Whether to place a ghost entity
--- @return table Result with {success, position, entity_name, entity_type}
function PlacementActions.place_entity(self, entity_name, position, direction, ghost, label)
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end

    if not entity_name or type(entity_name) ~= "string" then
        error("Agent: entity_name (string) is required")
    end
    
    if not position or type(position.x) ~= "number" or type(position.y) ~= "number" then
        error("Agent: position {x, y} is required")
    end

    if direction and type(direction) ~= "number" then
        error("Agent: direction (number) must be nil or a number")
    end
    
    if ghost ~= nil and type(ghost) ~= "boolean" then
        error("Agent: ghost (boolean) must be nil or true/false")
    end

    ghost = ghost or false

    label = label or nil

    -- Validate agent can reach placement position
    if not ghost and not self:can_reach_position(position) then
        error("Agent: Placement position is out of reach: " .. position.x .. ", " .. position.y)
    end
    
    -- Validate entity prototype exists
    local proto = prototypes and prototypes.entity and prototypes.entity[entity_name]
    if not proto then
        error("Agent: Unknown entity prototype: " .. entity_name)
    end

    if not ghost then
        local item_count = self.character.get_main_inventory().get_item_count(entity_name)
        if item_count < 1 then
            error("Agent: Insufficient items in agent inventory (have " .. item_count .. ", need 1)")
        end
    end
    
    local can_place_params = {
        name = entity_name,
        position = position,
        direction = direction,
        force = self.character.force,
        build_check_type = defines.build_check_type.manual,
    }
    if ghost then
        can_place_params.build_check_type = defines.build_check_type.manual_ghost
    end

    -- Check if agent's own character might be blocking placement
    -- move_stuck_players in create_entity may not work for non-player characters,
    -- and can_place_entity has no way to account for character movement.
    -- Solution: temporarily teleport character out of the way for validation.
    local surface = game.surfaces[1]
    local original_char_pos = nil

    if proto.collision_box then
        local char_pos = self.character.position
        local cb = proto.collision_box
        -- Check if character center is within the entity's collision box at placement position
        local min_x = position.x + cb.left_top.x - 0.5  -- 0.5 buffer for character radius
        local max_x = position.x + cb.right_bottom.x + 0.5
        local min_y = position.y + cb.left_top.y - 0.5
        local max_y = position.y + cb.right_bottom.y + 0.5

        if char_pos.x >= min_x and char_pos.x <= max_x and
           char_pos.y >= min_y and char_pos.y <= max_y then
            -- Character is potentially blocking - teleport it out of the way
            original_char_pos = { x = char_pos.x, y = char_pos.y }

            -- Find a safe non-colliding position that's OUTSIDE the placement collision box.
            -- We search from a point offset from placement position, not from the center,
            -- because find_non_colliding_position may return the center itself if there's
            -- no entity collision there (e.g., on resource tiles like iron-ore).
            -- Search from 4 cardinal directions and pick the first valid one.
            local search_offset = math.max(
                math.abs(cb.right_bottom.x),
                math.abs(cb.right_bottom.y)
            ) + 1.5  -- Collision box extent + buffer for character radius

            local search_offsets = {
                {x = search_offset, y = 0},   -- East
                {x = -search_offset, y = 0},  -- West
                {x = 0, y = search_offset},   -- South
                {x = 0, y = -search_offset},  -- North
            }

            local safe_pos = nil
            for _, offset in ipairs(search_offsets) do
                local search_start = {
                    x = position.x + offset.x,
                    y = position.y + offset.y
                }
                local candidate = surface.find_non_colliding_position("character", search_start, 5, 0.5)
                if candidate then
                    -- Verify the candidate is actually outside the collision box
                    if candidate.x < min_x or candidate.x > max_x or
                       candidate.y < min_y or candidate.y > max_y then
                        safe_pos = candidate
                        break
                    end
                end
            end

            if not safe_pos then
                -- Fallback: search with larger radius from original position
                safe_pos = surface.find_non_colliding_position("character", char_pos, 10, 0.5)
                -- If still inside collision box, offset it
                if safe_pos and safe_pos.x >= min_x and safe_pos.x <= max_x and
                   safe_pos.y >= min_y and safe_pos.y <= max_y then
                    safe_pos = {x = max_x + 1, y = max_y + 1}
                end
            end

            if not safe_pos then
                error("Agent: Cannot find safe position to step back for placement at " .. position.x .. ", " .. position.y)
            end

            self.character.teleport(safe_pos)
            if DEBUG then
                game.print(string.format("[placement] Temporarily moved agent from (%f,%f) to (%f,%f) for placement check",
                    original_char_pos.x, original_char_pos.y, safe_pos.x, safe_pos.y))
            end
        end
    end

    local can_place = surface.can_place_entity(can_place_params)

    if not can_place then
        -- Restore character position if we moved it
        if original_char_pos then
            self.character.teleport(original_char_pos)
            if DEBUG then
                game.print(string.format("[placement] Restored agent to (%f,%f) after failed placement check",
                    original_char_pos.x, original_char_pos.y))
            end
        end
        -- TODO: Need to implement proper diagnostics for why it can't be placed
        error("Agent: Cannot place entity at position " .. position.x .. ", " .. position.y)
    end

    -- Note: We intentionally leave the character at the safe position if validation passed.
    -- create_entity will handle the final placement, and the character is already out of the way.
    
    -- Build placement parameters
    local placement = {
        name = entity_name,
        position = { x = position.x, y = position.y },
        force = self.character.force,
        direction = direction,
        source = self.character,
        fast_replace = true,
        raise_built = true,
        move_stuck_players = true,
    }
    
    if ghost then
        placement.inner_name = entity_name
        placement.name = "entity-ghost"
    end

    -- Check if there is already a ghost at the position and destroy it BEFORE placing entity
    -- We destroy first because can_place_entity already validated placement will succeed
    -- CRITICAL: fast_replace in create_entity does NOT raise destroy events, so we must manually destroy
    local existing_ghost = game.surfaces[1].find_entities_filtered({position=position, type="entity-ghost"})
    if #(existing_ghost) > 0 then
        for _, ghost_entity in pairs(existing_ghost) do
            if ghost_entity and ghost_entity.valid then
                if DEBUG then
                    game.print(string.format("[placement] Destroying ghost %s at (%f,%f) before placing entity", 
                        ghost_entity.ghost_name or "unknown", ghost_entity.position.x, ghost_entity.position.y))
                end
                -- Destroy with raise_destroy=true to trigger script_raised_destroy event
                -- This allows fv_snapshot to track ghost removal via Factorio's built-in event system
                local destroyed = ghost_entity.destroy({raise_destroy=true})
                if DEBUG then
                    game.print(string.format("[placement] Ghost destruction result: %s", tostring(destroyed)))
                end
            end
        end
    end

    -- Place entity (can_place_entity check ensures this will succeed)
    local created_entity = game.surfaces[1].create_entity(placement)
    if not created_entity or not created_entity.valid then
        error("Agent: Failed to place entity")
    end
    if not ghost then
        self.character.get_main_inventory().remove({ name = entity_name, count = 1 })
    end
    
    local entity_pos = { x = created_entity.position.x, y = created_entity.position.y }

    -- Raise agent entity built event for non-ghost entities (ghosts are handled separately)

    script.raise_event(custom_events.on_agent_entity_built, {
        agent_id = self.agent_id,
        entity = created_entity,
        is_ghost = ghost,
        label = label,
    })

    local message = {
        action = "place_entity",
        agent_id = self.agent_id,
        success = true,
        position = entity_pos,
        entity_name = entity_name,
        entity_type = created_entity.type,
    }

    if ghost then
        message.ghost = true
    end
    
    -- Enqueue completion message
    self:enqueue_message(message, "placement")
    
    return {
        success = true,
        position = entity_pos,
        entity_name = entity_name,
        entity_type = created_entity.type,
    }
end

return PlacementActions
