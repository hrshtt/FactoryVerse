--- Agent mining state machine and job management
--- Handles resource mining jobs, inventory tracking, and mining state management

-- Note: Do not capture 'game' at module level - it may be nil during on_load
-- Access 'game' directly in functions where it's guaranteed to be available (event handlers)
local pairs = pairs
local snapshot = require("utils.snapshot")

--- @class MiningModule
local M = {}

-- ============================================================================
-- MINING STATE MACHINE
-- ============================================================================

--- Send UDP notification for mining completion
--- @param job table Mining job
local function _send_mining_completion_udp(job)
    -- Get action tracking info (action_id + rcon_tick that queued this action)
    storage.mine_resource_in_progress = storage.mine_resource_in_progress or {}
    local tracking = storage.mine_resource_in_progress[job.agent_id]
    
    local action_id = job.action_id
    local rcon_tick = job.start_tick
    
    if tracking and type(tracking) == "table" then
        action_id = tracking.action_id or action_id
        rcon_tick = tracking.rcon_tick or rcon_tick
    end
    
    -- Clean up tracking entry
    storage.mine_resource_in_progress[job.agent_id] = nil
    
    local completion_tick = game.tick
    
    -- New async action completion payload contract
    local payload = {
        action_id = action_id,
        agent_id = job.agent_id,
        action_type = "mine_resource",
        rcon_tick = rcon_tick,
        completion_tick = completion_tick,
        success = true,
        cancelled = job.cancelled or false,
        result = {
            [job.item_name] = storage.agents[job.agent_id].get_item_count(job.item_name) - job.initial_item_count,
        }
    }
    
    if job.cancelled then
        payload.cancelled_tick = job.cancelled_tick
    end
    
    snapshot.send_action_completion_udp(payload)
end


-- In M.tick_mine_jobs()
function M.tick_mine_jobs(event)
    for agent_id, agent in pairs(storage.agents) do
        local job = storage.mining_results[agent_id]
        
        if job then
            -- Check if agent is still mining
            if agent.mining_state and agent.mining_state.mining then
                -- Mining is active, check completion conditions
                if not job.mine_till_depleted then
                    local current_count = agent.get_item_count(job.item_name)
                    if current_count >= job.mine_till_count then
                        -- Reached target count, stop mining
                        agent.mining_state = { mining = false }
                        agent.clear_selected_entity()
                        game.print("Mining completed for agent " .. agent_id)
                    end
                end
                -- If mine_till_depleted, let it continue until resource is gone
            else
                -- Mining stopped (either completed or failed)
                _send_mining_completion_udp(job)
                storage.mining_results[agent_id] = nil
            end
        end
    end
end

--- Get event handlers for mining activities
--- @return table Event handlers keyed by event ID
function M.get_event_handlers()
    return {
        [defines.events.on_tick] = function(event)
            M.tick_mine_jobs(event)
        end
    }
end

return M
