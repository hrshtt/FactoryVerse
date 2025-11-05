local Action = require("types.Action")
local GameStateAliases = require("game_state.GameStateAliases")

--- @class WalkParams : ParamSpec
--- @field agent_id number
--- @field direction string|number
--- @field walking boolean|nil
--- @field ticks number|nil
local WalkParams = Action.ParamSpec:new({
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
local WalkToParams = Action.ParamSpec:new({
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
        return GameStateAliases.direction[key]
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

--- @class WalkToAction : Action
--- @field validators table<function>
local WalkToAction = Action:new("agent.walk_to", WalkToParams)

--- @param params WalkToParams
--- @return boolean
function WalkToAction:run(params)
    local p = self:_pre_run(params)
    ---@cast p WalkToParams
    local agent_id = p.agent_id
    local goal = p.goal
    if not (goal and goal.x and goal.y) then return false end

    -- Delegate to AgentGameState for centralized state management
    local agent_state = self.game_state.agent
    local job_id = agent_state:start_walk_to_job(agent_id, goal, {
        arrive_radius = p.arrive_radius,
        lookahead = p.lookahead,
        replan_on_stuck = p.replan_on_stuck,
        max_replans = p.max_replans,
        prefer_cardinal = p.prefer_cardinal,
        diag_band = p.diag_band,
        snap_axis_eps = p.snap_axis_eps
    })

    return self:_post_run(job_id ~= nil, p)
end

--- @class WalkAction : Action
--- @field validators table<function>
local WalkAction = Action:new("agent.walk", WalkParams)

--- @param params WalkParams
--- @return boolean
function WalkAction:run(params)
    local p = self:_pre_run(params)
    ---@cast p WalkParams
    local agent_id = p.agent_id
    local direction = normalize_direction(p.direction)
    local should_walk = p.walking

    if direction == nil then
        return false
    end

    local agent_state = self.game_state.agent
    local agent = agent_state:get_agent(agent_id)

    -- If ticks specified, register an intent to sustain walking each tick
    if p.ticks and p.ticks > 0 then
        agent_state:sustain_walking(agent_id, direction, p.ticks)
        return true
    end

    -- One-shot set for this tick
    if should_walk == false then
        -- Stop walking and clear any intent
        agent_state:clear_walking_intent(agent_id)
        agent_state:set_walking(agent_id, direction, false)
    else
        agent_state:set_walking(agent_id, direction, true)
    end

    return self:_post_run(true, p)
end

-- Event handlers removed - now handled by AgentGameState:get_activity_events()

--- @class WalkCancelParams : ParamSpec
--- @field agent_id number
local WalkCancelParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
})

--- @class WalkCancelAction : Action
local WalkCancelAction = Action:new("agent.walk_cancel", WalkCancelParams)

--- @param params WalkCancelParams
--- @return boolean
function WalkCancelAction:run(params)
    local p = self:_pre_run(params)
    local agent_id = p.agent_id

    -- Delegate to AgentGameState for centralized state management
    local agent_state = self.game_state.agent
    agent_state:stop_walking(agent_id)

    return self:_post_run(true, p)
end

-- Event handlers removed - now handled by AgentGameState:get_activity_events()
-- WalkAction is kept internal-only (not exposed via remote interface)
-- while WalkToAction & WalkCancelAction are exposed via remote interface

return { WalkToAction, WalkCancelAction }
