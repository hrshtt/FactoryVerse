--- Agent placing_in_line state machine and job management
--- Handles placing entities while walking in a straight line

local pairs = pairs
local ipairs = ipairs
local math = math
local snapshot = require("utils.snapshot")

local M = {}

--- Calculate squared distance between two positions
--- @param a {x:number, y:number}
--- @param b {x:number, y:number}
--- @return number
local function dist_sq(a, b)
    local dx, dy = (a.x - b.x), (b.y - a.y)
    return dx*dx + dy*dy
end

--- Calculate distance between two positions
--- @param a {x:number, y:number}
--- @param b {x:number, y:number}
--- @return number
local function dist(a, b)
    return math.sqrt(dist_sq(a, b))
end

--- Validate that a path passes near placement positions
--- @param path table Array of waypoints from pathfinding
--- @param placement_positions table Array of {x, y} positions
--- @param tolerance number Maximum distance from path (in tiles)
--- @return boolean, string|nil, table|nil
local function validate_path_passes_placements(path, placement_positions, tolerance)
    if not path or #path == 0 then
        return false, "no_path_found", nil
    end
    
    -- Check each placement position is near path waypoints
    for i, placement_pos in ipairs(placement_positions) do
        local near_path = false
        local min_dist = math.huge
        
        for _, waypoint in ipairs(path) do
            local wp_pos = waypoint.position or waypoint
            local wp_x = wp_pos.x or wp_pos[1] or 0
            local wp_y = wp_pos.y or wp_pos[2] or 0
            local d = dist(placement_pos, {x = wp_x, y = wp_y})
            min_dist = math.min(min_dist, d)
            
            if d <= tolerance then
                near_path = true
                break
            end
        end
        
        if not near_path then
            return false, "placement_not_near_path", {
                index = i,
                position = placement_pos,
                min_distance = min_dist
            }
        end
    end
    
    return true, nil, nil
end

--- Validate placement path and return detailed validation results
--- @param agent_id number
--- @param placement_plan table Array of placement entries
--- @param start_position table
--- @param end_position table
--- @return table Validation results
function M:validate_placement_path(agent_id, placement_plan, start_position, end_position)
    local agent = storage.agents[agent_id]
    if not agent or not agent.valid then
        return {
            valid = false,
            error = "agent_not_found"
        }
    end
    
    local surface = agent.surface
    local obstacles = {}
    local resources_to_mine = {}
    local items_to_pickup = {}
    local unplaceable_positions = {}
    
    -- Check inventory
    local inv = agent.get_inventory(defines.inventory.character_main)
    local inventory_check = {
        has_sufficient_items = true,
        required_items = {},
        available_items = {}
    }
    
    -- Count required items
    for i, plan_entry in ipairs(placement_plan) do
        local entity_name = plan_entry.entity_name
        if entity_name ~= "space" then
            inventory_check.required_items[entity_name] = (inventory_check.required_items[entity_name] or 0) + 1
        end
    end
    
    -- Check available items
    for entity_name, required_count in pairs(inventory_check.required_items) do
        local available = inv and inv.get_item_count(entity_name) or 0
        inventory_check.available_items[entity_name] = available
        if available < required_count then
            inventory_check.has_sufficient_items = false
        end
    end
    
    -- Validate each placement position
    for i, plan_entry in ipairs(placement_plan) do
        local pos = plan_entry.position
        
        -- Check for existing entities at position
        local existing = surface.find_entity(plan_entry.entity_name, pos)
        if existing then
            table.insert(obstacles, {
                index = i,
                position = pos,
                entity = {
                    name = existing.name,
                    unit_number = existing.unit_number,
                    type = existing.type
                },
                action_required = "remove_entity"
            })
        end
        
        -- Check for resources
        local resources = surface.find_entities_filtered({
            position = pos,
            radius = 0.5,
            type = "resource"
        })
        for _, resource in ipairs(resources) do
            table.insert(resources_to_mine, {
                index = i,
                position = pos,
                resource = {
                    name = resource.name,
                    unit_number = resource.unit_number,
                    amount = resource.amount
                }
            })
        end
        
        -- Check for items on ground
        local items = surface.find_entities_filtered({
            position = pos,
            radius = 0.5,
            type = "item-entity"
        })
        for _, item in ipairs(items) do
            table.insert(items_to_pickup, {
                index = i,
                position = pos,
                item = {
                    name = item.stack.name,
                    count = item.stack.count
                }
            })
        end
        
        -- Check if position is placeable
        local can_place = surface.can_place_entity({
            name = plan_entry.entity_name,
            position = pos,
            direction = plan_entry.direction,
            force = agent.force,
            build_check_type = defines.build_check_type.manual
        })
        
        if not can_place then
            table.insert(unplaceable_positions, {
                index = i,
                position = pos,
                reason = "not_placeable"
            })
        end
    end
    
    -- Note: Pathfinding validation would require async handling
    -- For dry_run, we'll validate what we can synchronously
    -- The actual pathfinding will be done when the job starts
    
    local valid = #obstacles == 0 and #unplaceable_positions == 0 and inventory_check.has_sufficient_items
    
    return {
        valid = valid,
        path_exists = nil,  -- Would need async handling to determine
        path_waypoints = nil,  -- Would need async handling
        path_passes_placements = nil,  -- Would need async handling
        total_positions = #placement_plan,
        placeable_positions = #placement_plan - #unplaceable_positions,
        unplaceable_positions = unplaceable_positions,
        obstacles = obstacles,
        resources_to_mine = resources_to_mine,
        items_to_pickup = items_to_pickup,
        inventory_check = inventory_check,
        estimated_ticks = #placement_plan * 2,  -- Rough estimate
        estimated_placements = #placement_plan - #unplaceable_positions
    }
end

--- Send UDP notification for place_in_line completion
--- @param job table Place in line job
--- @param success boolean Whether placement succeeded
local function _send_placement_completion_udp(job, success)
    -- Get action tracking info
    local tracking = nil
    local action_id = nil
    local rcon_tick = nil
    
    if storage.place_in_line_in_progress then
        tracking = storage.place_in_line_in_progress[job.agent_id]
        if tracking and type(tracking) == "table" then
            action_id = tracking.action_id
            rcon_tick = tracking.rcon_tick
        end
        storage.place_in_line_in_progress[job.agent_id] = nil
    end
    
    local completion_tick = game.tick
    
    local payload = {
        action_id = action_id or string.format("place_in_line_unknown_%d_%d", rcon_tick or completion_tick, job.agent_id),
        agent_id = job.agent_id,
        action_type = "agent_place_in_line",
        rcon_tick = rcon_tick or completion_tick,
        completion_tick = completion_tick,
        success = success,
        result = {
            agent_id = job.agent_id,
            start_position = job.start_position,
            end_position = job.end_position,
            reached_end = job.walk_state == "completed",
            placed_entities = job.placed_entities or {},
            placed_count = #(job.placed_entities or {}),
            failed_placements = job.failed_placements or {},
            failed_count = #(job.failed_placements or {})
        }
    }
    
    snapshot.send_action_completion_udp(payload)
end

--- Attempt to place an entity
--- @param agent LuaEntity
--- @param entity_name string
--- @param position table
--- @param direction number|nil
--- @param orient_towards table|nil
--- @return boolean, LuaEntity|nil
local function try_place_entity(agent, entity_name, position, direction, orient_towards)
    local surface = agent.surface
    
    -- Check inventory
    local inv = agent.get_inventory(defines.inventory.character_main)
    if not inv or inv.get_item_count(entity_name) <= 0 then
        return false, nil
    end
    
    -- Build placement spec
    local placement = {
        name = entity_name,
        position = position,
        force = agent.force,
    }
    
    if direction then
        placement.direction = direction
    elseif orient_towards then
        -- Calculate direction from position to orient_towards
        local target_pos = nil
        if orient_towards.entity_name and orient_towards.position then
            local ok, ent = pcall(function()
                return surface.find_entity(orient_towards.entity_name, orient_towards.position)
            end)
            if ok and ent and ent.valid then
                target_pos = ent.position
            end
        end
        if not target_pos and orient_towards.position then
            target_pos = orient_towards.position
        end
        if target_pos then
            local dx = target_pos.x - position.x
            local dy = target_pos.y - position.y
            if not (dx == 0 and dy == 0) then
                local angle = math.atan2(dy, dx)
                local oct = math.floor(((angle + math.pi / 8) % (2 * math.pi)) / (math.pi / 4))
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
                placement.direction = dir_map[oct] or defines.direction.north
            end
        end
    end
    
    -- Check if can place
    local can_place = surface.can_place_entity({
        name = placement.name,
        position = placement.position,
        direction = placement.direction,
        force = placement.force,
        build_check_type = defines.build_check_type.manual
    })
    
    if not can_place then
        return false, nil
    end
    
    -- Place entity
    local entity = surface.create_entity(placement)
    if not entity then
        return false, nil
    end
    
    -- Consume item
    inv.remove({ name = entity_name, count = 1 })
    
    return true, entity
end

--- Start a place_in_line job
--- @param agent_id number
--- @param start_position table
--- @param end_position table
--- @param placement_plan table
--- @param spacing number
--- @param skip_invalid boolean
--- @param max_entities number|nil
--- @param arrive_radius number
--- @return number|nil job_id
function M:start_place_in_line_job(agent_id, start_position, end_position, placement_plan, spacing, skip_invalid, max_entities, arrive_radius)
    if not (start_position and start_position.x and start_position.y) then return nil end
    if not (end_position and end_position.x and end_position.y) then return nil end
    
    storage.place_in_line_jobs = storage.place_in_line_jobs or {}
    storage.place_in_line_next_id = (storage.place_in_line_next_id or 1)
    
    local agent = storage.agents[agent_id]
    if not agent then return nil end
    
    local agent_pos = agent.position
    local cp = { x = agent_pos.x or agent_pos[1] or 0, y = agent_pos.y or agent_pos[2] or 0 }
    
    local job = {
        id = storage.place_in_line_next_id,
        agent_id = agent_id,
        start_position = { x = start_position.x, y = start_position.y },
        end_position = { x = end_position.x, y = end_position.y },
        placement_plan = placement_plan,
        spacing = spacing,
        skip_invalid = skip_invalid,
        max_entities = max_entities,
        arrive_radius = arrive_radius,
        next_placement_index = 1,
        placed_entities = {},
        failed_placements = {},
        state = "planning",
        path_req_id = nil,
        path = nil,
        walk_state = "planning",
        current_position = { x = cp.x, y = cp.y },
        last_position = { x = cp.x, y = cp.y },
        stuck_ticks = 0
    }
    
    local job_id = storage.place_in_line_next_id
    storage.place_in_line_next_id = storage.place_in_line_next_id + 1
    
    storage.place_in_line_jobs[job_id] = job
    
    -- Request pathfinding
    local path_req_id = agent.surface.request_path({
        start = start_position,
        goal = end_position,
        force = agent.force,
        bounding_box = agent.prototype.collision_box,
        collision_mask = agent.prototype.collision_mask,
        prefer_straight_paths = true,
        can_open_gates = true,
        radius = arrive_radius
    })
    
    job.path_req_id = path_req_id
    
    return job_id
end

--- Cancel place_in_line jobs for an agent
--- @param agent_id number
function M:cancel_place_in_line(agent_id)
    if not storage.place_in_line_jobs then return end
    for id, job in pairs(storage.place_in_line_jobs) do
        if job and job.agent_id == agent_id then
            -- Stop any walking
            if job.walk_state == "walking" then
                local agent = storage.agents[agent_id]
                if agent and agent.valid then
                    -- Stop walking (would need agent_control interface)
                    -- For now, just mark as cancelled
                end
            end
            storage.place_in_line_jobs[id] = nil
        end
    end
end

--- Handle pathfinding callback
--- @param event table
function M:on_path_finished(event)
    if not (storage.place_in_line_jobs and event and event.id) then return end
    
    for _, job in pairs(storage.place_in_line_jobs) do
        if job.path_req_id == event.id then
            if event.path and #event.path > 0 then
                -- Validate path passes near placements
                local placement_positions = {}
                for _, plan_entry in ipairs(job.placement_plan) do
                    table.insert(placement_positions, plan_entry.position)
                end
                
                local valid, reason, details = validate_path_passes_placements(event.path, placement_positions, 1.0)
                
                if valid then
                    job.path = event.path
                    job.walk_state = "walking"
                    -- Start walking along path (would integrate with walking module)
                else
                    job.state = "failed"
                    job.failure_reason = reason
                    _send_placement_completion_udp(job, false)
                end
            else
                job.state = "failed"
                job.failure_reason = "no_path_found"
                _send_placement_completion_udp(job, false)
            end
            break
        end
    end
end

--- Tick handler for place_in_line jobs
--- @param event table
--- @param agent_control table Interface with set_walking method
function M:tick_place_in_line_jobs(event, agent_control)
    if not storage.place_in_line_jobs then return end
    
    for id, job in pairs(storage.place_in_line_jobs) do
        if job.state == "failed" or job.state == "completed" then
            -- Clean up completed/failed jobs
            storage.place_in_line_jobs[id] = nil
        elseif job.state == "walking" then
            local agent = storage.agents[job.agent_id]
            if not agent or not agent.valid then
                job.state = "failed"
                job.failure_reason = "agent_invalid"
                _send_placement_completion_udp(job, false)
                storage.place_in_line_jobs[id] = nil
                goto continue
            end
            
            local agent_pos = agent.position
            local agent_pos_normalized = { x = agent_pos.x or agent_pos[1] or 0, y = agent_pos.y or agent_pos[2] or 0 }
            local build_distance = agent.build_distance or 10
            
            -- Check if reached end
            if dist_sq(agent_pos_normalized, job.end_position) <= (job.arrive_radius * job.arrive_radius) then
                job.walk_state = "completed"
                job.state = "completed"
                _send_placement_completion_udp(job, true)
                storage.place_in_line_jobs[id] = nil
                goto continue
            end
            
            -- Check each unplaced position in plan
            for i = job.next_placement_index, #job.placement_plan do
                local plan_entry = job.placement_plan[i]
                if not plan_entry.placed then
                    local placement_pos = plan_entry.position
                    
                    -- Check if agent is within build distance
                    local dx = placement_pos.x - agent_pos_normalized.x
                    local dy = placement_pos.y - agent_pos_normalized.y
                    local dist_sq_val = dx*dx + dy*dy
                    
                    if dist_sq_val <= build_distance * build_distance then
                        -- Attempt placement
                        local success, entity = try_place_entity(
                            agent,
                            plan_entry.entity_name,
                            placement_pos,
                            plan_entry.direction,
                            plan_entry.orient_towards
                        )
                        
                        if success and entity then
                            plan_entry.placed = true
                            plan_entry.entity_unit_number = entity.unit_number
                            table.insert(job.placed_entities, {
                                unit_number = entity.unit_number,
                                position = {x = entity.position.x, y = entity.position.y},
                                name = entity.name,
                                direction = entity.direction
                            })
                            job.next_placement_index = i + 1
                        elseif not job.skip_invalid then
                            -- Fail entire job if can't place and skip_invalid=false
                            job.state = "failed"
                            job.failure_reason = "placement_failed"
                            _send_placement_completion_udp(job, false)
                            storage.place_in_line_jobs[id] = nil
                            goto continue
                        else
                            -- Track failure but continue
                            table.insert(job.failed_placements, {
                                position = placement_pos,
                                reason = "placement_failed"
                            })
                        end
                    end
                end
            end
            
            -- Simple walking logic: move towards end position
            local dx = job.end_position.x - agent_pos_normalized.x
            local dy = job.end_position.y - agent_pos_normalized.y
            local dist_to_end = math.sqrt(dx*dx + dy*dy)
            
            if dist_to_end > job.arrive_radius then
                -- Calculate direction to end
                local angle = math.atan2(dy, dx)
                local oct = math.floor(((angle + math.pi / 8) % (2 * math.pi)) / (math.pi / 4))
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
                local direction = dir_map[oct] or defines.direction.north
                
                -- Set walking
                if agent_control and agent_control.set_walking then
                    agent_control:set_walking(job.agent_id, direction, true)
                end
                
                -- Stuck detection
                local last = job.last_position
                if last then
                    local step_dx = agent_pos_normalized.x - last.x
                    local step_dy = agent_pos_normalized.y - last.y
                    local step_len = math.sqrt(step_dx*step_dx + step_dy*step_dy)
                    
                    if step_len < 0.01 then
                        job.stuck_ticks = (job.stuck_ticks or 0) + 1
                    else
                        job.stuck_ticks = 0
                    end
                end
                
                job.last_position = { x = agent_pos_normalized.x, y = agent_pos_normalized.y }
                
                -- Fail if stuck for too long
                if (job.stuck_ticks or 0) >= 60 then
                    job.state = "failed"
                    job.failure_reason = "stuck"
                    _send_placement_completion_udp(job, false)
                    storage.place_in_line_jobs[id] = nil
                    goto continue
                end
            end
            
            ::continue::
        end
    end
end

--- Get event handlers for placing_in_line activities
--- @param agent_control table Interface with set_walking method
--- @return table Event handlers keyed by event ID
function M:get_event_handlers(agent_control)
    return {
        [defines.events.on_tick] = function(event)
            self:tick_place_in_line_jobs(event, agent_control)
        end,
        [defines.events.on_script_path_request_finished] = function(event)
            self:on_path_finished(event)
        end
    }
end

return M

