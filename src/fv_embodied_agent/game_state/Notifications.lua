--- Notifications.lua
--- Game events that belong to the agent's `turn` stream: research lifecycle
--- (force-scoped, fanned out per agent) and hand-crafting completion
--- (character-scoped). Nothing here sends; everything rides utils/stream.lua
--- and leaves at the per-tick flush with an epoch/seq stamp and a file line.
---
--- The action stream (per-call completions correlated by action_id) is a
--- separate port and a separate path (Agent.message_queue → Agents.on_tick).
--- A craft completion therefore leaves once per port: `craft_enqueue
--- completed` on the action port, `crafting_finished` on the turn port.

local M = {}
local stream = require("utils.stream")
local custom_events = require("utils.custom_events")

-- ============================================================================
-- NOTIFICATION HELPERS
-- ============================================================================

--- Emit a `turn` event onto one agent's stream.
--- Nothing is sent here: the stream stamps, writes and sends at the next
--- flush (Agents.on_tick), once per tick, in emit order. The envelope carries
--- epoch/seq/tick; agent_id rides inside data.
--- @param agent_id number Agent ID
--- @param event_type string One of vocabulary.target.turn
--- @param data table Event-specific data
local function emit_agent_turn_event(agent_id, event_type, data)
    local agent = storage.agents[agent_id]
    if not agent or not agent.turn_stream then
        log(string.format("[Notifications] Agent %s not found or has no turn stream", tostring(agent_id)))
        return false
    end
    data = data or {}
    data.agent_id = agent_id
    local accepted = stream.emit(agent:turn_stream(), event_type, data)
    if accepted then
        log(string.format("[Notifications] Emitted %s for agent %d", event_type, agent_id))
    end
    return accepted
end

--- Emit a force-scoped `turn` event to every agent on the force.
--- Research is force state; each agent gets its own datagram at its own seq.
--- @param force LuaForce The force
--- @param event_type string One of vocabulary.target.turn
--- @param data table Event-specific data (copied per agent)
local function emit_force_turn_event(force, event_type, data)
    if not force or not force.valid then
        return
    end

    local count = 0
    for agent_id, agent in pairs(storage.agents or {}) do
        if agent.character and agent.character.valid and
           agent.character.force == force then
            local copy = {}
            for k, v in pairs(data or {}) do copy[k] = v end
            if emit_agent_turn_event(agent_id, event_type, copy) then
                count = count + 1
            end
        end
    end

    if count > 0 then
        log(string.format("[Notifications] Emitted %s to %d agents in force %s",
            event_type, count, force.name))
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
    
    -- Collect both the convenience recipe list and the complete normalized
    -- capability delta. Prototype effects are structs; copy their scalar
    -- fields into plain tables so UDP JSON serialization is deterministic.
    local unlocked_recipes = {}
    local effects = {}
    for _, effect in ipairs(tech.prototype.effects or {}) do
        local normalized = {type = effect.type}
        for key, value in pairs(effect) do
            local value_type = type(value)
            if value_type == "string" or value_type == "number" or value_type == "boolean" then
                normalized[key] = value
            end
        end
        table.insert(effects, normalized)
        if effect.type == "unlock-recipe" then
            table.insert(unlocked_recipes, effect.recipe)
        end
    end
    
    local data = {
        technology = tech.name,
        researched_by_script = event.by_script,
        unlocked_recipes = unlocked_recipes,
        effects = effects,
        level = tech.level
    }
    
    emit_force_turn_event(force, "research_finished", data)
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
    
    emit_force_turn_event(force, "research_started", data)
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
    
    emit_force_turn_event(force, "research_cancelled", data)
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
    
    emit_force_turn_event(force, "research_queued", data)
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
    
    emit_force_turn_event(force, "research_moved", data)
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

    emit_force_turn_event(force, "research_reversed", data)
end

-- ============================================================================
-- CRAFTING EVENT HANDLERS
-- ============================================================================

--- Called when agent crafting completes (custom event from crafting.lua)
--- This notification is sent for the fire-and-forget NQ/DQ pattern, allowing
--- agents to queue crafting and continue with other work while being notified
--- when items are ready.
--- @param event table Custom event with agent_id, recipe, count_crafted, products
function M.on_agent_crafting_completed(event)
    local agent_id = event.agent_id
    if not agent_id then
        return
    end

    local data = {
        recipe = event.recipe,
        count = event.count_crafted or 0,
        products = event.products or {},
        action_id = event.action_id,  -- Link back to original action if available
    }

    emit_agent_turn_event(agent_id, "crafting_finished", data)
end

-- ============================================================================
-- EVENT REGISTRATION
-- ============================================================================

--- Get events for registration in control.lua
--- @return table Event registration table with defined_events
function M.get_events()
    return {
        defined_events = {
            -- Research events (built-in Factorio events)
            [defines.events.on_research_finished] = M.on_research_finished,
            [defines.events.on_research_started] = M.on_research_started,
            [defines.events.on_research_cancelled] = M.on_research_cancelled,
            [defines.events.on_research_queued] = M.on_research_queued,
            [defines.events.on_research_moved] = M.on_research_moved,
            [defines.events.on_research_reversed] = M.on_research_reversed,
            -- Crafting events (custom events from crafting.lua)
            [custom_events.on_agent_crafting_completed] = M.on_agent_crafting_completed,
        }
    }
end

return M
