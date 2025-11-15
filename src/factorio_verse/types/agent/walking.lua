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
        max_radius = math.max(max_radius, entity.get_radius())
    end

    return max_radius + 0.1
end


---@param self Agent
---@param goal {x:number, y:number}
---@param options table|nil
WalkingActions.walk_to = function(self, goal, adjust_to_non_colliding, options)
    if not goal then
        error("Goal is required")
    end

    adjust_to_non_colliding = adjust_to_non_colliding or false
    options = options or {}
    options.goal = goal
    options.start = self.entity.position
    options.bounding_box = self.entity.prototype.collision_box  -- Centered at {0,0}
    options.collision_mask = self.entity.prototype.collision_mask
    options.force = self.entity.force.name
    options.radius = get_goal_radius(self.entity.surface, goal)
    options.entity_to_ignore = self.entity

    game.print("walking options: " .. helpers.table_to_json(options))

    if options.radius > 0 and not adjust_to_non_colliding then
        error(
            "Cannot reach goal due to collisions. Provide adjust_to_non_colliding=true to adjust the goal position to a non-colliding position.")
    end

    if self.entity.walking_state["walking"] then
        error("Agent is already walking")
    end
    local job_id = self.entity.surface.request_path(options)
    self.walking.path_id = job_id
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

return WalkingActions
