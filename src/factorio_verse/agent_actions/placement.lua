--- Agent placement action methods
--- Methods operate directly on Agent instances (self)
--- State is stored in self.placing (jobs, next_job_id)
--- These methods are mixed into the Agent class at module level

local PlacementActions = {}

--- Place an entity (sync)
--- @param self Agent
--- @param entity_name string Entity prototype name
--- @param position table Position {x, y}
--- @param options table|nil Placement options {direction, orient_towards}
--- @return table Result with {success, position, entity_name, entity_type}
function PlacementActions.place_entity(self, entity_name, position, options)
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    if not entity_name or type(entity_name) ~= "string" then
        error("Agent: entity_name (string) is required")
    end
    
    if not position or type(position.x) ~= "number" or type(position.y) ~= "number" then
        error("Agent: position {x, y} is required")
    end
    
    options = options or {}
    
    -- Validate entity prototype exists
    local proto = prototypes and prototypes.entity and prototypes.entity[entity_name]
    if not proto then
        error("Agent: Unknown entity prototype: " .. entity_name)
    end

    local item_count = self.character.get_main_inventory().get_item_count(entity_name)
    if item_count < 1 then
        error("Agent: Insufficient items in agent inventory (have " .. item_count .. ", need 1)")
    end
    
    local can_place_params = {
        name = entity_name,
        position = position,
        direction = options.direction,
        force = self.character.force,
        build_check_type = defines.build_check_type.manual,
    }

    if not game.surfaces[1].can_place_entity(can_place_params) then
        -- TODO: Need to implement proper diagnostics for why it can't be placed
        error("Agent: Cannot place entity at position " .. position.x .. ", " .. position.y)
    end
    
    -- Build placement parameters
    local placement = {
        name = entity_name,
        position = { x = position.x, y = position.y },
        force = self.character.force,
        source = self.character,
        fast_replace = true,
        raise_built = true,
        move_stuck_players = true,
    }
    
    -- Handle direction
    if options.direction ~= nil then
        placement.direction = options.direction
    elseif options.orient_towards then
        -- Derive direction from orient_towards
        local target_pos = nil
        
        if options.orient_towards.entity_name and options.orient_towards.position then
            local ok, ent = pcall(function()
                return game.surfaces[1].find_entity(options.orient_towards.entity_name, options.orient_towards.position)
            end)
            if ok and ent and ent.valid then
                target_pos = ent.position
            end
        end
        
        if not target_pos and options.orient_towards.position then
            target_pos = options.orient_towards.position
        end
        
        if target_pos then
            local dx = target_pos.x - placement.position.x
            local dy = target_pos.y - placement.position.y
            local angle = math.atan2(dy, dx)
            -- Convert angle to direction (0 = east, increments of 45 degrees)
            local dir_enum = math.floor((angle + math.pi) / (math.pi / 4) + 0.5) % 8
            placement.direction = dir_enum
        end
    end
    
    -- Place entity
    local created_entity = game.surfaces[1].create_entity(placement)
    if not created_entity or not created_entity.valid then
        error("Agent: Failed to place entity")
    end
    self.character.get_main_inventory().remove({ name = entity_name, count = 1 })
    
    local entity_pos = { x = created_entity.position.x, y = created_entity.position.y }

    
    -- Enqueue completion message
    self:enqueue_message({
        action = "place_entity",
        agent_id = self.agent_id,
        success = true,
        position = entity_pos,
        entity_name = entity_name,
        entity_type = created_entity.type,
        tick = game.tick or 0,
    }, "placement")
    
    return {
        success = true,
        position = entity_pos,
        entity_name = entity_name,
        entity_type = created_entity.type,
    }
end

--- Map entity names to required chunk resource categories
--- Structure: {category = "resource"|"water", name = resource_name|nil}
--- name is the ChunkTracker resource name (underscore format)
local entity_name_to_chunk_categories = {
    ["electric-mining-drill"] = {
        {category = "resource", name = "copper_ore"},
        {category = "resource", name = "iron_ore"},
        {category = "resource", name = "uranium_ore"},
        {category = "resource", name = "coal"},
        {category = "resource", name = "stone"},
    },
    ["pumpjack"] = {
        {category = "resource", name = "crude_oil"},
    },
    ["offshore-pump"] = {
        {category = "water", name = nil},
    },
}

--- Map Factorio resource entity names to ChunkTracker resource names
--- Converts hyphenated names to underscore names (e.g., "copper-ore" -> "copper_ore")
local function map_resource_name(factorio_name)
    local resource_map = {
        ["copper-ore"] = "copper_ore",
        ["iron-ore"] = "iron_ore",
        ["uranium-ore"] = "uranium_ore",
        ["coal"] = "coal",
        ["stone"] = "stone",
        ["crude-oil"] = "crude_oil"
    }
    return resource_map[factorio_name]
end

--- Get all tile positions in a chunk (for offshore-pump water scanning)
--- Chunk (x, y) covers tiles from (x*32, y*32) to ((x+1)*32 - 1, (y+1)*32 - 1) inclusive
--- @param chunk_key string Chunk key in format "x,y"
--- @return table Array of positions {x, y}
local function get_all_chunk_coordinates(chunk_key)
    local xstr, ystr = string.match(chunk_key, "([^,]+),([^,]+)")
    local chunk_x = tonumber(xstr)
    local chunk_y = tonumber(ystr)
    
    local coordinates = {}
    local x0 = chunk_x * 32
    local y0 = chunk_y * 32
    -- Chunk covers 32x32 tiles: from (x0, y0) to (x0+31, y0+31) inclusive
    for dx = 0, 31 do
        for dy = 0, 31 do
            table.insert(coordinates, { x = x0 + dx, y = y0 + dy })
        end
    end
    return coordinates
end

--- Get placement cues for an entity type
--- Returns valid positions where the entity can be placed based on chunk resource tracking
--- @param entity_name string Entity prototype name
--- @return table Array of {position = {x, y}, can_place = true}
function PlacementActions.get_placement_cues(self, entity_name)
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    local required_categories = entity_name_to_chunk_categories[entity_name]
    if not required_categories then
        game.print(string.format("[get_placement_cues] Unknown entity type: %s", entity_name))
        return {}  -- Unknown entity type, return empty
    end

    -- Get chunks in view (5x5 chunks around agent)
    -- Note: get_chunks_in_view is mixed into Agent from ChartingActions
    local chunks_in_view = self:get_chunks_in_view()
    game.print(string.format("[get_placement_cues] Chunks in view: %d", #chunks_in_view))
    
    local chunks_to_scan = {}
    
    -- Filter chunks that contain required resources
    for _, chunk in pairs(chunks_in_view) do
        local chunk_has_resource = false
        
        -- Check if chunk has ANY of the required resources (OR logic)
        for _, req in pairs(required_categories) do
            if storage.chunk_tracker and storage.chunk_tracker:chunk_has(req.category, req.name, chunk.x, chunk.y) then
                chunk_has_resource = true
                game.print(string.format("[get_placement_cues] Chunk (%d, %d) has %s/%s", chunk.x, chunk.y, req.category, req.name or "nil"))
                break
            end
        end
        
        if chunk_has_resource then
            table.insert(chunks_to_scan, {
                x = chunk.x,
                y = chunk.y,
                area = {
                    left_top = { x = chunk.x * 32, y = chunk.y * 32 },
                    right_bottom = { x = chunk.x * 32 + 31, y = chunk.y * 32 + 31 }
                }
            })
        end
    end
    
    game.print(string.format("[get_placement_cues] Chunks to scan: %d", #chunks_to_scan))
    for _, chunk in pairs(chunks_to_scan) do
        game.print(string.format("[get_placement_cues]   - Chunk (%d, %d): area TL=(%d, %d) BR=(%d, %d)", 
            chunk.x, chunk.y, 
            chunk.area.left_top.x, chunk.area.left_top.y,
            chunk.area.right_bottom.x, chunk.area.right_bottom.y))
    end

    local response = {}
    
    -- For offshore-pump: scan all positions in chunks with water
    -- Test 4 cardinal directions since offshore-pump must face water
    if entity_name == "offshore-pump" then
        local total_positions_checked = 0
        local total_positions_valid = 0
        -- Test only cardinal directions (north, east, south, west)
        local directions = {
            {enum = defines.direction.north, name = "north"},
            {enum = defines.direction.east, name = "east"},
            {enum = defines.direction.south, name = "south"},
            {enum = defines.direction.west, name = "west"}
        }
        for _, chunk in pairs(chunks_to_scan) do
            local chunk_key = chunk.x .. "," .. chunk.y
            local chunk_positions_checked = 0
            local chunk_positions_valid = 0
            for _, position in pairs(get_all_chunk_coordinates(chunk_key)) do
                total_positions_checked = total_positions_checked + 1
                chunk_positions_checked = chunk_positions_checked + 1
                
                -- Test each direction
                local found_valid = false
                for _, dir_info in pairs(directions) do
                    local params = {
                        name = entity_name,
                        position = position,
                        direction = dir_info.enum,
                        force = self.character.force,
                        build_check_type = defines.build_check_type.manual,
                    }
                    local can_place = game.surfaces[1].can_place_entity(params)
                    if can_place then
                        if not found_valid then
                            -- Only add position once (first valid direction found)
                            total_positions_valid = total_positions_valid + 1
                            chunk_positions_valid = chunk_positions_valid + 1
                            table.insert(response, {position = position, can_place = can_place, direction = dir_info.name})
                            found_valid = true
                        end
                    end
                end
            end
            game.print(string.format("[get_placement_cues] Chunk (%d, %d): checked %d positions, %d valid", 
                chunk.x, chunk.y, chunk_positions_checked, chunk_positions_valid))
        end
        game.print(string.format("[get_placement_cues] Total: checked %d positions, %d valid placements", 
            total_positions_checked, total_positions_valid))
    else
        -- For mining drills and pumpjacks: find resource entities and check placement at those positions
        local total_resources_found = 0
        local total_resources_matched = 0
        local total_positions_valid = 0
        for _, chunk in pairs(chunks_to_scan) do
            -- Find resource entities in chunk
            local resource_entities = game.surfaces[1].find_entities_filtered({
                area = chunk.area,
                type = "resource"
            })
            game.print(string.format("[get_placement_cues] Chunk (%d, %d): found %d resource entities", 
                chunk.x, chunk.y, #resource_entities))
            total_resources_found = total_resources_found + #resource_entities
            
            for _, resource_entity in pairs(resource_entities) do
                if resource_entity and resource_entity.valid then
                    -- Map Factorio resource entity name to ChunkTracker resource name
                    local tracker_resource_name = map_resource_name(resource_entity.name)
                    
                    -- Check if this resource type matches any of the required resources
                    local matches_requirement = false
                    for _, req in pairs(required_categories) do
                        if req.category == "resource" and req.name == tracker_resource_name then
                            matches_requirement = true
                            break
                        end
                    end
                    
                    if matches_requirement then
                        total_resources_matched = total_resources_matched + 1
                        local position = { x = resource_entity.position.x, y = resource_entity.position.y }
                        local params = {
                            name = entity_name,
                            position = position,
                            force = self.character.force,
                            build_check_type = defines.build_check_type.manual,
                        }
                        local can_place = game.surfaces[1].can_place_entity(params)
                        if can_place then
                            total_positions_valid = total_positions_valid + 1
                            -- Reuse resource_entity.name from find_entities_filtered response
                            table.insert(response, {
                                position = position, 
                                can_place = can_place,
                                resource_name = resource_entity.name
                            })
                        end
                    end
                end
            end
        end
        game.print(string.format("[get_placement_cues] Total: found %d resources, %d matched requirements, %d valid placements", 
            total_resources_found, total_resources_matched, total_positions_valid))
    end
    
    game.print(string.format("[get_placement_cues] Returning %d placement cues for %s", #response, entity_name))
    return response
end


return PlacementActions

