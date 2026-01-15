--- Agent research action methods
--- Methods operate directly on Agent instances (self)
--- These methods are mixed into the Agent class at module level

local ResearchActions = {}

--- Check if a technology can be researched right now (all prerequisites met)
--- @param technology LuaTechnology
--- @return boolean
local function can_research_now(technology)
    -- Already researched technologies cannot be researched again
    if technology.researched then
        return false
    end
    
    -- Technology must be enabled
    if not technology.enabled then
        return false
    end
    
    -- Check if all prerequisites are researched
    -- prerequisites is a dictionary mapping technology name to LuaTechnology
    for prereq_name, prereq_tech in pairs(technology.prerequisites) do
        if not prereq_tech.researched then
            return false
        end
    end
    
    return true
end

--- Get technologies available to the agent's force
--- @param only_available boolean|nil If true, only return technologies that can be researched right now
--- @return table[] Array of technology details
function ResearchActions.get_technologies(self, only_available)
    only_available = only_available or false

    local technologies = self.character.force.technologies
    local valid_technologies = {}
    for technology_name, technology in pairs(technologies) do
        -- Skip if not enabled
        if not technology.enabled then
            goto continue
        end
        
        -- If only_available flag is set, filter to technologies that can be researched now
        if only_available and not can_research_now(technology) then
            goto continue
        end
        
        -- Convert prerequisites from dictionary[string → LuaTechnology] to dictionary[string → string]
        -- for JSON serialization
        local prerequisites_dict = {}
        for prereq_name, prereq_tech in pairs(technology.prerequisites) do
            prerequisites_dict[prereq_name] = prereq_tech.name
        end
        
        local details = {
            name = technology.name,
            researched = technology.researched,
            enabled = technology.enabled,
            prerequisites = prerequisites_dict,
            successors = technology.successors,
            research_unit_ingredients = technology.research_unit_ingredients,
            research_unit_count = technology.research_unit_count,
            research_unit_energy = technology.research_unit_energy,
            saved_progress = technology.saved_progress,
            effects = technology.prototype.effects,
            research_trigger = technology.prototype.research_trigger,
        }
        table.insert(valid_technologies, details)
        
        ::continue::
    end
    return valid_technologies or {}
end

--- Enqueue a technology for research
--- Adds the technology to the back of the research queue if queue is enabled,
--- otherwise sets it as the current research
--- @param technology_name string Technology name to research
--- @return table Result with {success, technology_name, tick, queue_position}
function ResearchActions.enqueue_research(self, technology_name)
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    if not technology_name or type(technology_name) ~= "string" then
        error("Agent: technology_name (string) is required")
    end
    
    local force = self.character.force
    if not force then
        error("Agent: Agent force is invalid")
    end
    
    -- Get technology from force
    local technology = force.technologies[technology_name]
    if not technology then
        error("Agent: Technology '" .. technology_name .. "' not found")
    end
    
    -- Check if technology is enabled
    if not technology.enabled then
        error("Agent: Technology '" .. technology_name .. "' is not enabled")
    end
    
    -- Check if already researched
    if technology.researched then
        error("Agent: Technology '" .. technology_name .. "' is already researched")
    end
    
    -- Get current queue length before adding
    local queue_before = force.research_queue or {}
    local queue_length_before = #queue_before
    
    -- Add research to queue
    local success = force.add_research(technology)
    
    if not success then
        -- Technology might have been dropped silently (e.g., prerequisites not met)
        -- Check if it was actually added
        local queue_after = force.research_queue or {}
        local queue_length_after = #queue_after
        
        if queue_length_after <= queue_length_before then
            error("Agent: Failed to add technology '" .. technology_name .. "' to research queue (prerequisites may not be met)")
        end
    end
    
    -- Get updated queue to find position
    local queue_after = force.research_queue or {}
    local queue_position = nil
    for i, queued_tech in ipairs(queue_after) do
        if queued_tech.name == technology_name then
            queue_position = i
            break
        end
    end
    
    return {
        success = true,
        technology_name = technology_name,
        tick = game.tick,
        queue_position = queue_position,
        queue_length = #queue_after
    }
end

--- Cancel the current research
--- Cancels the currently active research (first in queue)
--- @return table Result with {success, cancelled_technology, tick}
function ResearchActions.cancel_current_research(self)
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    local force = self.character.force
    if not force then
        error("Agent: Agent force is invalid")
    end
    
    -- Get current research before canceling
    local current_research = force.current_research
    local cancelled_technology = nil
    if current_research then
        cancelled_technology = current_research.name
    end
    
    -- Check if there's actually research to cancel
    if not current_research then
        return {
            success = false,
            error = "No active research to cancel",
            tick = game.tick
        }
    end
    
    -- Cancel current research
    force.cancel_current_research()
    
    return {
        success = true,
        cancelled_technology = cancelled_technology,
        tick = game.tick
    }
end

--- Get current research queue with progress information
--- @return table Queue information with current research and queued technologies
function ResearchActions.get_research_queue(self)
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    local force = self.character.force
    if not force then
        error("Agent: Agent force is invalid")
    end
    
    local queue = {}
    local research_queue = force.research_queue or {}
    
    -- Build queue array with progress information
    for i, tech in ipairs(research_queue) do
        table.insert(queue, {
            position = i,
            name = tech.name,
            progress = tech.saved_progress or 0.0,  -- 0.0-1.0
            is_current = (i == 1),
            research_unit_count = tech.research_unit_count,
            research_unit_energy = tech.research_unit_energy,
            research_unit_ingredients = tech.research_unit_ingredients,
        })
    end
    
    return {
        queue = queue,
        queue_length = #queue,
        current_research = force.current_research and force.current_research.name or nil,
        tick = game.tick,
    }
end

--- Get comprehensive research status with progressive detail levels
--- Returns minimal info if no research, more if queued, full details if active
--- @return table Research status with progressive detail based on state
function ResearchActions.get_research_status(self)
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    local force = self.character.force
    if not force then
        error("Agent: Agent force is invalid")
    end
    
    local current_tech = force.current_research
    local research_queue = force.research_queue or {}
    local research_progress = force.research_progress or 0.0
    
    -- Check if anything is queued (items in queue beyond the current one)
    local is_queued = #research_queue > 1
    
    -- Check if actively researched (is a tech selected?)
    local is_active = current_tech ~= nil
    
    -- Base response with minimal info
    local status = {
        queued = is_queued,
        active = is_active,
        progress = research_progress,
        tick = game.tick,
    }
    
    -- If nothing is queued and nothing is active, return minimal response
    if not is_queued and not is_active then
        status.current_research = nil
        status.queue_length = 0
        status.status = "No research queued or active"
        return status
    end
    
    -- Add queue information if anything is queued
    if #research_queue > 0 then
        status.queue_length = #research_queue
        status.current_research = current_tech and current_tech.name or nil
        
        -- Build queue array with basic info
        local queue = {}
        for i, tech in ipairs(research_queue) do
            table.insert(queue, {
                position = i,
                name = tech.name,
                is_current = (i == 1),
            })
        end
        status.queue = queue
    end
    
    -- If research is active, add detailed progress information
    if is_active and current_tech then
        local total_units = current_tech.research_unit_count
        local units_done = math.floor(research_progress * total_units)
        local units_remaining = total_units - units_done
        
        status.status = string.format("%d / %d units completed", units_done, total_units)
        status.units_completed = units_done
        status.units_total = total_units
        status.units_remaining = units_remaining
        status.research_unit_count = total_units
        status.research_unit_energy = current_tech.research_unit_energy
        status.research_unit_ingredients = current_tech.research_unit_ingredients
        
        -- Add saved progress from the tech object (more accurate than force.research_progress)
        if current_tech.saved_progress then
            status.saved_progress = current_tech.saved_progress
        end
    elseif is_queued then
        -- Research is queued but not active (no labs working or waiting for prerequisites)
        status.status = "Research queued but not active"
    end
    
    return status
end

return ResearchActions

