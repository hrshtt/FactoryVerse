--- Agent walking state machine and navigation logic
--- Simplified implementation using Factorio's built-in pathfinding and walking_state persistence

local pairs = pairs
local math = math


--- Calculate squared distance between two positions
--- @param a {x:number, y:number}
--- @param b {x:number, y:number}
--- @return number
local function dist_sq(a, b)
    local dx, dy = (a.x - b.x), (a.y - b.y)
    return dx*dx + dy*dy
end

local M = {}

-- ============================================================================
-- SIMPLE DIRECTION CALCULATION
-- ============================================================================

--- Calculate direction enum from position to target
--- @param from {x:number, y:number}
--- @param to {x:number, y:number}
--- @return defines.direction|nil
local function direction_to_target(from, to)
    local dx, dy = to.x - from.x, to.y - from.y
    if dx == 0 and dy == 0 then return nil end
    
    local angle = math.atan2(dy, dx)  -- 0=east, pi/2=south
    -- Convert angle to 8-direction enum
    -- Add pi/8 to center each octant, then divide by pi/4
    local oct = math.floor(((angle + math.pi/8) % (2*math.pi)) / (math.pi/4))
    
    local dir_map = {
        [0] = defines.direction.east,
        [1] = defines.direction.southeast,
        [2] = defines.direction.south,
        [3] = defines.direction.southwest,
        [4] = defines.direction.west,
        [5] = defines.direction.northwest,
        [6] = defines.direction.north,
        [7] = defines.direction.northeast
    }
    return dir_map[oct] or defines.direction.north
end

-- ============================================================================
-- PATHFINDING
-- ============================================================================

--- Request a path from Factorio's pathfinding system
--- @param job table
--- @param agent LuaEntity
local function _request_path(job, agent)
    if not (agent and agent.valid and agent.surface) then return end
    
    local proto = agent.prototype
    local req_id = agent.surface.request_path{
        start = agent.position,
        goal = job.goal,
        force = agent.force,
        bounding_box = proto and proto.collision_box or nil,
        collision_mask = proto and proto.collision_mask or nil,
        can_open_gates = true,
        radius = 1.0,  -- Use default radius
        entity_to_ignore = agent
    }
    job.req_id = req_id
    job.state = "planning"
end

-- ============================================================================
-- UDP COMPLETION NOTIFICATIONS
-- ============================================================================

--- Send UDP notification for walk completion
--- @param job table Walk job
--- @param success boolean Whether walk succeeded (true) or failed (false)
local function _send_walk_completion_udp(job, success)
    -- Get action tracking info (action_id + rcon_tick that queued this action)
    local tracking = nil
    local action_id = nil
    local rcon_tick = nil
    
    if storage.walk_in_progress then
        tracking = storage.walk_in_progress[job.agent_id]
        if tracking and type(tracking) == "table" then
            action_id = tracking.action_id
            rcon_tick = tracking.rcon_tick
        elseif tracking and type(tracking) == "string" then
            -- backwards compat: old format was just action_id string
            action_id = tracking
        end
        storage.walk_in_progress[job.agent_id] = nil
    end
    
    local completion_tick = game.tick
    
    local payload = {
        action_id = action_id or string.format("walk_unknown_%d_%d", rcon_tick or completion_tick, job.agent_id),
        agent_id = job.agent_id,
        action_type = "agent_walk_to",
        rcon_tick = rcon_tick or completion_tick,
        completion_tick = completion_tick,
        success = success,
        result = {
            agent_id = job.agent_id,
            goal = job.goal,
            reached = success,
            current_position = job.last_pos or job.goal
        }
    }
    
    local json_payload = helpers.table_to_json(payload)
    local ok, err = pcall(function() helpers.send_udp(34202, json_payload) end)
    if not ok then
        game.print(string.format("[UDP] ERROR sending walk completion: %s", err or "unknown"))
    end
end

-- ============================================================================
-- WALKING STATE MACHINE
-- ============================================================================

--- @class WalkingModule
--- @field agent_control table Interface with set_walking, stop_walking methods
--- @field start_walk_to_job fun(self: WalkingModule, agent_id: number, goal: {x:number, y:number}, options: table|nil): number|nil
--- @field cancel_walk_to fun(self: WalkingModule, agent_id: number)
--- @field get_event_handlers fun(self: WalkingModule, agent_control: table): table
--- @field tick_walk_intents fun(self: WalkingModule, event: table, agent_control: table)
--- @field tick_walk_to_jobs fun(self: WalkingModule, event: table, agent_control: table)
--- @field on_path_finished fun(self: WalkingModule, event: table)

--- Initialize walking module with agent control interface
--- @param agent_control table Interface with set_walking, stop_walking methods
function M:init(agent_control)
    self.agent_control = agent_control
end

--- Start a walk-to job for an agent
--- @param self WalkingModule
--- @param agent_id number
--- @param goal {x:number, y:number}
--- @param options table|nil Options: arrive_radius, replan_on_stuck, max_replans
--- @return number|nil job_id
function M:start_walk_to_job(agent_id, goal, options)
    if not (goal and goal.x and goal.y) then return nil end
    
    storage.walk_to_jobs = storage.walk_to_jobs or {}
    storage.walk_to_next_id = (storage.walk_to_next_id or 1)
    
    local opts = options or {}
    local agent = storage.agent_characters[agent_id]
    if not agent then return nil end
    
    -- Convert position to {x, y} format if needed
    local agent_pos = agent.position
    local cp = { x = agent_pos.x or agent_pos[1] or 0, y = agent_pos.y or agent_pos[2] or 0 }
    
    local job = {
        id = storage.walk_to_next_id,
        agent_id = agent_id,
        goal = { x = goal.x, y = goal.y },
        arrive_radius = opts.arrive_radius or 0.7,
        replan_on_stuck = opts.replan_on_stuck ~= false,
        max_replans = opts.max_replans or 3,
        replans = 0,
        state = "planning",
        req_id = nil,
        waypoints = nil,
        wp_index = 1,
        last_pos = { x = cp.x, y = cp.y },
        stuck_ticks = 0,
        current_dir = nil
    }
    
    local job_id = storage.walk_to_next_id
    storage.walk_to_next_id = storage.walk_to_next_id + 1
    
    storage.walk_to_jobs[job_id] = job
    _request_path(job, agent)
    
    return job_id
end

--- Cancel walk-to jobs for an agent
--- @param self WalkingModule
--- @param agent_id number
function M:cancel_walk_to(agent_id)
    if not storage.walk_to_jobs then return end
    for id, job in pairs(storage.walk_to_jobs) do
        if job and job.agent_id == agent_id then
            -- Stop walking before removing job
            if job.state == "following" then
                self.agent_control:set_walking(agent_id, job.current_dir or defines.direction.north, false)
            end
            storage.walk_to_jobs[id] = nil
        end
    end
end

--- Tick handler for following waypoints
--- @param agent_control table
--- @param job table
--- @param control LuaEntity
local function _tick_follow(agent_control, job, control)
    local pos = control.position
    local pos_normalized = { x = pos.x or pos[1] or 0, y = pos.y or pos[2] or 0 }
    
    -- Check if reached goal
    if dist_sq(pos_normalized, job.goal) <= (job.arrive_radius * job.arrive_radius) then
        agent_control:set_walking(job.agent_id, job.current_dir or defines.direction.north, false)
        job.state = "arrived"
        return
    end
    
    -- Remove waypoints we've passed
    if job.waypoints and job.waypoints[job.wp_index] then
        local wp_raw = job.waypoints[job.wp_index].position or job.waypoints[job.wp_index]
        local wp = { x = wp_raw.x or wp_raw[1] or 0, y = wp_raw.y or wp_raw[2] or 0 }
        if dist_sq(pos_normalized, wp) <= 0.5*0.5 then  -- Within 0.5 tiles
            job.wp_index = job.wp_index + 1
        end
    end
    
    -- Determine target (next waypoint or goal)
    local target = job.goal
    if job.waypoints and job.waypoints[job.wp_index] then
        local wp_raw = job.waypoints[job.wp_index].position or job.waypoints[job.wp_index]
        target = { x = wp_raw.x or wp_raw[1] or 0, y = wp_raw.y or wp_raw[2] or 0 }
    end
    
    -- Calculate direction to target
    local new_dir = direction_to_target(pos_normalized, target)
    if not new_dir then
        -- Already at target, should have been caught by arrival check
        return
    end
    
    -- Only update walking_state if direction changed (leverages persistence)
    if new_dir ~= job.current_dir then
        job.current_dir = new_dir
        agent_control:set_walking(job.agent_id, new_dir, true)
    end
    
    -- Simple stuck detection: check if position hasn't changed since last tick
    local last = job.last_pos
    if last then
        local dx, dy = pos_normalized.x - last.x, pos_normalized.y - last.y
        local step_len = math.sqrt(dx*dx + dy*dy)
        
        if step_len < 0.01 then
            job.stuck_ticks = (job.stuck_ticks or 0) + 1
        else
            job.stuck_ticks = 0
        end
    end
    
    -- Update last position for next tick
    job.last_pos = { x = pos_normalized.x, y = pos_normalized.y }
    
    -- Replan if stuck for 30 ticks
    if (job.stuck_ticks or 0) >= 30 then
        if job.replan_on_stuck and job.replans < job.max_replans then
            job.replans = job.replans + 1
            job.stuck_ticks = 0
            _request_path(job, control)
            job.state = "planning"
        else
            job.state = "failed"
            agent_control:set_walking(job.agent_id, job.current_dir or defines.direction.north, false)
        end
    end
end

--- Tick handler for walk intents (sustained walking)
--- @param self WalkingModule
--- @param event table
--- @param agent_control table Interface with set_walking method
function M:tick_walk_intents(event, agent_control)
    if not storage.walk_intents then return end
    if not game then return end
    
    local current_tick = game.tick
    for agent_id, intent in pairs(storage.walk_intents) do
        if intent.end_tick and current_tick >= intent.end_tick then
            storage.walk_intents[agent_id] = nil
        else
            agent_control:set_walking(agent_id, intent.direction, (intent.walking ~= false))
        end
    end
end

--- Tick handler for walk-to jobs
--- @param self WalkingModule
--- @param event table
--- @param agent_control table Interface with set_walking method
function M:tick_walk_to_jobs(event, agent_control)
    if not storage.walk_to_jobs then return end
    for id, job in pairs(storage.walk_to_jobs) do
        if job.state == "arrived" or job.state == "failed" then
            -- Send UDP completion notification
            local success = (job.state == "arrived")
            _send_walk_completion_udp(job, success)
            storage.walk_to_jobs[id] = nil
        elseif job.state == "following" then
            local agent = storage.agent_characters[job.agent_id]
            if not agent then return end
            if agent and agent.valid then
                _tick_follow(agent_control, job, agent)
            else
                -- Agent invalid, mark as failed
                job.state = "failed"
            end
        end
        -- "planning" state: waiting for path, do nothing
    end
end

--- Handle pathfinding callback
--- @param self WalkingModule
--- @param event table
function M:on_path_finished(event)
    if not (storage.walk_to_jobs and event and event.id) then return end
    for _, job in pairs(storage.walk_to_jobs) do
        if job.req_id == event.id then
            if event.path and #event.path > 0 then
                job.waypoints = event.path
                job.wp_index = 1
                job.state = "following"
            else
                -- Path failed
                if job.replan_on_stuck == false or job.replans >= job.max_replans then
                    job.state = "failed"
                else
                    -- Try replanning with current position
                    local agent = storage.agent_characters[job.agent_id]
                    if agent and agent.valid then
                        job.replans = job.replans + 1
                        _request_path(job, agent)
                        -- Stay in "planning" state
                    else
                        job.state = "failed"
                    end
                end
            end
            break
        end
    end
end

--- Get event handlers for walking activities
--- @param self WalkingModule
--- @param agent_control table Interface with set_walking method
--- @return table Event handlers keyed by event ID
function M:get_event_handlers(agent_control)
    return {
        [defines.events.on_tick] = function(event)
            self:tick_walk_intents(event, agent_control)
            self:tick_walk_to_jobs(event, agent_control)
        end,
        [defines.events.on_script_path_request_finished] = function(event)
            self:on_path_finished(event)
        end
    }
end

return M
