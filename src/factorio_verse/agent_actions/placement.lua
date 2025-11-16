--- Agent placement action methods
--- Methods operate directly on Agent instances (self)
--- State is stored in self.placing (jobs, next_job_id)
--- These methods are mixed into the Agent class at module level

local PlacementActions = {}

--- Place an entity (sync)
--- @param entity_name string Entity prototype name
--- @param position table Position {x, y}
--- @param options table|nil Placement options {direction, orient_towards}
--- @return table Result with {success, position, entity_name, entity_type}
function PlacementActions.place_entity(self, entity_name, position, options)
    if not (self.entity and self.entity.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    if not entity_name or type(entity_name) ~= "string" then
        error("Agent: entity_name (string) is required")
    end
    
    if not position or type(position.x) ~= "number" or type(position.y) ~= "number" then
        error("Agent: position {x, y} is required")
    end
    
    options = options or {}
    
    local surface = self.entity.surface or game.surfaces[1]
    if not surface then
        error("Agent: No surface available")
    end
    
    -- Validate entity prototype exists
    local proto = prototypes and prototypes.entity and prototypes.entity[entity_name]
    if not proto then
        error("Agent: Unknown entity prototype: " .. entity_name)
    end
    
    -- Build placement parameters
    local placement = {
        name = entity_name,
        position = { x = position.x, y = position.y },
        force = self.entity.force,
        source = self.entity,
        fast_replace = true,
        raise_built = true,
        move_stuck_players = true,
    }
    
    -- Handle direction
    if options.direction ~= nil then
        placement.direction = options.direction
    elseif options.orient_towards then
        -- Derive direction from orient_towards
        local target_pos = nil
        
        if options.orient_towards.entity_name and options.orient_towards.position then
            local ok, ent = pcall(function()
                return surface.find_entity(options.orient_towards.entity_name, options.orient_towards.position)
            end)
            if ok and ent and ent.valid then
                target_pos = ent.position
            end
        end
        
        if not target_pos and options.orient_towards.position then
            target_pos = options.orient_towards.position
        end
        
        if target_pos then
            local dx = target_pos.x - placement.position.x
            local dy = target_pos.y - placement.position.y
            local angle = math.atan2(dy, dx)
            -- Convert angle to direction (0 = east, increments of 45 degrees)
            local dir_enum = math.floor((angle + math.pi) / (math.pi / 4) + 0.5) % 8
            placement.direction = dir_enum
        end
    end
    
    -- Place entity
    local created_entity = surface.create_entity(placement)
    if not created_entity or not created_entity.valid then
        error("Agent: Failed to place entity")
    end
    
    local entity_pos = { x = created_entity.position.x, y = created_entity.position.y }
    
    -- Enqueue completion message
    self:enqueue_message({
        action = "place_entity",
        agent_id = self.agent_id,
        success = true,
        position = entity_pos,
        entity_name = entity_name,
        entity_type = created_entity.type,
        tick = game.tick or 0,
    }, "placement")
    
    return {
        success = true,
        position = entity_pos,
        entity_name = entity_name,
        entity_type = created_entity.type,
    }
end

--- Cancel a placement job
--- @param job_id number|nil If nil, cancels all placement jobs
--- @return table Result
function PlacementActions.cancel_placement(self, job_id)
    if not (self.entity and self.entity.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    local cancelled_jobs = {}
    
    if job_id then
        -- Cancel specific job
        local job = self.placing.jobs[job_id]
        if job then
            job.cancelled = true
            job.cancelled_tick = game.tick
            table.insert(cancelled_jobs, job_id)
            self.placing.jobs[job_id] = nil
        end
    else
        -- Cancel all jobs
        for id, job in pairs(self.placing.jobs) do
            job.cancelled = true
            job.cancelled_tick = game.tick
            table.insert(cancelled_jobs, id)
        end
        self.placing.jobs = {}
    end
    
    -- Enqueue cancel message
    self:enqueue_message({
        action = "cancel_placement",
        agent_id = self.agent_id,
        success = true,
        cancelled = #cancelled_jobs > 0,
        cancelled_jobs = cancelled_jobs,
        tick = game.tick or 0,
    }, "placement")
    
    return {
        success = true,
        cancelled = #cancelled_jobs > 0,
        cancelled_jobs = cancelled_jobs,
    }
end

return PlacementActions

