local Action = require("types.Action")
local GameStateAliases = require("game_state.GameStateAliases")

--- @class WalkParams : ParamSpec
--- @field agent_id number
--- @field direction string|number
--- @field walking boolean|nil
--- @field ticks number|nil
local WalkParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    direction = { type = "direction", required = true },
    walking = { type = "boolean", required = false },
    ticks = { type = "number", required = false },
})

--- @class WalkToParams : ParamSpec
--- @field agent_id number
--- @field position table Position to walk to: { x = number, y = number }
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
    position = { type = "position", required = true },
    arrive_radius = { type = "number", required = false },
    lookahead = { type = "number", required = false },
    replan_on_stuck = { type = "boolean", required = false },
    max_replans = { type = "number", required = false },
    debug = { type = "boolean", required = false },
    prefer_cardinal = { type = "boolean", required = false },
    diag_band = { type = "number", required = false },
    snap_axis_eps = { type = "number", required = false },
})

--- @class WalkToAction : Action
--- @field validators table<function>
local WalkToAction = Action:new("agent.walk_to", WalkToParams)

--- @param params WalkToParams
--- @return table|boolean Result with async contract or boolean for backwards compatibility
function WalkToAction:run(params)
    local p = self:_pre_run(params)
    ---@cast p WalkToParams
    local agent_id = p.agent_id
    local goal = p.position
    if not (goal and goal.x and goal.y) then return self:_post_run({ success = false }, p) end

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

    if job_id then
        -- Generate unique action_id from tick + agent_id
        -- Tick is captured at RCON invocation time, ensuring consistency
        -- between the queued response and eventual UDP completion
        local rcon_tick = game.tick
        local action_id = string.format("agent_walk_to_%d_%d", rcon_tick, agent_id)
        
        -- Store in progress tracking with both action_id and rcon_tick
        storage.walk_in_progress = storage.walk_in_progress or {}
        storage.walk_in_progress[agent_id] = { action_id = action_id, rcon_tick = rcon_tick }
        game.print(string.format("[walk_to_action] Queued walk for agent %d at tick %d: %s", agent_id, rcon_tick, action_id))
        
        -- Return async contract: queued + action_id for UDP tracking
        local result = {
            success = true,
            queued = true,
            action_id = action_id,
            tick = rcon_tick
        }
        return self:_post_run(result, p)
    else
        game.print(string.format("[walk_to_action] Failed to start job for agent %d", agent_id))
        return self:_post_run({ success = false }, p)
    end
end

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
