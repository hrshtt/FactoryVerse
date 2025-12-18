--- Notifications.lua
--- Handles game event notifications sent to agents via UDP
--- Supports research events, crafting events, and other asynchronous game events

local M = {}
local udp = require("utils.udp")

-- ============================================================================
-- NOTIFICATION HELPERS
-- ============================================================================

--- Send notification to specific agent
--- @param agent_id number Agent ID
--- @param notification_type string Type of notification (e.g., "research_finished")
--- @param data table Notification-specific data
local function send_agent_notification(agent_id, notification_type, data)
    local agent = storage.agents[agent_id]
    if not agent or not agent.udp_port then
        log(string.format("[Notifications] Agent %d not found or no UDP port", agent_id))
        return
    end
    
    local payload = {
        event_type = "notification",
        notification_type = notification_type,
        agent_id = agent_id,
        tick = game.tick,
        data = data
    }
    
    udp.send_udp_notification(payload, agent.udp_port)
    log(string.format("[Notifications] Sent %s to agent %d", notification_type, agent_id))
end

--- Send notification to all agents in a force
--- @param force LuaForce The force
--- @param notification_type string Type of notification
--- @param data table Notification-specific data
local function send_force_notification(force, notification_type, data)
    if not force or not force.valid then
        return
    end
    
    local count = 0
    for agent_id, agent in pairs(storage.agents or {}) do
        if agent.character and agent.character.valid and 
           agent.character.force == force then
            send_agent_notification(agent_id, notification_type, data)
            count = count + 1
        end
    end
    
    if count > 0 then
        log(string.format("[Notifications] Sent %s to %d agents in force %s", 
            notification_type, count, force.name))
    end
end

-- ============================================================================
-- RESEARCH EVENT HANDLERS
-- ============================================================================

--- Called when research finishes
--- @param event EventData.on_research_finished
function M.on_research_finished(event)
    local tech = event.research
    if not tech or not tech.valid then
        return
    end
    
    local force = tech.force
    
    -- Collect unlocked recipes
    local unlocked_recipes = {}
    for _, effect in ipairs(tech.prototype.effects or {}) do
        if effect.type == "unlock-recipe" then
            table.insert(unlocked_recipes, effect.recipe)
        end
    end
    
    local data = {
        technology = tech.name,
        researched_by_script = event.by_script,
        unlocked_recipes = unlocked_recipes,
        level = tech.level
    }
    
    send_force_notification(force, "research_finished", data)
end

--- Called when research starts
--- @param event EventData.on_research_started
function M.on_research_started(event)
    local tech = event.research
    if not tech or not tech.valid then
        return
    end
    
    local force = tech.force
    
    local data = {
        technology = tech.name,
        last_research = event.last_research and event.last_research.name or nil,
        level = tech.level
    }
    
    send_force_notification(force, "research_started", data)
end

--- Called when research is cancelled
--- @param event EventData.on_research_cancelled
function M.on_research_cancelled(event)
    local force = event.force
    if not force or not force.valid then
        return
    end
    
    local data = {
        technologies = event.research,  -- mapping of tech_name -> count
        player_index = event.player_index
    }
    
    send_force_notification(force, "research_cancelled", data)
end

--- Called when research is queued
--- @param event EventData.on_research_queued
function M.on_research_queued(event)
    local tech = event.research
    if not tech or not tech.valid then
        return
    end
    
    local force = event.force
    
    local data = {
        technology = tech.name,
        player_index = event.player_index,
        level = tech.level
    }
    
    send_force_notification(force, "research_queued", data)
end

--- Called when research queue is reordered
--- @param event EventData.on_research_moved
function M.on_research_moved(event)
    local force = event.force
    if not force or not force.valid then
        return
    end
    
    local data = {
        player_index = event.player_index
    }
    
    send_force_notification(force, "research_moved", data)
end

--- Called when research is reversed (unresearched)
--- @param event EventData.on_research_reversed
function M.on_research_reversed(event)
    local tech = event.research
    if not tech or not tech.valid then
        return
    end
    
    local force = tech.force
    
    local data = {
        technology = tech.name,
        researched_by_script = event.by_script,
        level = tech.level
    }
    
    send_force_notification(force, "research_reversed", data)
end

-- ============================================================================
-- EVENT REGISTRATION
-- ============================================================================

--- Get events for registration in control.lua
--- @return table Event registration table with defined_events
function M.get_events()
    return {
        defined_events = {
            [defines.events.on_research_finished] = M.on_research_finished,
            [defines.events.on_research_started] = M.on_research_started,
            [defines.events.on_research_cancelled] = M.on_research_cancelled,
            [defines.events.on_research_queued] = M.on_research_queued,
            [defines.events.on_research_moved] = M.on_research_moved,
            [defines.events.on_research_reversed] = M.on_research_reversed,
        }
    }
end

return M
