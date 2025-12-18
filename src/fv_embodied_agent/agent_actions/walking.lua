--- Agent walking action methods
--- Methods operate directly on Agent instances (self)
--- State is stored in self.walking (path, path_id, progress)
--- These methods are mixed into the Agent class at module level

local WalkingActions = {}

DEBUG = false

--- Calculate a perimeter goal point outside an entity's collision box
--- Returns a point on the edge of the entity closest to the start position
--- @param start_pos {x:number, y:number} Starting position
--- @param target_entity LuaEntity Target entity
--- @param agent_collision_box BoundingBox|nil Agent's collision box (centered at 0,0)
--- @return {x:number, y:number} Perimeter goal position
local function get_perimeter_goal(start_pos, target_entity, agent_collision_box)
    -- Get the radius of the target (approximate from bounding box)
    local bb = target_entity.bounding_box
    local target_radius = math.max(
        bb.right_bottom.x - bb.left_top.x,
        bb.right_bottom.y - bb.left_top.y
    ) / 2
    
    -- Calculate agent's collision box size
    local agent_size = 0
    if agent_collision_box then
        agent_size = math.max(
            agent_collision_box.right_bottom.x - agent_collision_box.left_top.x,
            agent_collision_box.right_bottom.y - agent_collision_box.left_top.y
        ) / 2
    end
    
    -- Add agent size + safety buffer so agent can stand outside the entity
    -- This ensures the agent can actually stand at the goal position
    local safe_distance = target_radius + agent_size + 0.5
    
    -- Get vector from target to start
    local vec = {
        x = start_pos.x - target_entity.position.x,
        y = start_pos.y - target_entity.position.y
    }
    
    -- Normalize and scale
    local distance = math.sqrt(vec.x * vec.x + vec.y * vec.y)
    if distance < 0.001 then
        -- If start and target are at same position, use a default direction
        vec = {x = 1.0, y = 0.0}
        distance = 1.0
    end
    
    local offset_x = (vec.x / distance) * safe_distance
    local offset_y = (vec.y / distance) * safe_distance
    
    -- New valid goal outside the entity
    return {
        x = target_entity.position.x + offset_x,
        y = target_entity.position.y + offset_y
    }
end

--- Find entities at goal position and calculate perimeter goal if needed
--- @param surface LuaSurface Surface to search
--- @param goal {x:number, y:number} Goal position
--- @param start_pos {x:number, y:number} Starting position
--- @param agent_collision_box BoundingBox|nil Agent's collision box (centered at 0,0)
--- @return {x:number, y:number}|nil Adjusted goal (nil if no entities found)
--- @return LuaEntity|nil Entity found at goal (nil if none)
local function find_and_adjust_goal(surface, goal, start_pos, agent_collision_box)
    local entities = surface.find_entities_filtered({ position = goal })
    if #entities == 0 then
        return nil, nil
    end
    
    -- Use the first valid entity found
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
    
    -- Calculate perimeter goal with agent collision box
    local perimeter_goal = get_perimeter_goal(start_pos, target_entity, agent_collision_box)
    return perimeter_goal, target_entity
end


---@param self Agent
---@param goal {x:number, y:number}
---@param options table|nil
WalkingActions.walk_to = function(self, goal, strict_goal, options)

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
    options.collision_mask = self.character.prototype.collision_mask
    options.force = self.character.force.name
    options.entity_to_ignore = self.character -- entity pathfinding has to ignore itself 
    
    -- Check if goal is inside an entity's collision box and calculate perimeter goal
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
        -- Use the perimeter goal for pathfinding
        options.goal = adjusted_goal
        -- Store original goal and entity for completion checking
        self.walking.original_goal = goal
        self.walking.goal_entity = goal_entity
    else
        -- No entities at goal, use goal as-is
        options.goal = goal
        self.walking.original_goal = nil
        self.walking.goal_entity = nil
    end
    local job_id = self.character.surface.request_path(options)
    self.walking.path_id = job_id
    
    -- Generate action ID and store for completion tracking
    local action_id = string.format("walk_to_%d_%d", game.tick, self.agent_id)
    local rcon_tick = game.tick
    self.walking.action_id = action_id
    self.walking.start_tick = rcon_tick
    -- Store the actual goal used for pathfinding (may be adjusted perimeter goal)
    self.walking.goal = options.goal
    
    options.entity_to_ignore = options.entity_to_ignore.name .. "_" .. options.entity_to_ignore.name_tag
    return {
        success = true,
        queued = true,
        action_id = action_id,
        tick = rcon_tick,
        result = {
            path_id = job_id,
            options_used = options,
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

