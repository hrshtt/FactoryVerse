local Action = require("core.action.Action")
local ParamSpec = require("core.action.ParamSpec")
local game_state = require("core.game_state.GameState")

--- @class WalkParams : ParamSpec
--- @field agent_id number
--- @field direction string|number
--- @field walking boolean|nil
--- @field ticks number|nil
local WalkParams = ParamSpec:new({
    agent_id = { type = "number", required = true },
    direction = { type = "string", required = true },
    walking = { type = "boolean", required = false },
    ticks = { type = "number", required = false },
})

--- @class WalkToParams : ParamSpec
--- @field agent_id number
--- @field goal {x:number,y:number}
--- @field arrive_radius number|nil
--- @field lookahead number|nil
--- @field replan_on_stuck boolean|nil
--- @field max_replans number|nil
--- @field debug boolean|nil
--- @field prefer_cardinal boolean|nil
--- @field diag_band number|nil
--- @field snap_axis_eps number|nil
local WalkToParams = ParamSpec:new({
    agent_id = { type = "number", required = true },
    goal = { type = "table", required = true },
    arrive_radius = { type = "number", required = false },
    lookahead = { type = "number", required = false },
    replan_on_stuck = { type = "boolean", required = false },
    max_replans = { type = "number", required = false },
    debug = { type = "boolean", required = false },
    prefer_cardinal = { type = "boolean", required = false },
    diag_band = { type = "number", required = false },
    snap_axis_eps = { type = "number", required = false },
})

--- Map common direction strings to defines.direction

local function normalize_direction(dir)
    if type(dir) == "number" then
        return dir
    end
    if type(dir) == "string" then
        local key = string.lower(dir)
        return game_state.aliases.direction[key]
    end
    return nil
end

-- ===== Helpers for walk_to =====
local function dist_sq(a, b)
    local dx, dy = (a.x - b.x), (a.y - b.y)
    return dx*dx + dy*dy
end

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

local function sign(x) if x < 0 then return -1 elseif x > 0 then return 1 else return 0 end end

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

-- ===== WalkTo action (plan + follow) =====

--- Internal job state
--- @class WalkToJob
--- @field id number
--- @field agent_id number
--- @field goal {x:number,y:number}
--- @field arrive_radius number
--- @field lookahead number
--- @field replan_on_stuck boolean
--- @field max_replans number
--- @field replans number
--- @field state "planning"|"following"|"arrived"|"failed"
--- @field req_id uint64|nil
--- @field waypoints table|nil
--- @field wp_index integer
--- @field last_pos {x:number,y:number}
--- @field last_goal_dist number
--- @field no_progress_ticks integer
--- @field current_dir defines.direction|nil
local function _new_walkto_job(agent_id, goal, opts)
    return {
        id = (storage.walk_to_next_id or 1),
        agent_id = agent_id,
        goal = { x = goal.x, y = goal.y },
        arrive_radius = (opts and opts.arrive_radius) or 0.7,
        lookahead = (opts and opts.lookahead) or 3.0,
        replan_on_stuck = (opts and opts.replan_on_stuck ~= false),
        max_replans = (opts and opts.max_replans) or 3,
        replans = 0,
        state = "planning",
        req_id = nil,
        waypoints = nil,
        wp_index = 1,
        last_pos = { x = goal.x, y = goal.y },
        last_goal_dist = math.huge,
        no_progress_ticks = 0,
        current_dir = nil,
        prefer_cardinal = (opts and opts.prefer_cardinal ~= false), -- default true
        diag_band = (opts and opts.diag_band) or 0.25,              -- 25% band around equal deltas
        snap_axis_eps = (opts and opts.snap_axis_eps) or 0.25       -- snap to axis near goal
    }
end

local function _get_control_for_agent(agent_id)
    local agent = storage.agent_characters and storage.agent_characters[agent_id] or nil
    if agent and agent.valid then return agent end
    return nil
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
        path_resolution_modifier = 0
    }
    job.req_id = req_id
    job.state = "planning"
end

local function _advance_waypoint(job, pos)
    if not (job.waypoints and job.waypoints[job.wp_index]) then return end
    local wp = job.waypoints[job.wp_index].position or job.waypoints[job.wp_index]
    while wp and dist_sq(pos, wp) <= 0.8*0.8 do
        job.wp_index = job.wp_index + 1
        wp = job.waypoints[job.wp_index] and (job.waypoints[job.wp_index].position or job.waypoints[job.wp_index]) or nil
    end
end

local function _current_target(job, pos)
    if job.waypoints and job.waypoints[job.wp_index] then
        local wp = job.waypoints[job.wp_index].position or job.waypoints[job.wp_index]
        return wp
    end
    return job.goal
end

local function _tick_follow(job, control)
    local pos = control.position
    -- arrival check
    if dist_sq(pos, job.goal) <= (job.arrive_radius * job.arrive_radius) then
        control.walking_state = { walking = false, direction = job.current_dir or defines.direction.north }
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

    control.walking_state = { walking = true, direction = next_dir }

    -- progress & stuck detection
    local goal_dist = math.sqrt(dist_sq(pos, job.goal))
    if goal_dist > job.last_goal_dist - 0.05 then
        job.no_progress_ticks = job.no_progress_ticks + 1
    else
        job.no_progress_ticks = 0
    end
    job.last_goal_dist = goal_dist

    if job.replan_on_stuck and job.no_progress_ticks >= 60 then
        if job.replans < job.max_replans then
            job.replans = job.replans + 1
            _request_path(job, control)
            job.no_progress_ticks = 0
        else
            job.state = "failed"
            control.walking_state = { walking = false, direction = job.current_dir or defines.direction.north }
        end
    end
end

--- @class WalkToAction : Action
--- @field validators table<function>
local WalkToAction = Action:new("agent.walk_to", WalkToParams)

--- @param params WalkToParams
--- @return boolean
function WalkToAction:run(params)
    local p = self:_pre_run(game_state, params)
    ---@cast p WalkToParams
    local agent_id = p.agent_id
    local goal = p.goal
    if not (goal and goal.x and goal.y) then return false end

    storage.walk_to_jobs = storage.walk_to_jobs or {}
    storage.walk_to_next_id = (storage.walk_to_next_id or 1)

    local job = _new_walkto_job(agent_id, goal, {
        arrive_radius = p.arrive_radius,
        lookahead = p.lookahead,
        replan_on_stuck = p.replan_on_stuck,
        max_replans = p.max_replans,
        prefer_cardinal = p.prefer_cardinal,
        diag_band = p.diag_band,
        snap_axis_eps = p.snap_axis_eps
    })
    job.id = storage.walk_to_next_id
    storage.walk_to_next_id = storage.walk_to_next_id + 1

    local control = _get_control_for_agent(agent_id)
    if not control then return false end
    job.last_pos = { x = control.position.x, y = control.position.y }
    job.last_goal_dist = math.sqrt(dist_sq(control.position, job.goal))

    storage.walk_to_jobs[job.id] = job
    _request_path(job, control) -- async; meanwhile we'll start walking directly

    return self:_post_run(true, p)
end

--- @class WalkAction : Action
--- @field validators table<function>
local WalkAction = Action:new("agent.walk", WalkParams)

--- @param params WalkParams
--- @return boolean
function WalkAction:run(params)
    local p = self:_pre_run(game_state, params)
    ---@cast p WalkParams
    local agent_id = p.agent_id
    local direction = normalize_direction(p.direction)
    local should_walk = p.walking

    if direction == nil then
        return false
    end

    local agent = game_state:agent_state():get_agent(agent_id)

    -- If ticks specified, register an intent to sustain walking each tick
    if p.ticks and p.ticks > 0 then
        storage.walk_intents = storage.walk_intents or {}
        storage.walk_intents[agent_id] = {
            direction = direction,
            end_tick = game.tick + p.ticks,
            walking = (should_walk ~= false)
        }
        -- Apply immediately this tick as well
        agent.walking_state = { walking = (should_walk ~= false), direction = direction }
        return true
    end

    -- One-shot set for this tick
    if should_walk == false then
        -- Stop walking and clear any intent
        if storage.walk_intents then
            storage.walk_intents[agent_id] = nil
        end
        local current_dir = (agent.walking_state and agent.walking_state.direction) or direction
        agent.walking_state = { walking = false, direction = current_dir }
    else
        agent.walking_state = { walking = true, direction = direction }
    end

    return self:_post_run(true, p)
end

local function on_tick_walk_intents(event)
    if not storage.walk_intents then return end

    local current_tick = game.tick
    local agent_ids = {}
    for agent_id, _ in pairs(storage.walk_intents) do agent_ids[#agent_ids+1] = agent_id end
    table.sort(agent_ids)
    for _, agent_id in ipairs(agent_ids) do
        local intent = storage.walk_intents[agent_id]
        if intent then
            if intent.end_tick and current_tick >= intent.end_tick then
                storage.walk_intents[agent_id] = nil
            else
                local control = _get_control_for_agent(agent_id)
                if control and control.walking_state ~= nil then
                    control.walking_state = {
                        walking = (intent.walking ~= false),
                        direction = intent.direction
                    }
                end
            end
        end
    end
end

local function on_tick_walk_to(event)
    if not storage.walk_to_jobs then return end
    local ids = {}
    for id, _ in pairs(storage.walk_to_jobs) do ids[#ids+1] = id end
    table.sort(ids)
    for _, id in ipairs(ids) do
        local job = storage.walk_to_jobs[id]
        if job then
            if job.state == "arrived" or job.state == "failed" then
                storage.walk_to_jobs[id] = nil
            else
                local control = _get_control_for_agent(job.agent_id)
                if control and control.valid then
                    _tick_follow(job, control)
                else
                    storage.walk_to_jobs[id] = nil
                end
            end
        end
    end
end

local function on_tick(event)
    -- Idempotency guard: prevent duplicate execution if event handlers were registered twice
    if storage._walk_tick_stamp == game.tick then return end
    storage._walk_tick_stamp = game.tick

    on_tick_walk_intents(event)
    on_tick_walk_to(event)
end

local function on_script_path_request_finished(e)
    if not (storage.walk_to_jobs and e and e.id) then return end
    storage._processed_path_evt = storage._processed_path_evt or {}
    if storage._processed_path_evt[e.id] then return end
    storage._processed_path_evt[e.id] = true
    for _, job in pairs(storage.walk_to_jobs) do
        if job.req_id == e.id then
            if e.path and #e.path > 0 then
                job.waypoints = e.path
                job.wp_index = 1
                job.state = "following"
            else
                -- Path failed; keep local steering, optionally mark failed if we insist
                if job.replan_on_stuck == false then
                    job.state = "failed"
                else
                    job.state = "following" -- continue greedy steering
                end
            end
            job.req_id = nil
            break
        end
    end
end

WalkAction.events = {
    [defines.events.on_tick] = on_tick,
    [defines.events.on_script_path_request_finished] = on_script_path_request_finished
}

return { WalkAction, WalkToAction }
