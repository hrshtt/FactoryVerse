--- Agent walking action methods
--- Methods operate directly on Agent instances (self)
--- State is stored in self.walking (jobs, intent, next_job_id)
--- These methods are mixed into the Agent class at module level

local WalkingActions = {}

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

    if self.entity.walking_state["walking"] then
        error("Agent is already walking")
    end

    if not goal then
        error("Goal is required")
    end

    strict_goal = strict_goal or false
    options = options or {}
    options.goal = goal
    options.start = self.entity.position
    options.bounding_box = self.entity.prototype.collision_box
    options.collision_mask = self.entity.prototype.collision_mask
    options.force = self.entity.force.name
    options.radius = get_goal_radius(self.entity.surface, goal)
    options.entity_to_ignore = self.entity -- entity pathfinding has to ignore itself 

    if options.radius > 0 and strict_goal then
        error(
            "There are entities at the goal position."
            ..
            "Provide strict_goal=false to approximate to non-colliding position.")
    end
    local job_id = self.entity.surface.request_path(options)
    self.walking.path_id = job_id
    options.entity_to_ignore = options.entity_to_ignore.name .. "_" .. options.entity_to_ignore.name_tag
    return {
        success = true,
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
        walking.progress = 0
        walking.path = {}
        self.entity.walking_state = { walking = false }
        return
    end

    local waypoint = path[walking.progress]
    local pos = self.entity.position
    local dx, dy = waypoint.position.x - pos.x, waypoint.position.y - pos.y

    if dx * dx + dy * dy < 0.0625 then -- 0.25^2
        walking.progress = walking.progress + 1
        if walking.progress > #path then
            walking.progress = 0
            walking.path = {}
            self.entity.walking_state = { walking = false }
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

    self.entity.walking_state = { walking = true, direction = dirs[math.floor(octant) % 8 + 1] }
end

WalkingActions.stop_walking = function(self)
    local is_walking = self.entity.walking_state["walking"]
    if not is_walking then
        return {
            success = false,
            error = "Agent is not walking"
        }
    end
    self.entity.walking_state = { walking = false }
    self.walking.path = nil
    self.walking.path_id = nil
    self.walking.progress = 0
    return {
        success = true,
        position = self.entity.position
    }
end

return WalkingActions
