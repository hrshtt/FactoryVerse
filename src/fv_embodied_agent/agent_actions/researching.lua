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

return ResearchActions

