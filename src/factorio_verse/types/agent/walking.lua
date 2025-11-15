--- Agent walking action methods
--- Methods operate directly on Agent instances (self)
--- State is stored in self.walking (jobs, intent, next_job_id)
--- These methods are mixed into the Agent class at module level

local WalkingActions = {}

--- Start a walk-to job (async)
--- @param goal table Position {x, y}
--- @param options table|nil Walk options {arrive_radius, lookahead, replan_on_stuck, max_replans, prefer_cardinal, diag_band, snap_axis_eps}
--- @return table Result with {success, queued, action_id, tick, job_id}
function WalkingActions.walk_to(self, goal, options)
    if not (self.entity and self.entity.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    if not goal or type(goal.x) ~= "number" or type(goal.y) ~= "number" then
        error("Agent: Goal position {x, y} is required")
    end
    
    options = options or {}
    
    -- Generate job ID
    local job_id = self.walking.next_job_id
    self.walking.next_job_id = self.walking.next_job_id + 1
    
    -- Generate action ID for tracking
    local action_id = string.format("agent_walk_to_%d_%d", game.tick, self.agent_id)
    local rcon_tick = game.tick
    
    -- Create walk job
    local job = {
        job_id = job_id,
        goal = { x = goal.x, y = goal.y },
        action_id = action_id,
        start_tick = rcon_tick,
        arrive_radius = options.arrive_radius or 0.5,
        lookahead = options.lookahead or 2.0,
        replan_on_stuck = options.replan_on_stuck ~= false,
        max_replans = options.max_replans or 3,
        prefer_cardinal = options.prefer_cardinal ~= false,
        diag_band = options.diag_band or 0.1,
        snap_axis_eps = options.snap_axis_eps or 0.1,
        cancelled = false,
    }
    
    -- Store job
    self.walking.jobs[job_id] = job
    
    -- Enqueue async result message
    self:enqueue_message({
        action = "walk_to",
        agent_id = self.agent_id,
        success = true,
        queued = true,
        action_id = action_id,
        tick = rcon_tick,
        job_id = job_id,
        goal = { x = goal.x, y = goal.y },
    }, "walking")
    
    return {
        success = true,
        queued = true,
        action_id = action_id,
        tick = rcon_tick,
        job_id = job_id,
    }
end

--- Cancel a walk-to job
--- @param job_id number|nil If nil, cancels all walk-to jobs
--- @return table Result
function WalkingActions.cancel_walking(self, job_id)
    if not (self.entity and self.entity.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    local cancelled_jobs = {}
    
    if job_id then
        -- Cancel specific job
        local job = self.walking.jobs[job_id]
        if job then
            job.cancelled = true
            job.cancelled_tick = game.tick
            table.insert(cancelled_jobs, job_id)
            
            -- Remove from jobs table
            self.walking.jobs[job_id] = nil
        end
    else
        -- Cancel all jobs
        for id, job in pairs(self.walking.jobs) do
            job.cancelled = true
            job.cancelled_tick = game.tick
            table.insert(cancelled_jobs, id)
        end
        self.walking.jobs = {}
    end
    
    -- Clear sustained intent
    self.walking.intent = nil
    
    -- Stop walking on entity
    self:stop_walking()
    
    -- Enqueue cancel message
    self:enqueue_message({
        action = "cancel_walking",
        agent_id = self.agent_id,
        success = true,
        cancelled = #cancelled_jobs > 0,
        cancelled_jobs = cancelled_jobs,
        tick = game.tick or 0,
    }, "walking")
    
    return {
        success = true,
        cancelled = #cancelled_jobs > 0,
        cancelled_jobs = cancelled_jobs,
    }
end

--- Stop all walking activities (internal helper)
--- @return boolean
function WalkingActions.stop_walking(self)
    -- Clear sustained intent
    self.walking.intent = nil
    
    -- Stop walking on entity
    if self.entity and self.entity.valid then
        local current_dir = (self.entity.walking_state and self.entity.walking_state.direction) or defines.direction.north
        self.entity.walking_state = { walking = false, direction = current_dir }
    end
    
    return true
end

--- Set walking state for current tick (internal helper)
--- @param direction defines.direction|nil
--- @param walking boolean|nil
function WalkingActions.set_walking(self, direction, walking)
    if not (self.entity and self.entity.valid) then return end
    
    -- If starting to walk, stop mining per exclusivity policy
    if walking then
        if self.entity.mining_state and self.entity.mining_state.mining then
            self.entity.mining_state = { mining = false }
        end
    end
    
    -- Apply walking state
    local dir = direction or (self.entity.walking_state and self.entity.walking_state.direction) or defines.direction.north
    self.entity.walking_state = { walking = (walking ~= false), direction = dir }
end

--- Sustain walking for a number of ticks (internal helper)
--- @param direction defines.direction
--- @param ticks number
function WalkingActions.sustain_walking(self, direction, ticks)
    if not ticks or ticks <= 0 then return end
    
    local end_tick = (game and game.tick or 0) + ticks
    self.walking.intent = {
        direction = direction,
        end_tick = end_tick,
        walking = true
    }
    
    -- Apply immediately for current tick
    self:set_walking(direction, true)
end

--- Clear sustained walking intent (internal helper)
function WalkingActions.clear_walking_intent(self)
    self.walking.intent = nil
end

return WalkingActions

