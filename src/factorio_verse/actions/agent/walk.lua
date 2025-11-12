local Action = require("types.Action")
local GameContext = require("game_state.GameContext")
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
local WalkToAction = Action:new("agent.walk_to", WalkToParams)

--- @class WalkToContext
--- @field agent LuaEntity Agent character entity
--- @field position table Position to walk to: {x: number, y: number}
--- @field options table Walk options
--- @field params WalkToParams ParamSpec instance for _post_run

--- Override _pre_run to build context using GameContext
--- @param params WalkToParams|table|string
--- @return WalkToContext
function WalkToAction:_pre_run(params)
    -- Call parent to get validated ParamSpec
    local p = Action._pre_run(self, params)
    local params_table = p:get_values()
    
    -- Build context using GameContext
    local agent = GameContext.resolve_agent(params_table, self.game_state)
    
    -- Return context for run()
    return {
        agent = agent,
        position = params_table.position,
        options = {
            arrive_radius = params_table.arrive_radius,
            lookahead = params_table.lookahead,
            replan_on_stuck = params_table.replan_on_stuck,
            max_replans = params_table.max_replans,
            prefer_cardinal = params_table.prefer_cardinal,
            diag_band = params_table.diag_band,
            snap_axis_eps = params_table.snap_axis_eps
        },
        params = p
    }
end

--- @param params WalkToParams|table|string
--- @return table Result with async contract
function WalkToAction:run(params)
    --- @type WalkToContext
    local context = self:_pre_run(params)
    
    local params_table = context.params:get_values()
    local agent_id = params_table.agent_id
    local goal = context.position
    if not (goal and goal.x and goal.y) then return self:_post_run({ success = false }, context.params) end

    -- Delegate to AgentGameState for centralized state management
    local agent_state = self.game_state.agent
    local job_id = agent_state:start_walk_to_job(agent_id, goal, context.options)

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
        return self:_post_run(result, context.params)
    else
        game.print(string.format("[walk_to_action] Failed to start job for agent %d", agent_id))
        return self:_post_run({ success = false }, context.params)
    end
end

--- @class WalkCancelParams : ParamSpec
--- @field agent_id number
local WalkCancelParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
})

--- @class WalkCancelAction : Action
local WalkCancelAction = Action:new("agent.walk_cancel", WalkCancelParams)

--- @class WalkCancelContext
--- @field agent LuaEntity Agent character entity
--- @field params WalkCancelParams ParamSpec instance for _post_run

--- Override _pre_run to build context using GameContext
--- @param params WalkCancelParams|table|string
--- @return WalkCancelContext
function WalkCancelAction:_pre_run(params)
    -- Call parent to get validated ParamSpec
    local p = Action._pre_run(self, params)
    local params_table = p:get_values()
    
    -- Build context using GameContext
    local agent = GameContext.resolve_agent(params_table, self.game_state)
    
    -- Return context for run()
    return {
        agent = agent,
        params = p
    }
end

--- @param params WalkCancelParams|table|string
--- @return boolean
function WalkCancelAction:run(params)
    --- @type WalkCancelContext
    local context = self:_pre_run(params)
    
    local params_table = context.params:get_values()
    local agent_id = params_table.agent_id

    -- Delegate to AgentGameState for centralized state management
    local agent_state = self.game_state.agent
    agent_state:stop_walking(agent_id)

    return self:_post_run(true, context.params)
end

-- Event handlers removed - now handled by AgentGameState:get_activity_events()
-- WalkAction is kept internal-only (not exposed via remote interface)
-- while WalkToAction & WalkCancelAction are exposed via remote interface

return { WalkToAction, WalkCancelAction }
