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
function PlacementActions.place_entity(self, entity_name, position, direction, ghost)
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

    if not game.surfaces[1].can_place_entity(can_place_params) then
        -- TODO: Need to implement proper diagnostics for why it can't be placed
        error("Agent: Cannot place entity at position " .. position.x .. ", " .. position.y)
    end
    
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

    -- Place entity
    local created_entity = game.surfaces[1].create_entity(placement)
    if not created_entity or not created_entity.valid then
        error("Agent: Failed to place entity")
    end
    if not ghost then
        self.character.get_main_inventory().remove({ name = entity_name, count = 1 })
    end
    
    local entity_pos = { x = created_entity.position.x, y = created_entity.position.y }

    -- Raise agent entity built event for non-ghost entities (ghosts are handled separately)
    if not ghost and created_entity.type ~= "entity-ghost" then
        script.raise_event(custom_events.on_agent_entity_built, {
            entity = created_entity,
            agent_id = self.agent_id,
        })
    end

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

--- Determine if an entity requires resources for placement
--- @param entity_name string Entity prototype name
--- @return boolean True if entity needs resources (mining drills, pumpjacks)
local function entity_requires_resources(entity_name)
    -- Mining drills need ore/coal/stone resources
    if string.find(entity_name, "mining%-drill") then
        return true
    end
    -- Pumpjacks need crude oil
    if entity_name == "pumpjack" then
        return true
    end
    return false
end

--- Determine if an entity requires water for placement
--- @param entity_name string Entity prototype name
--- @return boolean True if entity needs water (offshore pumps)
local function entity_requires_water(entity_name)
    return entity_name == "offshore-pump"
end

--- Get all tile positions in a chunk
--- Chunk (x, y) covers tiles from (x*32, y*32) to ((x+1)*32 - 1, (y+1)*32 - 1) inclusive
--- @param chunk_x number Chunk X coordinate
--- @param chunk_y number Chunk Y coordinate
--- @return table Array of positions {x, y}
local function get_chunk_tile_positions(chunk_x, chunk_y)
    local positions = {}
    local x0 = chunk_x * 32
    local y0 = chunk_y * 32
    -- Chunk covers 32x32 tiles: from (x0, y0) to (x0+31, y0+31) inclusive
    for dx = 0, 31 do
        for dy = 0, 31 do
            table.insert(positions, { x = x0 + dx, y = y0 + dy })
        end
    end
    return positions
end

--- Get placement cues for an entity type
--- Scans chunks in view and returns valid placement positions
--- @param entity_name string Entity prototype name
--- @return table {positions: array, reachable_positions: array}
function PlacementActions.get_placement_cues(self, entity_name)
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    -- Validate entity prototype exists
    local proto = prototypes and prototypes.entity and prototypes.entity[entity_name]
    if not proto then
        error("Agent: Unknown entity prototype: " .. entity_name)
    end

    -- Get chunks in view (5x5 chunks around agent)
    local chunks_in_view = self:get_chunks_in_view()
    if DEBUG then
        game.print(string.format("[get_placement_cues] Entity: %s, Chunks in view: %d", entity_name, #chunks_in_view))
    end
    
    local all_positions = {}
    local requires_resources = entity_requires_resources(entity_name)
    local requires_water = entity_requires_water(entity_name)
    
    -- For each chunk in view, collect all valid positions
    for _, chunk in pairs(chunks_in_view) do
        local should_scan_chunk = false
        
        -- Determine if we should scan this chunk
        if requires_resources then
            -- Check if chunk has ANY resource entities
            local chunk_area = {
                left_top = { x = chunk.x * 32, y = chunk.y * 32 },
                right_bottom = { x = (chunk.x + 1) * 32, y = (chunk.y + 1) * 32 }
            }
            local resource_count = game.surfaces[1].count_entities_filtered({
                area = chunk_area,
                type = "resource"
            })
            should_scan_chunk = resource_count > 0
            
            if DEBUG and should_scan_chunk then
                game.print(string.format("[get_placement_cues] Chunk (%d, %d) has %d resources", 
                    chunk.x, chunk.y, resource_count))
            end
        elseif requires_water then
            -- Check if chunk has water (using chunk tracker)
            if storage.chunk_tracker and storage.chunk_tracker:chunk_has("water", nil, chunk.x, chunk.y) then
                should_scan_chunk = true
                if DEBUG then
                    game.print(string.format("[get_placement_cues] Chunk (%d, %d) has water", chunk.x, chunk.y))
                end
            end
        else
            -- For other entities, scan all chunks
            should_scan_chunk = true
        end
        
        -- Scan chunk if it meets requirements
        if should_scan_chunk then
            local chunk_valid_positions = 0
            
            if requires_water then
                -- For offshore pumps: test cardinal directions
                local directions = {
                    {enum = defines.direction.north, name = "north"},
                    {enum = defines.direction.east, name = "east"},
                    {enum = defines.direction.south, name = "south"},
                    {enum = defines.direction.west, name = "west"}
                }
                
                for _, position in pairs(get_chunk_tile_positions(chunk.x, chunk.y)) do
                    -- Test each direction
                    for _, dir_info in pairs(directions) do
                        local params = {
                            name = entity_name,
                            position = position,
                            direction = dir_info.enum,
                            force = self.character.force,
                            build_check_type = defines.build_check_type.manual,
                        }
                        if game.surfaces[1].can_place_entity(params) then
                            chunk_valid_positions = chunk_valid_positions + 1
                            table.insert(all_positions, {
                                position = position,
                                can_place = true,
                                direction = dir_info.name
                            })
                            break  -- Only add position once (first valid direction)
                        end
                    end
                end
            elseif requires_resources then
                -- For mining drills/pumpjacks: scan resource entity positions
                local chunk_area = {
                    left_top = { x = chunk.x * 32, y = chunk.y * 32 },
                    right_bottom = { x = (chunk.x + 1) * 32, y = (chunk.y + 1) * 32 }
                }
                local resource_entities = game.surfaces[1].find_entities_filtered({
                    area = chunk_area,
                    type = "resource"
                })
                
                for _, resource_entity in pairs(resource_entities) do
                    if resource_entity and resource_entity.valid then
                        local position = { x = resource_entity.position.x, y = resource_entity.position.y }
                        local params = {
                            name = entity_name,
                            position = position,
                            force = self.character.force,
                            build_check_type = defines.build_check_type.manual,
                        }
                        if game.surfaces[1].can_place_entity(params) then
                            chunk_valid_positions = chunk_valid_positions + 1
                            table.insert(all_positions, {
                                position = position,
                                can_place = true,
                                resource_name = resource_entity.name
                            })
                        end
                    end
                end
            else
                -- For other entities: scan all tile positions
                for _, position in pairs(get_chunk_tile_positions(chunk.x, chunk.y)) do
                    local params = {
                        name = entity_name,
                        position = position,
                        force = self.character.force,
                        build_check_type = defines.build_check_type.manual,
                    }
                    if game.surfaces[1].can_place_entity(params) then
                        chunk_valid_positions = chunk_valid_positions + 1
                        table.insert(all_positions, {
                            position = position,
                            can_place = true
                        })
                    end
                end
            end
            
            if DEBUG and chunk_valid_positions > 0 then
                game.print(string.format("[get_placement_cues] Chunk (%d, %d): %d valid positions", 
                    chunk.x, chunk.y, chunk_valid_positions))
            end
        end
    end
    
    -- Now scan reachable area separately
    local reachable_positions = {}
    local agent_pos = self.character.position
    local build_distance = self.character.build_distance or 10
    
    -- Define reachable bounding box
    local reachable_area = {
        left_top = { x = agent_pos.x - build_distance, y = agent_pos.y - build_distance },
        right_bottom = { x = agent_pos.x + build_distance, y = agent_pos.y + build_distance }
    }
    
    if DEBUG then
        game.print(string.format("[get_placement_cues] Scanning reachable area: build_distance=%d", build_distance))
    end
    
    -- Scan reachable area
    if requires_water then
        -- For offshore pumps: test cardinal directions in reachable area
        local directions = {
            {enum = defines.direction.north, name = "north"},
            {enum = defines.direction.east, name = "east"},
            {enum = defines.direction.south, name = "south"},
            {enum = defines.direction.west, name = "west"}
        }
        
        -- Scan tiles in reachable area
        for x = math.floor(reachable_area.left_top.x), math.floor(reachable_area.right_bottom.x) do
            for y = math.floor(reachable_area.left_top.y), math.floor(reachable_area.right_bottom.y) do
                local position = { x = x, y = y }
                -- Check if within reach
                if self:can_reach_position(position) then
                    for _, dir_info in pairs(directions) do
                        local params = {
                            name = entity_name,
                            position = position,
                            direction = dir_info.enum,
                            force = self.character.force,
                            build_check_type = defines.build_check_type.manual,
                        }
                        if game.surfaces[1].can_place_entity(params) then
                            table.insert(reachable_positions, {
                                position = position,
                                can_place = true,
                                direction = dir_info.name
                            })
                            break
                        end
                    end
                end
            end
        end
    elseif requires_resources then
        -- For mining drills/pumpjacks: find resources in reachable area
        local resource_entities = game.surfaces[1].find_entities_filtered({
            area = reachable_area,
            type = "resource"
        })
        
        for _, resource_entity in pairs(resource_entities) do
            if resource_entity and resource_entity.valid then
                local position = { x = resource_entity.position.x, y = resource_entity.position.y }
                if self:can_reach_position(position) then
                    local params = {
                        name = entity_name,
                        position = position,
                        force = self.character.force,
                        build_check_type = defines.build_check_type.manual,
                    }
                    if game.surfaces[1].can_place_entity(params) then
                        table.insert(reachable_positions, {
                            position = position,
                            can_place = true,
                            resource_name = resource_entity.name
                        })
                    end
                end
            end
        end
    else
        -- For other entities: scan all tiles in reachable area
        for x = math.floor(reachable_area.left_top.x), math.floor(reachable_area.right_bottom.x) do
            for y = math.floor(reachable_area.left_top.y), math.floor(reachable_area.right_bottom.y) do
                local position = { x = x, y = y }
                if self:can_reach_position(position) then
                    local params = {
                        name = entity_name,
                        position = position,
                        force = self.character.force,
                        build_check_type = defines.build_check_type.manual,
                    }
                    if game.surfaces[1].can_place_entity(params) then
                        table.insert(reachable_positions, {
                            position = position,
                            can_place = true
                        })
                    end
                end
            end
        end
    end
    
    if DEBUG then
        game.print(string.format("[get_placement_cues] Returning %d total positions, %d reachable", 
            #all_positions, #reachable_positions))
    end
    
    return {
        positions = all_positions,
        reachable_positions = reachable_positions
    }
end

return PlacementActions
