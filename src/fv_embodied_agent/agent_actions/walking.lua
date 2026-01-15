--- Agent walking action methods
--- Methods operate directly on Agent instances (self)
--- State is stored in self.walking (path, path_id, progress)
--- These methods are mixed into the Agent class at module level
---
--- Entity-aware walking:
--- When entity_ref is provided, computes candidate approach tiles around entity
--- and tries each until path succeeds or all candidates exhausted.

local WalkingActions = {}

DEBUG = false

-- ============================================================================
-- TILE CANDIDATE COMPUTATION
-- ============================================================================

--- Check if a tile position is valid for agent to stand on
--- @param surface LuaSurface
--- @param tile_pos {x:number, y:number} Tile center position
--- @param agent LuaEntity Agent character
--- @return boolean True if tile is standable
local function is_tile_standable(surface, tile_pos, agent)
    -- Check tile itself (water, cliffs, etc.)
    local tile = surface.get_tile(tile_pos.x, tile_pos.y)
    if not tile or not tile.valid then
        return false
    end
    
    -- Check if tile has collision (water, cliffs, etc.)
    local tile_proto = tile.prototype
    if tile_proto and tile_proto.collision_mask then
        -- If tile collides with player-layer, skip it
        for layer, _ in pairs(tile_proto.collision_mask.layers or {}) do
            if layer == "player" or layer == "water_tile" or layer == "object" then
                return false
            end
        end
    end
    
    -- Check for entities on the tile that would block standing
    local entities_on_tile = surface.find_entities_filtered({
        position = tile_pos,
        radius = 0.4,  -- Slightly less than half a tile
    })
    
    for _, entity in pairs(entities_on_tile) do
        if entity.valid and entity ~= agent then
            local entity_type = entity.type
            -- Skip transport belts - don't want to stand on moving belts
            if entity_type == "transport-belt" or 
               entity_type == "underground-belt" or 
               entity_type == "splitter" or
               entity_type == "loader" or
               entity_type == "loader-1x1" then
                return false
            end
            -- Skip if entity has collision that would block agent
            if entity.prototype and entity.prototype.collision_mask then
                for layer, _ in pairs(entity.prototype.collision_mask.layers or {}) do
                    if layer == "player" or layer == "object" then
                        return false
                    end
                end
            end
        end
    end
    
    return true
end

--- Compute candidate approach tiles around an entity
--- @param surface LuaSurface
--- @param target_entity LuaEntity Target entity to approach
--- @param agent LuaEntity Agent character
--- @return table Array of {x, y} tile positions
local function compute_approach_candidates(surface, target_entity, agent)
    local candidates = {}
    local reach_distance = agent.reach_distance or 6
    local entity_pos = target_entity.position
    local entity_bb = target_entity.bounding_box
    
    -- Calculate entity bounds in tiles
    local min_x = math.floor(entity_bb.left_top.x)
    local max_x = math.ceil(entity_bb.right_bottom.x)
    local min_y = math.floor(entity_bb.left_top.y)
    local max_y = math.ceil(entity_bb.right_bottom.y)
    
    -- Search tiles around entity within reach distance
    -- Use integer tile coordinates with 0.5 offset for tile centers
    local search_radius = math.ceil(reach_distance) + 1
    
    for dx = -search_radius, search_radius do
        for dy = -search_radius, search_radius do
            local tile_x = math.floor(entity_pos.x) + dx + 0.5
            local tile_y = math.floor(entity_pos.y) + dy + 0.5
            local tile_pos = {x = tile_x, y = tile_y}
            
            -- Skip tiles inside entity bounding box
            if tile_x > min_x and tile_x < max_x and
               tile_y > min_y and tile_y < max_y then
                goto continue
            end
            
            -- Check if agent at this tile could reach the entity
            local dist_to_entity = math.sqrt(
                (tile_x - entity_pos.x)^2 + (tile_y - entity_pos.y)^2
            )
            if dist_to_entity > reach_distance then
                goto continue
            end
            
            -- Check if tile is standable
            if not is_tile_standable(surface, tile_pos, agent) then
                goto continue
            end
            
            table.insert(candidates, tile_pos)
            
            ::continue::
        end
    end
    
    if DEBUG then
        game.print(string.format("Found %d candidate approach tiles for %s", 
            #candidates, target_entity.name))
    end
    
    return candidates
end

-- ============================================================================
-- DEPRECATED: Single perimeter goal (kept for position-only walking)
-- ============================================================================

--- Calculate a perimeter goal point outside an entity's collision box
--- @deprecated Use compute_approach_candidates for entity-aware walking
local function get_perimeter_goal(start_pos, target_entity, agent_collision_box)
    local bb = target_entity.bounding_box
    local target_radius = math.max(
        bb.right_bottom.x - bb.left_top.x,
        bb.right_bottom.y - bb.left_top.y
    ) / 2
    
    local agent_size = 0
    if agent_collision_box then
        agent_size = math.max(
            agent_collision_box.right_bottom.x - agent_collision_box.left_top.x,
            agent_collision_box.right_bottom.y - agent_collision_box.left_top.y
        ) / 2
    end
    
    local safe_distance = target_radius + agent_size + 0.5
    
    local vec = {
        x = start_pos.x - target_entity.position.x,
        y = start_pos.y - target_entity.position.y
    }
    
    local distance = math.sqrt(vec.x * vec.x + vec.y * vec.y)
    if distance < 0.001 then
        vec = {x = 1.0, y = 0.0}
        distance = 1.0
    end
    
    return {
        x = target_entity.position.x + (vec.x / distance) * safe_distance,
        y = target_entity.position.y + (vec.y / distance) * safe_distance
    }
end

--- Find entities at goal position and calculate perimeter goal if needed
--- @deprecated Use entity_ref parameter for entity-aware walking
local function find_and_adjust_goal(surface, goal, start_pos, agent_collision_box)
    local entities = surface.find_entities_filtered({ position = goal })
    if #entities == 0 then
        return nil, nil
    end
    
    local target_entity = nil
    for _, entity in pairs(entities) do
        if entity and entity.valid then
            target_entity = entity
            break
        end
    end
    
    if not target_entity then
        return nil, nil
    end
    
    local perimeter_goal = get_perimeter_goal(start_pos, target_entity, agent_collision_box)
    return perimeter_goal, target_entity
end

-- ============================================================================
-- WALK TO ACTION
-- ============================================================================

--- Walk to a goal position or entity
--- @param self Agent
--- @param goal {x:number, y:number} Goal position
--- @param strict_goal boolean If true, fail if exact position unreachable
--- @param options table|nil Additional pathfinding options
--- @param entity_ref {name:string, position:{x:number,y:number}}|nil Entity reference for entity-aware walking
WalkingActions.walk_to = function(self, goal, strict_goal, options, entity_ref)

    if self.character.walking_state["walking"] then
        error("Agent is already walking")
    end

    if not goal then
        error("Goal is required")
    end

    strict_goal = strict_goal or false
    options = options or {}
    options.start = self.character.position
    options.bounding_box = self.character.prototype.collision_box
    -- Prepare collision mask - explicitly include layers to avoid shipwrecks/obstacles
    -- request_path sometimes needs explicit layers even if character prototype has them
    local collision_mask = { layers = {} }
    
    -- 1. Start with character's base layers
    if self.character.prototype.collision_mask and self.character.prototype.collision_mask.layers then
        for layer, _ in pairs(self.character.prototype.collision_mask.layers) do
            collision_mask.layers[layer] = true
        end
    end
    
    -- 2. Explicitly force common obstacle layers (fixes issues with shipwrecks/debris)
    local force_layers = {
        "object",           -- Most entities
        "player",           -- Character/Player
        "water_tile",       -- Water
        "cliff",            -- Cliffs
        "train",            -- Trains
        "transport_belt"    -- Belts (optional but good for avoidance)
    }
    
    for _, layer in ipairs(force_layers) do
        collision_mask.layers[layer] = true
    end
    
    options.collision_mask = collision_mask
    options.force = self.character.force.name
    options.entity_to_ignore = self.character
    
    -- Generate action ID
    local action_id = string.format("walk_to_%d_%d", game.tick, self.agent_id)
    local rcon_tick = game.tick
    
    -- Initialize walking state
    self.walking.action_id = action_id
    self.walking.start_tick = rcon_tick
    self.walking.original_goal = goal
    self.walking.entity_ref = entity_ref
    self.walking.approach_candidates = nil
    self.walking.approach_index = 0
    self.walking.goal_entity = nil
    
    -- Entity-aware walking: resolve entity and compute candidates
    if entity_ref and entity_ref.name and entity_ref.position then
        local surface = self.character.surface
        local target_entity = surface.find_entity(entity_ref.name, entity_ref.position)
        
        if not target_entity or not target_entity.valid then
            -- Entity not found - immediate failure
            return {
                success = false,
                queued = false,
                action_id = action_id,
                tick = rcon_tick,
                failure_type = "entity_not_found",
                message = string.format("Entity '%s' not found at position (%.1f, %.1f)", 
                    entity_ref.name, entity_ref.position.x, entity_ref.position.y)
            }
        end
        
        -- Check if already in reach
        if self.character.can_reach_entity(target_entity) then
            -- Already reachable, no need to walk
            return {
                success = true,
                queued = false,
                action_id = action_id,
                tick = rcon_tick,
                position = {x = self.character.position.x, y = self.character.position.y},
                message = "Already in reach of entity"
            }
        end
        
        -- Compute candidate approach tiles
        local candidates = compute_approach_candidates(surface, target_entity, self.character)
        
        if #candidates == 0 then
            -- No standable tiles around entity
            return {
                success = false,
                queued = false,
                action_id = action_id,
                tick = rcon_tick,
                failure_type = "no_standable_tiles",
                message = string.format("No standable tiles within reach of '%s'", entity_ref.name)
            }
        end
        
        -- Store for fallback on path failure
        self.walking.goal_entity = target_entity
        self.walking.approach_candidates = candidates
        self.walking.approach_index = 1
        
        -- Use first candidate as goal
        options.goal = candidates[1]
        self.walking.goal = candidates[1]
        
        if DEBUG then
            game.print(string.format("Entity-aware walk: trying candidate 1/%d at (%.1f, %.1f)",
                #candidates, candidates[1].x, candidates[1].y))
        end
    else
        -- Position-only walking: use old perimeter goal logic
        local adjusted_goal, goal_entity = find_and_adjust_goal(
            self.character.surface,
            goal,
            self.character.position,
            self.character.prototype.collision_box
        )
        
        if adjusted_goal and goal_entity then
            if strict_goal then
                error(
                    "There are entities at the goal position. " ..
                    "Provide strict_goal=false to approximate to non-colliding position.")
            end
            options.goal = adjusted_goal
            self.walking.goal_entity = goal_entity
        else
            options.goal = goal
            self.walking.goal_entity = nil
        end
        self.walking.goal = options.goal
    end
    
    -- Store options for potential retry
    self.walking.path_options = {
        bounding_box = options.bounding_box,
        collision_mask = options.collision_mask,
        force = options.force,
        entity_to_ignore = self.character,
    }
    
    -- Request path
    local job_id = self.character.surface.request_path(options)
    self.walking.path_id = job_id
    
    -- Serialize entity_to_ignore for response
    local options_for_response = {}
    for k, v in pairs(options) do
        if k == "entity_to_ignore" then
            options_for_response[k] = v.name .. "_" .. (v.name_tag or "")
        else
            options_for_response[k] = v
        end
    end
    
    return {
        success = true,
        queued = true,
        action_id = action_id,
        tick = rcon_tick,
        result = {
            path_id = job_id,
            options_used = options_for_response,
            candidates_count = self.walking.approach_candidates and #self.walking.approach_candidates or 0,
        }
    }
end


-- Add to WalkingActions
WalkingActions.process_walking = function(self)
    local walking = self.walking
    if walking.progress == 0 or not walking.path then return end
    local path = walking.path

    if not path then
        error("No path found for Agent-" .. self.agent_id)
    end

    if not path or walking.progress > #path then
        -- Check if we need to validate distance to original goal entity
        local reached_goal = true
        if walking.goal_entity and walking.goal_entity.valid then
            -- Check if agent is within reach distance of the original goal entity
            local agent_pos = self.character.position
            local entity_pos = walking.goal_entity.position
            local dx = entity_pos.x - agent_pos.x
            local dy = entity_pos.y - agent_pos.y
            local distance = math.sqrt(dx * dx + dy * dy)
            
            -- Check if agent can reach the entity (within character's reach distance)
            local reach_distance = self.character.reach_distance or 2.5
            reached_goal = distance <= reach_distance
            
            -- If not close enough, continue walking toward the entity
            if not reached_goal then
                local last_distance = walking.last_distance_to_entity or math.huge
                -- If we're not making progress AND we're reasonably close (within 2x reach distance),
                -- consider it complete to avoid infinite stuck state
                if distance >= last_distance and distance <= (reach_distance * 2) then
                    reached_goal = true
                elseif distance < last_distance then
                    walking.last_distance_to_entity = distance
                    -- Continue processing (don't mark as complete yet)
                    return
                else
                    -- Not making progress and still far, mark complete to avoid infinite loop
                    reached_goal = true
                end
            end
        end
        
        if reached_goal then
            -- Walking completed - send completion message
            if walking.action_id then
                local actual_ticks = nil
                if walking.start_tick then
                    actual_ticks = (game.tick or 0) - walking.start_tick
                end
                
                local reported_goal = walking.original_goal or walking.goal
                self:enqueue_message({
                    action = "walk_to",
                    agent_id = self.agent_id,
                    action_id = walking.action_id,
                    success = true,
                    status = "completed",
                    tick = game.tick or 0,
                    position = { x = self.character.position.x, y = self.character.position.y },
                    goal = reported_goal,
                    actual_ticks = actual_ticks,
                }, "walking")
                
                -- Clear tracking
                walking.action_id = nil
                walking.start_tick = nil
                walking.goal = nil
                walking.original_goal = nil
                walking.goal_entity = nil
                walking.last_distance_to_entity = nil
            end
            
            walking.progress = 0
            walking.path = {}
            self.character.walking_state = { walking = false }
            
            return
        end
    end

    local waypoint = path[walking.progress]
    local pos = self.character.position
    local dx, dy = waypoint.position.x - pos.x, waypoint.position.y - pos.y

    if dx * dx + dy * dy < 0.0625 then -- 0.25^2
        walking.progress = walking.progress + 1
        if walking.progress > #path then
            -- All waypoints reached, check if we need to validate distance to original goal entity
            local reached_goal = true
            if walking.goal_entity and walking.goal_entity.valid then
                -- Check if agent is within reach distance of the original goal entity
                local agent_pos = self.character.position
                local entity_pos = walking.goal_entity.position
                local dx_entity = entity_pos.x - agent_pos.x
                local dy_entity = entity_pos.y - agent_pos.y
                local distance = math.sqrt(dx_entity * dx_entity + dy_entity * dy_entity)
                
                -- Check if agent can reach the entity (within character's reach distance)
                local reach_distance = self.character.reach_distance or 2.5
                reached_goal = distance <= reach_distance
                
                -- If not close enough, continue walking toward the entity
                if not reached_goal then
                    local last_distance = walking.last_distance_to_entity or math.huge
                    -- If we're not making progress AND we're reasonably close (within 2x reach distance),
                    -- consider it complete to avoid infinite stuck state
                    if distance >= last_distance and distance <= (reach_distance * 2) then
                        reached_goal = true
                    elseif distance < last_distance then
                        walking.last_distance_to_entity = distance
                        -- Continue processing (don't mark as complete yet)
                        -- Reset progress to keep walking
                        walking.progress = walking.progress - 1
                        return
                    else
                        -- Not making progress and still far, mark complete to avoid infinite loop
                        reached_goal = true
                    end
                end
            end
            
            if reached_goal then
                -- Walking completed - send completion message
                if walking.action_id then
                    local actual_ticks = nil
                    if walking.start_tick then
                        actual_ticks = (game.tick or 0) - walking.start_tick
                    end
                    
                    local reported_goal = walking.original_goal or walking.goal
                    self:enqueue_message({
                        action = "walk_to",
                        agent_id = self.agent_id,
                        action_id = walking.action_id,
                        success = true,
                        status = "completed",
                        tick = game.tick or 0,
                        position = { x = self.character.position.x, y = self.character.position.y },
                        goal = reported_goal,
                        actual_ticks = actual_ticks,
                    }, "walking")
                    
                    -- Clear tracking
                    walking.action_id = nil
                    walking.start_tick = nil
                    walking.goal = nil
                    walking.original_goal = nil
                    walking.goal_entity = nil
                    walking.last_distance_to_entity = nil
                end
                
                walking.progress = 0
                walking.path = {}
                self.character.walking_state = { walking = false }
                
                return
            end
        end
        waypoint = path[walking.progress]
        dx, dy = waypoint.position.x - pos.x, waypoint.position.y - pos.y
    end

    local angle = math.atan2(dy, -dx)
    local octant = (angle + math.pi) / (math.pi / 4) + 0.5
    local dirs = { defines.direction.east, defines.direction.northeast,
        defines.direction.north, defines.direction.northwest,
        defines.direction.west, defines.direction.southwest,
        defines.direction.south, defines.direction.southeast, }

    self:chart_view()
    self.character.walking_state = { walking = true, direction = dirs[math.floor(octant) % 8 + 1] }
end

WalkingActions.stop_walking = function(self)
    local is_walking = self.character.walking_state["walking"]
    if not is_walking then
        return {
            success = false,
            error = "Agent is not walking"
        }
    end
    
    -- Clear walking tracking (don't send completion message for cancellation)
    self.walking.action_id = nil
    self.walking.start_tick = nil
    self.walking.goal = nil
    self.walking.original_goal = nil
    self.walking.goal_entity = nil
    self.walking.last_distance_to_entity = nil
    
    self.character.walking_state = { walking = false }
    self.walking.path = nil
    self.walking.path_id = nil
    self.walking.progress = 0
    
    return {
        success = true,
        position = self.character.position
    }
end

return WalkingActions

