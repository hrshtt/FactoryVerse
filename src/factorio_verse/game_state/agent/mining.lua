--- Agent mining state machine and job management
--- Handles resource mining jobs, inventory tracking, and mining state management

-- Note: Do not capture 'game' at module level - it may be nil during on_load
-- Access 'game' directly in functions where it's guaranteed to be available (event handlers)
local pairs = pairs
local math = math

local helpers = require("game_state.agent.helpers")

local M = {}

-- ============================================================================
-- MINING STATE MACHINE
-- ============================================================================

--- @class MiningModule
--- @field agent_control table Interface with set_mining, stop_walking methods
--- @field walking WalkingModule|table Interface with start_walk_to_job, cancel_walk_to methods
--- @field start_mining_job fun(self: MiningModule, agent_id: number, target: {x:number, y:number}, resource_name: string, max_count: number, options: table|nil): boolean
--- @field get_event_handlers fun(self: MiningModule): table
--- @field tick_mine_jobs fun(self: MiningModule, event: table)
--- Initialize mining module with agent control interface
--- @param agent_control table Interface with set_mining, stop_walking methods
--- @param walking table Interface with start_walk_to_job, cancel_walk_to methods
function M:init(agent_control, walking)
    self.agent_control = agent_control
    self.walking = walking
end

--- Start a mining job for an agent
--- @param self MiningModule
--- @param agent_id number
--- @param target {x:number, y:number}
--- @param resource_name string
--- @param max_count number
--- @param options table|nil Options: walk_if_unreachable, debug
--- @return boolean success
function M:start_mining_job(agent_id, target, resource_name, max_count, options)
    if not (target and target.x and target.y and resource_name and max_count) then return false end
    
    storage.mine_resource_jobs = storage.mine_resource_jobs or {}
    
    local opts = options or {}
    local control = helpers.get_control_for_agent(agent_id)
    if not control then return false end
    
    -- Get resource entity to determine products
    local surface = control.surface
    local resource = helpers.find_resource_entity(surface, target, resource_name)
    if not (resource and resource.valid) then return false end
    
    local products, requires_fluid = helpers.get_resource_products(resource)
    if requires_fluid then
        log(string.format("[mine_resource] resource %s requires fluid; cannot hand-mine. Aborting job for agent=%d", resource_name, agent_id))
        return false
    end
    
    local start_item_count
    if resource.type == "tree" then
        start_item_count = nil
    else
        start_item_count = helpers.get_actor_item_count(control, resource_name)
    end
    
    local job = {
        agent_id = agent_id,
        target = { x = target.x, y = target.y },
        resource_name = resource_name,
        max_count = max_count,
        mined_count = 0,
        walk_if_unreachable = opts.walk_if_unreachable and true or false,
        finished = false,
        products = products,
        start_total = products and helpers.get_actor_items_total(control, products) or 0,
        start_item_count = start_item_count,
        debug = opts.debug or false,
        mining_active = false
    }
    
    storage.mine_resource_jobs[agent_id] = job
    return true
end

--- Cancel walk jobs for an agent (internal helper)
--- @param agent_id number
local function _cancel_walk_for_agent(walking_module, agent_id)
    if walking_module then
        walking_module:cancel_walk_to(agent_id)
    end
    if storage.walk_intents then
        storage.walk_intents[agent_id] = nil
    end
end

--- Send UDP notification for mining completion
--- @param job table Mining job
--- @param resource LuaEntity|nil Resource entity (may be nil if depleted)
local function _send_mining_completion_udp(job, resource)
    local payload = {
        action = "mine_resource_complete",
        agent_id = job.agent_id,
        resource_name = job.resource_name,
        target = { x = job.target.x, y = job.target.y },
        items_received = job.mined_count or 0,
        products = job.products
    }
    if resource and resource.valid and resource.type == "resource" then
        payload.resource_type = "tile"
        payload.resource_remaining = resource.amount or 0
    elseif resource and resource.valid and resource.type == "tree" then
        payload.resource_type = "tree"
        payload.resource_remaining = 0
    else
        payload.resource_type = job.resource_name == "tree" and "tree" or "tile"
        payload.resource_remaining = 0
    end
    pcall(function() _G.helpers.send_udp(30123, payload, 0) end)
end

--- Tick handler for mining jobs
--- @param self MiningModule
--- @param event table
function M:tick_mine_jobs(event)
    if not storage.mine_resource_jobs then return end
    for agent_id, job in pairs(storage.mine_resource_jobs) do
        if not job or job.finished then
            storage.mine_resource_jobs[agent_id] = nil
        else
            local control = helpers.get_control_for_agent(agent_id)
            if not control then
                storage.mine_resource_jobs[agent_id] = nil
            else
                -- Refresh progress from inventory when possible (authoritative stop)
                local mined_by_total = nil
                local mined_by_item = nil
                if job.products and (job.start_total ~= nil) then
                    local current_total = helpers.get_actor_items_total(control, job.products)
                    mined_by_total = math.max(0, (current_total - (job.start_total or 0)))
                end
                if job.resource_name and (job.start_item_count ~= nil) then
                    local current_item = helpers.get_actor_item_count(control, job.resource_name)
                    mined_by_item = math.max(0, (current_item - (job.start_item_count or 0)))
                end
                if mined_by_total or mined_by_item then
                    job.mined_count = math.max(mined_by_total or 0, mined_by_item or 0)
                end

                -- Stop if completed
                local surface = control.surface
                if (job.mined_count or 0) >= job.max_count then
                    self.agent_control:set_mining(agent_id, false)
                    local resource = helpers.find_resource_entity(surface, job.target, job.resource_name)
                    _send_mining_completion_udp(job, resource)
                    job.finished = true
                    storage.mine_resource_jobs[agent_id] = nil
                else
                    local resource = helpers.find_resource_entity(surface, job.target, job.resource_name)

                    if not (resource and resource.valid) then
                        -- Target depleted or missing
                        self.agent_control:set_mining(agent_id, false)
                        _send_mining_completion_udp(job, nil)
                        job.finished = true
                        storage.mine_resource_jobs[agent_id] = nil
                    else
                        -- Access game.tick directly when handler runs (not during closure creation)
                        -- game is guaranteed to be available during event handlers
                        if job.debug and ((game.tick % 60) == 0) then
                            log(string.format("[mine_resource] tick=%d agent=%d mined=%d/%d (item=%d)", game.tick, agent_id, job.mined_count or 0, job.max_count, (job.resource_name and helpers.get_actor_item_count(control, job.resource_name) - (job.start_item_count or 0)) or -1))
                        end
                        -- Initialize products and guard against fluid-only mining
                        if not job.products then
                            local names, requires_fluid = helpers.get_resource_products(resource)
                            if requires_fluid then
                                log(string.format("[mine_resource] resource %s requires fluid; cannot hand-mine. Aborting job for agent=%d", job.resource_name, agent_id))
                                self.agent_control:set_mining(agent_id, false)
                                job.finished = true
                                storage.mine_resource_jobs[agent_id] = nil
                                goto continue_agent
                            end
                            job.products = names
                            job.start_total = helpers.get_actor_items_total(control, job.products)
                            -- For trees: do NOT track resource_name as an item
                            if resource.type == "tree" then
                                job.start_item_count = nil
                            else
                                job.start_item_count = helpers.get_actor_item_count(control, job.resource_name)
                            end
                        end

                        local target_pos = resource.position or job.target
                        local reachable = helpers.can_reach_entity(control, resource)

                        if reachable then
                            -- Ensure we are not walking and keep mining active by reasserting every tick
                            _cancel_walk_for_agent(self.walking, agent_id)
                            self.agent_control:set_mining(agent_id, true, resource)
                            job.mining_active = true

                            -- Set selected entity and mining state (required for zombie characters)
                            if control.valid and resource and resource.valid then
                                control.selected = resource  -- Set selected entity for mining
                            end
                            if control.mining_state ~= nil then
                                control.mining_state = { mining = true, position = { x = target_pos.x, y = target_pos.y } }
                            end
                            
                            -- Track progress
                            local current_total = helpers.get_actor_items_total(control, job.products)
                            local mined_by_total = math.max(0, (current_total - (job.start_total or 0)))
                            -- Only track item count if start_item_count was set (skipped for trees)
                            local mined_by_item = 0
                            if job.start_item_count ~= nil then
                                local current_item = helpers.get_actor_item_count(control, job.resource_name)
                                mined_by_item = math.max(0, (current_item - (job.start_item_count or 0)))
                            end
                            job.mined_count = math.max(mined_by_total, mined_by_item)
                            
                            if (job.mined_count or 0) >= job.max_count then
                                if control.mining_state ~= nil then
                                    control.mining_state = { mining = false }
                                end
                                _send_mining_completion_udp(job, resource)
                                job.finished = true
                                storage.mine_resource_jobs[agent_id] = nil
                                log(string.format("[mine_resource] agent=%d completed target: %d/%d", agent_id, job.mined_count, job.max_count))
                            end
                        else
                            if job.mining_active then
                                self.agent_control:set_mining(agent_id, false)
                                job.mining_active = false
                            end
                            if job.walk_if_unreachable and self.walking then
                                -- Use walk_to_job API
                                --- @type WalkingModule
                                local walking = self.walking
                                walking:start_walk_to_job(agent_id, job.target, {
                                    arrive_radius = 1.2,
                                    prefer_cardinal = true
                                })
                            end
                        end
                    end
                end
                ::continue_agent::
            end
        end
    end
end

--- Get event handlers for mining activities
--- @param self MiningModule
--- @return table Event handlers keyed by event ID
function M:get_event_handlers()
    return {
        [defines.events.on_tick] = function(event)
            self:tick_mine_jobs(event)
        end
    }
end

return M

