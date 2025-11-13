local AsyncAction = require("types.AsyncAction")
local GameContext = require("types.GameContext")

--- @class MineResourceParams : ParamSpec
--- @field agent_id number
--- @field position table Position of the resource: { x = number, y = number }
--- @field resource_name string
--- @field max_count number
--- @field debug boolean|nil
local MineResourceParams = AsyncAction.ParamSpec:new({
    agent_id = { type = "number", required = true },
    resource_name = { type = "string", required = true },
    position = { type = "position", required = false, default = nil },
    max_count = { type = "number", required = false, default = 10 },
})

--- @class MineCancelParams : ParamSpec
--- @field agent_id number
local MineCancelParams = AsyncAction.ParamSpec:new({
    agent_id = { type = "number", required = true },
})

--- @class MineResourceAction : AsyncAction
local MineResourceAction = AsyncAction:new("mine_resource", MineResourceParams, {
    cancel_params = MineCancelParams,
    cancel_storage_key = "mine_resource_in_progress",
    cancel_tracking_key_fn = function(cancel_params)
        return cancel_params.agent_id
    end,
})

local resource_type_mapping = {
    ["tree"] = "tree",
    ["rock"] = "simple-entity",
}

local resource_item_mapping = {
    ["tree"] = "wood",
    ["rock"] = "stone",
}

--- @class MiningContext
--- @field agent LuaEntity Agent character entity
--- @field resource_name string Resource name to mine
--- @field position table|nil Optional position of the resource: {x: number, y: number}
--- @field max_count number Maximum count to mine
--- @field params MineResourceParams ParamSpec instance for _post_run

--- Override _pre_run to build context using GameContext
--- @param params MineResourceParams|table|string
--- @return MiningContext
function MineResourceAction:_pre_run(params)
    -- Call parent to get validated ParamSpec
    local p = AsyncAction._pre_run(self, params)
    local params_table = p:get_values()
    
    -- Build context using GameContext
    local agent = GameContext.resolve_agent(params_table, self.game_state)
    
    -- Return context for run()
    return {
        agent = agent,
        resource_name = params_table.resource_name,
        position = params_table.position,
        max_count = params_table.max_count or 10,
        params = p
    }
end

--- @param params MineResourceParams|table|string
--- @return table
function MineResourceAction:run(params)
    --- @type MiningContext
    local context = self:_pre_run(params)
    
    if not context.agent or not context.agent.valid then
        return self:_post_run({ success = false, error = "Agent not found" }, context.params)
    end

    -- Validate: cannot mine oil
    if string.find(context.resource_name:lower(), "oil") then
        return self:_post_run({ success = false, error = "Cannot mine oil resources" }, context.params)
    end

    local max_count_valid = true
    local search_args = {}
    local is_point_entity = (context.resource_name == "tree" or context.resource_name == "rock")
    local radius = context.agent.resource_reach_distance
    
    local params_table = context.params:get_values()
    local job = {
        agent_id = params_table.agent_id,
        action_id = nil,  -- Will be set from generate_action_id
        start_tick = game.tick,
        initial_item_count = 0,
        item_name = nil,
        mine_till_count = nil,
        mine_till_depleted = false,
        cancelled = false,
        cancelled_tick = nil,
    }

    -- Build search arguments based on resource type and position
    if is_point_entity then
        -- Trees and rocks need position + radius (point entities)
        search_args.type = resource_type_mapping[context.resource_name]
        if context.position then
            search_args.position = context.position
            search_args.radius = radius
        else
            search_args.position = context.agent.position
            search_args.radius = radius
        end
        job.initial_item_count = context.agent.get_item_count(resource_item_mapping[context.resource_name])
        job.item_name = resource_item_mapping[context.resource_name]
    else
        -- Ores can use position or area (tile-based entities)
        search_args.name = context.resource_name
        if context.position then
            -- When position is provided, search in an area around that position
            local x = context.position.x
            local y = context.position.y
            search_args.area = { { x = x - radius, y = y - radius }, { x = x + radius, y = y + radius } }
        else
            -- When position not provided, search around agent
            local x = context.agent.position.x
            local y = context.agent.position.y
            search_args.area = { { x = x - radius, y = y - radius }, { x = x + radius, y = y + radius } }
        end
        job.initial_item_count = context.agent.get_item_count(context.resource_name)
        job.item_name = context.resource_name
    end

    local resource_entity = game.surfaces[1].find_entities_filtered(search_args)[1]
    if not resource_entity or not resource_entity.valid then
        return self:_post_run({ success = false, error = "Resource not found" }, context.params)
    end

    -- Validate reachability using agent.resource_reach_distance
    local agent_pos = context.agent.position
    local resource_pos = resource_entity.position
    local dx = resource_pos.x - agent_pos.x
    local dy = resource_pos.y - agent_pos.y
    local dist_sq = dx * dx + dy * dy
    local reach = context.agent.resource_reach_distance
    if dist_sq > (reach * reach) then
        return self:_post_run({ success = false, error = "Resource out of reach" }, context.params)
    end

    if resource_entity.type == "tree" or resource_entity.type == "simple-entity" then
        max_count_valid = false
    end

    -- Generate action_id and store tracking using AsyncAction helpers
    local action_id, rcon_tick = self:generate_action_id(params_table.agent_id)
    job.action_id = action_id

    -- Store tracking with agent_id as key (1:1 per agent)
    self:store_tracking("mine_resource_in_progress", params_table.agent_id, action_id, rcon_tick, {
        agent_id = params_table.agent_id
    })

    -- Initialize job tracking
    if max_count_valid then
        job.mine_till_count = context.max_count + job.initial_item_count
    else
        job.mine_till_depleted = true
    end

    -- Start mining
    context.agent.update_selected_entity(resource_entity.position)
    context.agent.mining_state = { mining = true, position = context.agent.position }

    storage.mining_results = storage.mining_results or {}
    storage.mining_results[params_table.agent_id] = job

    -- Return async result using AsyncAction helper
    return self:_post_run(
        self:create_async_result(action_id, rcon_tick, {
            agent_id = params_table.agent_id,
            resource_name = context.resource_name,
            position = { x = resource_entity.position.x, y = resource_entity.position.y }
        }),
        context.params
    )
end

--- Cancel mining action
--- @param cancel_params MineCancelParams
--- @param tracking table|nil
--- @return table
function MineResourceAction:_do_cancel(cancel_params, tracking)
    game.print("Cancelling mining action")
    local agent_id = cancel_params.agent_id
    local agent = storage.agents[agent_id]
    
    if not agent or not agent.valid then
        return self:create_cancel_result(false, false, tracking and tracking.action_id, { error = "Agent not found or invalid" })
    end

    local job = storage.mining_results[agent_id]
    if not job then
        return self:create_cancel_result(false, false, tracking and tracking.action_id, { error = "No mining in progress for agent" })
    end

    agent.mining_state = { mining = false }
    agent.clear_selected_entity()
    job.cancelled = true
    job.cancelled_tick = game.tick
    storage.mining_results[agent_id] = job

    return self:create_cancel_result(true, true, tracking and tracking.action_id, {
        agent_id = agent_id,
        item_name = job.item_name
    })
end

return { action = MineResourceAction, params = MineResourceParams }
