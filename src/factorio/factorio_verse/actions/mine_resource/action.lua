local Action = require("core.action.Action")
local ParamSpec = require("core.action.ParamSpec")
local game_state = require("core.game_state.GameState")
local action_registry = require("core.action.ActionRegistry")

--- @class MineResourceParams : ParamSpec
--- @field agent_id number
--- @field x number
--- @field y number
--- @field resource_name string
--- @field min_count number
--- @field walk_if_unreachable boolean|nil
--- @field emulate boolean|nil
local MineResourceParams = ParamSpec:new({
    agent_id = { type = "number", required = true },
    x = { type = "number", required = true },
    y = { type = "number", required = true },
    resource_name = { type = "string", required = true },
    min_count = { type = "number", required = true },
    walk_if_unreachable = { type = "boolean", required = false, default = false },
    emulate = { type = "boolean", required = false, default = true },
})

--- Internal per-agent job state
--- @class MineJob
--- @field agent_id number
--- @field target {x:number,y:number}
--- @field resource_name string
--- @field min_count number
--- @field mined_count number
--- @field products string[]|nil
--- @field start_total number|nil
--- @field walking_started boolean
--- @field finished boolean
local function _new_job(agent_id, pos, resource_name, min_count, walk_if_unreachable)
    return {
        agent_id = agent_id,
        target = { x = pos.x, y = pos.y },
        resource_name = resource_name,
        min_count = min_count,
        mined_count = 0,
        walking_started = false,
        walk_if_unreachable = walk_if_unreachable and true or false,
        finished = false,
        current_entity = nil,
        ticks_left = nil,
        emulate = true,
        player = nil,
        start_total = nil,
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


local function _get_item_count(control, item_name)
    if not (control and control.valid and control.get_inventory) then return 0 end
    local inv = control.get_inventory(defines.inventory.character_main)
    if not inv then return 0 end
    if inv.get_item_count then
        return inv.get_item_count(item_name)
    end
    local contents = inv.get_contents and inv.get_contents() or {}
    return contents[item_name] or 0
end

local function _get_items_total(control, names)
    if not names or #names == 0 then return 0 end
    local total = 0
    for _, name in ipairs(names) do
        total = total + _get_item_count(control, name)
    end
    return total
end

local function _find_resource_entity(surface, position, resource_name)
    if not (surface and position and resource_name) then return nil end
    -- Try exact entity-at-position lookup first
    local ok_ent, ent = pcall(function() return surface.find_entity(resource_name, position) end)
    if ok_ent and ent and ent.valid and ent.type == "resource" then
        return ent
    end
    -- Fallback: search in a reasonable radius and pick the nearest
    local search_radius = 2.5
    local entities = surface.find_entities_filtered{
        position = position,
        radius = search_radius,
        type = "resource",
        name = resource_name
    }
    if not entities or #entities == 0 then return nil end
    local px, py = position.x, position.y
    local best, best_d2 = nil, math.huge
    for _, e in ipairs(entities) do
        if e and e.valid then
            local dx, dy = e.position.x - px, e.position.y - py
            local d2 = dx*dx + dy*dy
            if d2 < best_d2 then
                best, best_d2 = e, d2
            end
        end
    end
    return best
end

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
local function _ticks_to_mine(control, resource)
    local props = resource.prototype and resource.prototype.mineable_properties
    local mining_time = (props and props.mining_time) or 1
    -- TODO: incorporate bonuses/mining speed if needed
    return math.max(1, math.ceil(mining_time * 60))
end

-- Bind/unbind helper for emulate mode
local function _bind_player_to_character(agent_id, control)
    if not (game and game.players and game.players[agent_id]) then return nil end
    local player = game.players[agent_id]
    if not (player and player.valid) then return nil end
    local ok = pcall(function()
        player.set_controller{ type = defines.controllers.character, character = control }
    end)
    if ok then return player end
    return nil
end

local function _unbind_player(player)
    if not (player and player.valid) then return end
    pcall(function()
        player.set_controller{ type = defines.controllers.spectator }
    end)
end

-- Complete mining of the entity after enough ticks: remove entity and insert products
local function _complete_mining_of_entity(control, resource, job)
    if not (control and control.valid and resource and resource.valid) then return 0 end
    local products = resource.prototype and resource.prototype.mineable_properties and resource.prototype.mineable_properties.products or nil
    if not products or #products == 0 then
        -- Fallback: destroy without products
        pcall(function() resource.destroy({ raise_destroy = true }) end)
        return 0
    end

    -- Destroy the entity and insert products
    local inserted = 0
    local inv = control.get_inventory and control.get_inventory(defines.inventory.character_main) or nil
    local pos = resource.position
    local surf = resource.surface

    -- Remove entity and raise events
    pcall(function() resource.destroy({ raise_destroy = true }) end)

    for _, prod in ipairs(products) do
        local name = prod.name
        local amount = prod.amount or 1
        if inv and name and amount and amount > 0 then
            local actually = inv.insert({ name = name, count = amount }) or 0
            inserted = inserted + actually
            if actually < amount then
                -- Drop overflow on ground
                pcall(function()
                    surf.spill_item_stack(pos, { name = name, count = amount - actually }, true, control.force, false)
                end)
            end
        end
    end

    job.mined_count = (job.mined_count or 0) + inserted
    return inserted
end

local function _ensure_walking_towards(job)
    if job.walking_started then return end
    -- Invoke the existing walk_to action for simple greedy approach
    local walk_to = action_registry:get("agent.walk_to")
    if walk_to then
        local ok = pcall(function()
            walk_to:run({
                agent_id = job.agent_id,
                goal = { x = job.target.x, y = job.target.y },
                arrive_radius = 1.2,
                replan_on_stuck = true,
                max_replans = 2,
                prefer_cardinal = true
            })
        end)
        if ok then
            job.walking_started = true
        end
    end
end

local function _cancel_walk_for_agent(agent_id)
    local cancel = action_registry:get("agent.walk_cancel")
    if cancel then
        pcall(function()
            cancel:run({ agent_id = agent_id })
        end)
    end
end

-- Compute a conservative resource reach distance for the character
local function _resource_reach_distance(control)
    if not (control and control.valid) then return 2.5 end
    local proto = control.prototype
    local by_proto = proto and (proto.reach_resource_distance or proto.reach_distance) or nil
    local by_control = control.reach_distance or nil
    local reach = by_proto or by_control or 2.5
    -- generous small buffer
    return reach + 0.1
end

local function _can_reach_entity(control, entity)
    if not (control and control.valid and entity and entity.valid) then return false end
    if control.can_reach_entity then
        -- Try both call styles defensively
        local ok, res = pcall(function() return control.can_reach_entity(control, entity) end)
        if not ok then
            ok, res = pcall(function() return control.can_reach_entity(entity) end)
        end
        if ok and type(res) == "boolean" then return res end
    end
    -- Fallback to distance-based check
    local pos = entity.position or entity
    local dist = _distance(control.position, pos)
    local reach = _resource_reach_distance(control)
    return dist <= reach
end

local function _tick_mine_jobs(event)
    if not storage.mine_resource_jobs then return end
    for agent_id, job in pairs(storage.mine_resource_jobs) do
        if not job or job.finished then
            storage.mine_resource_jobs[agent_id] = nil
        else
            local control = _get_control_for_agent(agent_id)
            if not control then
                storage.mine_resource_jobs[agent_id] = nil
            else
                -- Stop if completed
                if (job.mined_count or 0) >= job.min_count then
                    game_state:agent_state():set_mining(agent_id, false)
                    if job.player then _unbind_player(job.player) end
                    job.finished = true
                    storage.mine_resource_jobs[agent_id] = nil
                else
                    local surface = control.surface
                    local resource = _find_resource_entity(surface, job.target, job.resource_name)

                    if not (resource and resource.valid) then
                        -- Target depleted or missing
                        game_state:agent_state():set_mining(agent_id, false)
                        if job.player then _unbind_player(job.player) end
                        job.finished = true
                        storage.mine_resource_jobs[agent_id] = nil
                    else
                        -- Initialize products and guard against fluid-only mining
                        if not job.products then
                            local names, requires_fluid = _get_resource_products(resource)
                            if requires_fluid then
                                log(string.format("[mine_resource] resource %s requires fluid; cannot hand-mine. Aborting job for agent=%d", job.resource_name, agent_id))
                                game_state:agent_state():set_mining(agent_id, false)
                                if job.player then _unbind_player(job.player) end
                                job.finished = true
                                storage.mine_resource_jobs[agent_id] = nil
                                goto continue_agent
                            end
                            job.products = names
                            local actor = (job.player and job.player.valid) and job.player or control
                            job.start_total = _get_actor_items_total(actor, job.products)
                        end

                        local target_pos = resource.position or job.target
                        local reachable = _can_reach_entity(control, resource)

                        if reachable then
                            -- Ensure we are not walking and keep mining active by reasserting every tick
                            _cancel_walk_for_agent(agent_id)
                            local agent_state = game_state:agent_state()
                            agent_state:set_mining(agent_id, true, resource)
                            job.mining_active = true

                            if job.emulate then
                                local actor = (job.player and job.player.valid) and job.player or control
                                if actor.update_selected_entity and target_pos then
                                    pcall(function() actor.update_selected_entity(target_pos) end)
                                end
                                if actor.mining_state ~= nil then
                                    actor.mining_state = { mining = true, position = { x = target_pos.x, y = target_pos.y } }
                                end
                                local current_total = _get_actor_items_total(actor, job.products)
                                job.mined_count = math.max(0, (current_total - (job.start_total or 0)))
                                if (job.mined_count or 0) >= job.min_count then
                                    if actor.mining_state ~= nil then
                                        actor.mining_state = { mining = false }
                                    end
                                    if job.player then _unbind_player(job.player) end
                                    job.finished = true
                                    storage.mine_resource_jobs[agent_id] = nil
                                    log(string.format("[mine_resource] agent=%d completed target: %d/%d", agent_id, job.mined_count, job.min_count))
                                end
                            else
                                -- Initialize or continue swing timer
                                if (not job.current_entity) or (not job.current_entity.valid) or (job.current_entity ~= resource) then
                                    job.current_entity = resource
                                    job.ticks_left = _ticks_to_mine(control, resource)
                                else
                                    job.ticks_left = math.max(0, (job.ticks_left or 0) - 1)
                                end
                                if (job.ticks_left or 0) <= 0 then
                                    local added = _complete_mining_of_entity(control, resource, job)
                                    job.current_entity = nil
                                    job.ticks_left = nil
                                end
                                if (job.mined_count or 0) >= job.min_count then
                                    agent_state:set_mining(agent_id, false)
                                    job.finished = true
                                    storage.mine_resource_jobs[agent_id] = nil
                                    log(string.format("[mine_resource] agent=%d completed target: %d/%d", agent_id, job.mined_count, job.min_count))
                                end
                            end
                        else
                            if job.mining_active then
                                game_state:agent_state():set_mining(agent_id, false)
                                job.mining_active = false
                            end
                            if job.walk_if_unreachable then
                                _ensure_walking_towards(job)
                            end
                        end
                    end
                end
            end
        end
        ::continue_agent::
    end
end

-- Removed player-mined event usage; character agents aren't players. Use inventory delta instead.

--- @class MineResourceAction : Action
local MineResourceAction = Action:new("mine_resource", MineResourceParams)

--- @param params MineResourceParams
--- @return boolean
function MineResourceAction:run(params)
    local p = self:_pre_run(game_state, params)
    ---@cast p MineResourceParams
    local agent_id = p.agent_id
    local target = { x = p.x, y = p.y }
    local resource_name = p.resource_name
    local min_count = p.min_count
    local emulate = (p.emulate ~= false)
    

    storage.mine_resource_jobs = storage.mine_resource_jobs or {}

    -- Initialize or replace existing job for this agent
    local job = _new_job(agent_id, target, resource_name, min_count, p.walk_if_unreachable)
    job.emulate = emulate
    storage.mine_resource_jobs[agent_id] = job
    log(string.format("[mine_resource] start agent=%d target=(%.2f,%.2f) res=%s min=%d walk=%s", agent_id, target.x, target.y, resource_name, min_count, tostring(p.walk_if_unreachable)))

    local control = _get_control_for_agent(agent_id)
    if control then
        local surface = control.surface
        local resource = _find_resource_entity(surface, target, resource_name)
        if resource and resource.valid then
            -- Precompute products and guard fluid requirement
            local names, requires_fluid = _get_resource_products(resource)
            if requires_fluid then
                log(string.format("[mine_resource] resource %s requires fluid; cannot hand-mine. Aborting job for agent=%d", resource_name, agent_id))
                storage.mine_resource_jobs[agent_id] = nil
                return self:_post_run(false, p)
            end
            job.products = names
            if emulate then
                job.player = _bind_player_to_character(agent_id, control)
            end
            local actor = (job.player and job.player.valid) and job.player or control
            job.start_total = _get_actor_items_total(actor, job.products)

            -- Try to begin mining immediately if in reach; tick will maintain it
            local reachable = _can_reach_entity(control, resource)
            if reachable then
                _cancel_walk_for_agent(agent_id)
                game_state:agent_state():set_mining(agent_id, true, resource)
                job.mining_active = true
                if emulate then
                    local target_pos = resource.position
                    if actor.update_selected_entity and target_pos then
                        pcall(function() actor.update_selected_entity(target_pos) end)
                    end
                    if actor.mining_state ~= nil then
                        actor.mining_state = { mining = true, position = { x = target_pos.x, y = target_pos.y } }
                    end
                else
                    -- Initialize swing timer
                    job.current_entity = resource
                    job.ticks_left = _ticks_to_mine(control, resource)
                end
            elseif job.walk_if_unreachable then
                _ensure_walking_towards(job)
            end
        else
            -- No entity found yet; optionally start walking toward the tile
            if job.walk_if_unreachable then _ensure_walking_towards(job) end
        end
    end

    return self:_post_run(true, p)
end

MineResourceAction.events = {
    [defines.events.on_tick] = _tick_mine_jobs,
}

return { action = MineResourceAction, MineResourceParams = MineResourceParams }
