--- Agent walking action methods
--- Methods operate directly on Agent instances (self)
--- State is stored in self.walking (path, path_id, progress)
--- These methods are mixed into the Agent class at module level

local WalkingActions = {}

DEBUG = true

local function get_goal_radius(surface, goal)
    local entities = surface.find_entities_filtered({ position = goal })
    if #entities == 0 then return 0.0 end

    local max_radius = 0
    for _, entity in pairs(entities) do
        -- Get the entity's bounding box
        local bbox = entity.bounding_box
        
        -- Calculate how far the furthest corner is from the goal point
        local corners = {
            {x = bbox.left_top.x, y = bbox.left_top.y},
            {x = bbox.right_bottom.x, y = bbox.left_top.y},
            {x = bbox.left_top.x, y = bbox.right_bottom.y},
            {x = bbox.right_bottom.x, y = bbox.right_bottom.y}
        }
        
        for _, corner in pairs(corners) do
            local dx = corner.x - goal.x
            local dy = corner.y - goal.y
            local distance = math.sqrt(dx * dx + dy * dy)
            max_radius = math.max(max_radius, distance)
        end
    end
    
    return max_radius
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
    options.goal = goal
    options.start = self.character.position
    options.bounding_box = self.character.prototype.collision_box
    options.collision_mask = self.character.prototype.collision_mask
    options.force = self.character.force.name
    options.radius = get_goal_radius(self.character.surface, goal)
    options.entity_to_ignore = self.character -- entity pathfinding has to ignore itself 

    if options.radius > 0 and strict_goal then
        error(
            "There are entities at the goal position."
            ..
            "Provide strict_goal=false to approximate to non-colliding position.")
    end
    local job_id = self.character.surface.request_path(options)
    self.walking.path_id = job_id
    
    -- Generate action ID and store for completion tracking
    local action_id = string.format("walk_to_%d_%d", game.tick, self.agent_id)
    local rcon_tick = game.tick
    self.walking.action_id = action_id
    self.walking.start_tick = rcon_tick
    self.walking.goal = goal
    
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
        -- Walking completed - send completion message
        if walking.action_id then
            local actual_ticks = nil
            if walking.start_tick then
                actual_ticks = (game.tick or 0) - walking.start_tick
            end
            
            self:enqueue_message({
                action = "walk_to",
                agent_id = self.agent_id,
                action_id = walking.action_id,
                success = true,
                tick = game.tick or 0,
                position = { x = self.character.position.x, y = self.character.position.y },
                goal = walking.goal,
                actual_ticks = actual_ticks,
            }, "walking")
            
            -- Clear tracking
            walking.action_id = nil
            walking.start_tick = nil
            walking.goal = nil
        end
        
        walking.progress = 0
        walking.path = {}
        self.character.walking_state = { walking = false }
        return
    end

    local waypoint = path[walking.progress]
    local pos = self.character.position
    local dx, dy = waypoint.position.x - pos.x, waypoint.position.y - pos.y

    if dx * dx + dy * dy < 0.0625 then -- 0.25^2
        walking.progress = walking.progress + 1
        if walking.progress > #path then
            -- Walking completed - send completion message
            if walking.action_id then
                local actual_ticks = nil
                if walking.start_tick then
                    actual_ticks = (game.tick or 0) - walking.start_tick
                end
                
                self:enqueue_message({
                    action = "walk_to",
                    agent_id = self.agent_id,
                    action_id = walking.action_id,
                    success = true,
                    tick = game.tick or 0,
                    position = { x = self.character.position.x, y = self.character.position.y },
                    goal = walking.goal,
                    actual_ticks = actual_ticks,
                }, "walking")
                
                -- Clear tracking
                walking.action_id = nil
                walking.start_tick = nil
                walking.goal = nil
            end
            
            walking.progress = 0
            walking.path = {}
            self.character.walking_state = { walking = false }
            return
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
