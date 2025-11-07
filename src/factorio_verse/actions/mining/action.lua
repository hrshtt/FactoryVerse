local Action = require("types.Action")
local helpers = require("game_state.agent.helpers")

--- @class MineResourceParams : ParamSpec
--- @field agent_id number
--- @field position table Position of the resource: { x = number, y = number }
--- @field resource_name string
--- @field max_count number
--- @field walk_if_unreachable boolean|nil
--- @field debug boolean|nil
local MineResourceParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    position = { type = "table", required = true },
    resource_name = { type = "string", required = true },
    max_count = { type = "number", required = true },
    walk_if_unreachable = { type = "boolean", required = false, default = false },
    debug = { type = "boolean", required = false, default = false },
})

--- Internal per-agent job state
--- @class MineJob
--- @field agent_id number
--- @field target {x:number,y:number}
--- @field resource_name string
--- @field max_count number
--- @field mined_count number
--- @field products string[]|nil
--- @field start_total number|nil
--- @field start_item_count number|nil
--- @field finished boolean
local function _new_job(agent_id, pos, resource_name, max_count, walk_if_unreachable)
    return {
        agent_id = agent_id,
        target = { x = pos.x, y = pos.y },
        resource_name = resource_name,
        max_count = max_count,
        mined_count = 0,
        walk_if_unreachable = walk_if_unreachable and true or false,
        finished = false,
        -- no swing timer state required
        start_total = nil,
        start_item_count = nil,
        debug = false,
    }
end

local function _get_control_for_agent(agent_id)
    local agent = storage.agent_characters and storage.agent_characters[agent_id] or nil
    if agent and agent.valid then return agent end
    return nil
end

local function _distance(a, b)
    local dx, dy = (a.x - b.x), (a.y - b.y)
    return math.sqrt(dx*dx + dy*dy)
end


-- removed older single-item helpers; we now use _get_actor_items_total/_get_actor_item_count

-- Generic item count over list of product names for either LuaEntity character or LuaPlayer
local function _get_actor_items_total(actor, names)
    if not names or #names == 0 then return 0 end
    if not actor or not actor.valid then return 0 end
    local total = 0
    if actor.get_main_inventory then
        local inv = actor.get_main_inventory()
        if not inv then return 0 end
        local contents = inv.get_contents and inv.get_contents() or {}
        for _, n in ipairs(names) do total = total + (contents[n] or 0) end
        return total
    end
    if actor.get_inventory then
        local inv = actor.get_inventory(defines.inventory.character_main)
        if not inv then return 0 end
        local contents = inv.get_contents and inv.get_contents() or {}
        for _, n in ipairs(names) do total = total + (contents[n] or 0) end
        return total
    end
    return 0
end

local function _get_actor_item_count(actor, name)
    if not (actor and actor.valid and name) then return 0 end
    if actor.get_main_inventory then
        local inv = actor.get_main_inventory()
        if not inv then return 0 end
        return (inv.get_item_count and inv.get_item_count(name)) or 0
    end
    if actor.get_inventory then
        local inv = actor.get_inventory(defines.inventory.character_main)
        if not inv then return 0 end
        return (inv.get_item_count and inv.get_item_count(name)) or 0
    end
    return 0
end

local function _get_resource_products(resource)
    if not (resource and resource.valid) then return nil, false end
    local ok_props, props = pcall(function() return resource.prototype and resource.prototype.mineable_properties end)
    if not ok_props or not props then return { resource.name }, false end
    local requires_fluid = (props.required_fluid and (props.fluid_amount or 0) > 0) or false
    local names = {}
    if props.products and type(props.products) == "table" then
        for _, prod in ipairs(props.products) do
            if prod and prod.name then table.insert(names, prod.name) end
        end
    elseif props.product then
        table.insert(names, props.product)
    end
    if #names == 0 then table.insert(names, resource.name) end
    return names, requires_fluid
end

-- Compute number of ticks required to mine the entity, approximating player mining (60 tps)
-- Removed: fake swing timer path and player bind/unbind; we only emulate via mining_state and inventory deltas

-- Create a shared WalkHelper instance for mine_resource actions
local walk_helper = require("actions.agent.walk.helper"):new()


local function _cancel_walk_for_agent(agent_id)
    walk_helper:cancel_walk(agent_id)
end

-- Check if control can reach entity (uses shared helper with resource-specific reach)
local function _can_reach_entity(control, entity)
    if not (control and control.valid and entity and entity.valid) then return false end
    
    -- Try Factorio's built-in can_reach_entity first
    if control.can_reach_entity then
        local ok, res = pcall(function() return control.can_reach_entity(entity) end)
        if not ok then
            ok, res = pcall(function() return control.can_reach_entity(control, entity) end)
        end
        if ok and type(res) == "boolean" then return res end
    end
    
    -- Fallback to distance-based check with resource-specific reach distance
    local pos = entity.position or entity
    local reach = helpers.resource_reach_distance(control)
    return walk_helper:is_reachable(control, pos, nil, reach)
end

-- Removed player-mined event usage; character agents aren't players. Use inventory delta instead.

--- @class MineResourceAction : Action
local MineResourceAction = Action:new("mine_resource", MineResourceParams)

--- @param params MineResourceParams
--- @return boolean
function MineResourceAction:run(params)
    local p = self:_pre_run(params)
    ---@cast p MineResourceParams
    local agent_id = p.agent_id
    local target = { x = p.position.x, y = p.position.y }
    local resource_name = p.resource_name
    local max_count = p.max_count
    local emulate = true
    local debug = (p.debug == true)
    

    storage.mine_resource_jobs = storage.mine_resource_jobs or {}

    -- Initialize or replace existing job for this agent
    local job = _new_job(agent_id, target, resource_name, max_count, p.walk_if_unreachable)
    job.emulate = emulate
    job.debug = debug
    storage.mine_resource_jobs[agent_id] = job
    log(string.format("[mine_resource] start agent=%d target=(%.2f,%.2f) res=%s max=%d walk=%s", agent_id, target.x, target.y, resource_name, max_count, tostring(p.walk_if_unreachable)))

    local control = _get_control_for_agent(agent_id)
    if not control then
        storage.mine_resource_jobs[agent_id] = nil
        return self:_post_run(false, p)
    end
    
    local surface = control.surface
    local resource = helpers.find_resource_entity(surface, target, resource_name)
    if not (resource and resource.valid) then
        -- Resource not found at target location
        storage.mine_resource_jobs[agent_id] = nil
        return self:_post_run(false, p)
    end
    
    -- Precompute products and guard fluid requirement
    local names, requires_fluid = _get_resource_products(resource)
    if requires_fluid then
        log(string.format("[mine_resource] resource %s requires fluid; cannot hand-mine. Aborting job for agent=%d", resource_name, agent_id))
        storage.mine_resource_jobs[agent_id] = nil
        return self:_post_run(false, p)
    end
    
    job.products = names
    job.start_total = _get_actor_items_total(control, job.products)
    
    -- For trees: do NOT track resource_name as an item (trees are not items).
    -- Only track products (wood) and rely on entity disappearance for completion.
    -- For ores: track the resource item itself as a backup completion signal.
    if resource.type == "tree" then
        job.start_item_count = nil  -- Trees are not items; rely on entity depletion
    else
        job.start_item_count = _get_actor_item_count(control, job.resource_name)
    end

    -- Check if resource is reachable
    local reachable = _can_reach_entity(control, resource)
    if not reachable then
        -- Resource is not reachable
        if not job.walk_if_unreachable then
            -- Cannot reach and walk_if_unreachable is false - fail immediately
            storage.mine_resource_jobs[agent_id] = nil
            return self:_post_run(false, p)
        else
            -- Start walking toward the resource
            walk_helper:start_walk_to({
                agent_id = job.agent_id,
                target_position = job.target,
                arrive_radius = 1.2,
                prefer_cardinal = true
            })
        end
    else
        -- Resource is reachable - start mining immediately
        _cancel_walk_for_agent(agent_id)
        self.game_state.agent:set_mining(agent_id, true, resource)
        job.mining_active = true
        local target_pos = resource.position
        if control.update_selected_entity and target_pos then
            pcall(function() control.update_selected_entity(target_pos) end)
        end
        if control.mining_state ~= nil then
            control.mining_state = { mining = true, position = { x = target_pos.x, y = target_pos.y } }
        end
    end

    -- Delegate to AgentGameState for centralized state management
    local agent_state = self.game_state.agent
    local success = agent_state:start_mining_job(agent_id, target, resource_name, max_count, {
        walk_if_unreachable = p.walk_if_unreachable,
        debug = p.debug
    })
    
    if not success then
        storage.mine_resource_jobs[agent_id] = nil
        return self:_post_run(false, p)
    end

    -- Create async action contract result
    -- Mining is async and happens over multiple ticks
    -- Returns queued response immediately, completion sent via UDP
    if success then
        -- Generate unique action_id from tick + agent_id
        -- Tick is captured at RCON invocation time, ensuring consistency
        -- between the queued response and eventual UDP completion
        local rcon_tick = game.tick
        local action_id = string.format("mine_resource_%d_%d", rcon_tick, agent_id)
        
        -- Store in progress tracking to prevent concurrent mining of same resource
        storage.mine_resource_in_progress = storage.mine_resource_in_progress or {}
        local resource = helpers.find_resource_entity(surface, target, resource_name)
        if resource and resource.valid then
            local resource_key = resource.position.x .. "," .. resource.position.y
            storage.mine_resource_in_progress[resource_key] = { 
                action_id = action_id, 
                rcon_tick = rcon_tick 
            }
        end
        
        log(string.format("[mine_resource] Queued mining for agent %d at tick %d: %s", agent_id, rcon_tick, action_id))
        
        -- Return async contract: queued + action_id for UDP tracking
        local result = {
            success = true,
            queued = true,
            action_id = action_id,
            tick = rcon_tick
        }
        return self:_post_run(result, p)
    else
        -- Action failed to start
        return self:_post_run({ success = false }, p)
    end
end

-- Event handlers removed - now handled by AgentGameState:get_activity_events()

return { action = MineResourceAction, params = MineResourceParams }
