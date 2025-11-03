--- Agent walking state machine and navigation logic
--- Handles pathfinding, waypoint following, obstacle avoidance, and walking job management

-- Note: Do not capture 'game' at module level - it may be nil during on_load
-- Access 'game' directly in functions where it's guaranteed to be available (event handlers)
local pairs = pairs
local math = math

local helpers = require("game_state.agent.helpers")

local M = {}

-- ============================================================================
-- NAVIGATION HELPERS
-- ============================================================================

local DIR_IDX_TO_ENUM = {
    [0]=defines.direction.east,
    [1]=defines.direction.southeast,
    [2]=defines.direction.south,
    [3]=defines.direction.southwest,
    [4]=defines.direction.west,
    [5]=defines.direction.northwest,
    [6]=defines.direction.north,
    [7]=defines.direction.northeast
}

local ENUM_TO_DIR_IDX = {
    [defines.direction.east]=0,
    [defines.direction.southeast]=1,
    [defines.direction.south]=2,
    [defines.direction.southwest]=3,
    [defines.direction.west]=4,
    [defines.direction.northwest]=5,
    [defines.direction.north]=6,
    [defines.direction.northeast]=7
}

local DIRV = {
    [0] = { 1, 0}, [1] = { 1, 1},
    [2] = { 0, 1}, [3] = {-1, 1},
    [4] = {-1, 0}, [5] = {-1,-1},
    [6] = { 0,-1}, [7] = { 1,-1},
}

local function sign(x) if x < 0 then return -1 elseif x > 0 then return 1 else return 0 end end

local function _scale(v, s) return { v[1]*s, v[2]*s } end
local function _addp(p, v)  return { x = p.x + v[1], y = p.y + v[2] } end

local function desired_octant(from, to)
    local dx, dy = to.x - from.x, to.y - from.y  -- +x east, +y south
    if dx == 0 and dy == 0 then return nil end
    local a = math.atan2(dy, dx)                 -- 0=east, pi/2=south
    local oct = math.floor(((a + math.pi/8) % (2*math.pi)) / (math.pi/4))
    return oct
end

local function hysteresis_octant(curr_enum, desired_oct)
    if desired_oct == nil then return curr_enum end
    if not curr_enum then return DIR_IDX_TO_ENUM[desired_oct] end
    local curr_oct = ENUM_TO_DIR_IDX[curr_enum] or 0
    local step = (desired_oct - curr_oct) % 8
    -- Only switch if the desired octant differs by 2 or more "steps"
    if step == 1 or step == 7 then
        return curr_enum
    else
        return DIR_IDX_TO_ENUM[desired_oct]
    end
end

-- Manhattan-biased desired octant. alpha = diag_band (0.0..1.0), snap_eps ~ 0.1..0.5 tiles
local function desired_octant_manhattan(from, to, alpha, snap_eps, allow_diag)
    local dx, dy = to.x - from.x, to.y - from.y
    if dx == 0 and dy == 0 then return nil end
    local adx, ady = math.abs(dx), math.abs(dy)

    -- Axis snap near goal to prevent zig-zag landing
    if adx <= snap_eps then
        return (dy > 0) and 2 or 6 -- south or north
    end
    if ady <= snap_eps then
        return (dx > 0) and 0 or 4 -- east or west
    end

    -- Prefer cardinal unless deltas are very similar
    if adx > ady * (1 + alpha) then
        return (dx > 0) and 0 or 4
    elseif ady > adx * (1 + alpha) then
        return (dy > 0) and 2 or 6
    else
        if allow_diag then
            local sx, sy = sign(dx), sign(dy)
            if sx > 0 and sy < 0 then return 7      -- northeast
            elseif sx > 0 and sy > 0 then return 1  -- southeast
            elseif sx < 0 and sy > 0 then return 3  -- southwest
            else return 5                            -- northwest
            end
        else
            -- Fall back to the larger axis; tie-break horizontal
            if adx >= ady then
                return (dx > 0) and 0 or 4
            else
                return (dy > 0) and 2 or 6
            end
        end
    end
end

local function _bbox_radius_from_proto(proto)
    if not (proto and proto.collision_box) then return 0.6 end
    local bb = proto.collision_box
    local w = (bb.right_bottom.x - bb.left_top.x)
    local h = (bb.right_bottom.y - bb.left_top.y)
    local r = math.max(w, h) * 0.5 + 0.05
    return r
end

-- Forward declaration
local _current_target, _maybe_start_micro_detour

function _current_target(job, pos)
    if job.micro_goal then
        if helpers.dist_sq(pos, job.micro_goal) > 0.35*0.35 then
            return job.micro_goal
        end
        -- reached micro goal
        job.micro_goal = nil
        job.micro_timeout = 0
    end
    if job.waypoints and job.waypoints[job.wp_index] then
        local wp = job.waypoints[job.wp_index].position or job.waypoints[job.wp_index]
        return wp
    end
    return job.goal
end

-- Start a small perpendicular sidestep around an obstacle (deterministic left/right)
function _maybe_start_micro_detour(job, control, pos, curr_oct)
    if not (control and control.valid) then return false end
    -- Prefer cardinal notion of "forward"
    local f_oct = curr_oct
    if f_oct % 2 == 1 then
        -- diagonal: derive dominant axis from Manhattan intent
        -- pick nearest cardinal toward goal
        local tgt = _current_target and _current_target(job, pos) or job.goal
        local adx = math.abs(tgt.x - pos.x)
        local ady = math.abs(tgt.y - pos.y)
        if adx >= ady then f_oct = (tgt.x > pos.x) and 0 or 4 else f_oct = (tgt.y > pos.y) and 2 or 6 end
    end
    local left  = (f_oct + 6) % 8  -- 90° left
    local right = (f_oct + 2) % 8  -- 90° right
    local first, second = left, right
    if (job.id % 2) == 1 then first, second = right, left end  -- deterministic per job

    local step = 1.0
    local proto = control.prototype
    local name = control.name
    local surf = control.surface
    local radius = _bbox_radius_from_proto(proto)

    local function try_dir(oct)
        local off = _scale(DIRV[oct], step)
        local guess = _addp(pos, off)
        -- Nudge to a non-colliding position near the guess
        local ok = surf.find_non_colliding_position(name, guess, radius + 0.75, 0.25, true)
        if ok then
            job.micro_goal = ok
            job.micro_timeout = 120 -- 2 seconds at 60 tps
            return true
        end
        return false
    end

    return try_dir(first) or try_dir(second)
end

local function _advance_waypoint(job, pos)
    if not (job.waypoints and job.waypoints[job.wp_index]) then return end
    local wp = job.waypoints[job.wp_index].position or job.waypoints[job.wp_index]
    while wp and helpers.dist_sq(pos, wp) <= 0.8*0.8 do
        job.wp_index = job.wp_index + 1
        wp = job.waypoints[job.wp_index] and (job.waypoints[job.wp_index].position or job.waypoints[job.wp_index]) or nil
    end
end

local function _request_path(job, control)
    if not (control and control.valid and control.surface) then return end
    local proto = control.prototype  -- agent is a LuaEntity (character); prototype is deterministic
    local bbox = proto and proto.collision_box or nil
    local mask = proto and proto.collision_mask or nil
    local req_id = control.surface.request_path{
        start = control.position,
        goal = job.goal,
        force = control.force,
        bounding_box = bbox,
        collision_mask = mask,
        can_open_gates = true,
        path_resolution_modifier = (job.replans and job.replans > 0) and -2 or 0,
        radius = _bbox_radius_from_proto(proto),
        entity_to_ignore = control
    }
    job.req_id = req_id
    job.state = "planning"
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
--- @param options table|nil Options: arrive_radius, lookahead, replan_on_stuck, max_replans, prefer_cardinal, diag_band, snap_axis_eps
--- @return number|nil job_id
function M:start_walk_to_job(agent_id, goal, options)
    if not (goal and goal.x and goal.y) then return nil end
    
    storage.walk_to_jobs = storage.walk_to_jobs or {}
    storage.walk_to_next_id = (storage.walk_to_next_id or 1)
    
    local opts = options or {}
    local control = helpers.get_control_for_agent(agent_id)
    if not control then return nil end
    
    -- Convert position to {x, y} format if needed (handle MapPosition array format)
    local control_pos = control.position
    local cp = { x = control_pos.x or control_pos[1] or 0, y = control_pos.y or control_pos[2] or 0 }
    
    local job = {
        id = storage.walk_to_next_id,
        agent_id = agent_id,
        goal = { x = goal.x, y = goal.y },
        arrive_radius = opts.arrive_radius or 0.7,
        lookahead = opts.lookahead or 3.0,
        replan_on_stuck = opts.replan_on_stuck ~= false,
        max_replans = opts.max_replans or 3,
        replans = 0,
        state = "planning",
        req_id = nil,
        waypoints = nil,
        wp_index = 1,
        last_pos = { x = cp.x, y = cp.y },
        last_goal_dist = math.sqrt(helpers.dist_sq(cp, {x = goal.x, y = goal.y})),
        no_progress_ticks = 0,
        current_dir = nil,
        prefer_cardinal = opts.prefer_cardinal ~= false,
        diag_band = opts.diag_band or 0.25,
        snap_axis_eps = opts.snap_axis_eps or 0.25,
        micro_goal = nil,
        micro_timeout = 0,
        samepos_ticks = 0
    }
    
    local job_id = storage.walk_to_next_id
    storage.walk_to_next_id = storage.walk_to_next_id + 1
    
    storage.walk_to_jobs[job_id] = job
    _request_path(job, control)
    
    return job_id
end

--- Cancel walk-to jobs for an agent
--- @param self WalkingModule
--- @param agent_id number
function M:cancel_walk_to(agent_id)
    if not storage.walk_to_jobs then return end
    for id, job in pairs(storage.walk_to_jobs) do
        if job and job.agent_id == agent_id then
            storage.walk_to_jobs[id] = nil
        end
    end
end

local function _tick_follow(agent_control, job, control)
    local pos = control.position
    local last = job.last_pos or pos
    local dx, dy = pos.x - last.x, pos.y - last.y
    local step_len = math.sqrt(dx*dx + dy*dy)
    job.last_pos = { x = pos.x, y = pos.y }

    -- arrival check
    if helpers.dist_sq(pos, job.goal) <= (job.arrive_radius * job.arrive_radius) then
        agent_control:set_walking(job.agent_id, job.current_dir or defines.direction.north, false)
        job.state = "arrived"
        return
    end

    if job.waypoints then
        _advance_waypoint(job, pos)
    end

    -- choose direction with hysteresis
    local target = _current_target(job, pos)
    local desired_oct
    if job.prefer_cardinal then
        desired_oct = desired_octant_manhattan(pos, target, job.diag_band or 0.25, job.snap_axis_eps or 0.25, true)
    else
        desired_oct = desired_octant(pos, target)
    end
    local next_dir = hysteresis_octant(job.current_dir, desired_oct)
    job.current_dir = next_dir

    agent_control:set_walking(job.agent_id, next_dir, true)

    -- motion-based stuck detection (hard collision or tight alley)
    if step_len < 0.01 then
        job.samepos_ticks = (job.samepos_ticks or 0) + 1
    else
        job.samepos_ticks = 0
    end

    if job.micro_goal then
        job.micro_timeout = math.max(0, (job.micro_timeout or 0) - 1)
        if job.micro_timeout == 0 then
            job.micro_goal = nil
        end
    end

    if (job.samepos_ticks or 0) >= 15 and (not job.micro_goal) then
        local curr_oct = ENUM_TO_DIR_IDX[job.current_dir or next_dir] or 0
        local started = _maybe_start_micro_detour(job, control, pos, curr_oct)
        if not started then
            -- couldn't find sidestep; escalate to replan immediately
            if job.replans < job.max_replans then
                job.replans = job.replans + 1
                _request_path(job, control)
                job.no_progress_ticks = 0
                return
            else
                job.state = "failed"
                agent_control:set_walking(job.agent_id, job.current_dir or defines.direction.north, false)
                return
            end
        end
    end

    local goal_dist = math.sqrt(helpers.dist_sq(pos, job.goal))
    local improving = (goal_dist <= job.last_goal_dist - 0.02)
    if not improving and (not job.micro_goal) then
        job.no_progress_ticks = (job.no_progress_ticks or 0) + 1
    else
        job.no_progress_ticks = 0
    end
    job.last_goal_dist = goal_dist

    if job.replan_on_stuck and (job.no_progress_ticks or 0) >= 45 then
        if job.replans < job.max_replans then
            job.replans = job.replans + 1
            _request_path(job, control)
            job.no_progress_ticks = 0
            return
        else
            job.state = "failed"
            agent_control:set_walking(job.agent_id, job.current_dir or defines.direction.north, false)
            return
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

    -- Access game.tick directly when handler runs (not during closure creation)
    -- game is guaranteed to be available during event handlers
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
            storage.walk_to_jobs[id] = nil
        else
            local control = helpers.get_control_for_agent(job.agent_id)
            if control and control.valid then
                _tick_follow(agent_control, job, control)
            else
                storage.walk_to_jobs[id] = nil
            end
        end
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
                job.micro_goal = nil
                job.micro_timeout = 0
                job.state = "following"
            else
                -- Path failed; keep local steering, optionally mark failed if we insist
                if job.replan_on_stuck == false then
                    job.state = "failed"
                else
                    -- Keep trying with local steering
                    job.state = "following"
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

