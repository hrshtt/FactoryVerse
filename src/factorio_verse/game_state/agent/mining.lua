--- Agent mining state machine and job management
--- Handles resource mining jobs, inventory tracking, and mining state management

-- Note: Do not capture 'game' at module level - it may be nil during on_load
-- Access 'game' directly in functions where it's guaranteed to be available (event handlers)
local pairs = pairs

--- @class MiningModule
local M = {}

-- ============================================================================
-- MINING STATE MACHINE
-- ============================================================================

--- Send UDP notification for mining completion
--- @param job table Mining job
local function _send_mining_completion_udp(job)
    -- New async action completion payload contract
    local payload = {
        agent_id = job.agent_id,
        action_id = job.action_id,
        action_type = "mine_resource",
        start_tick = job.start_tick, -- when action was triggered
        success = true,
        result = {
            [job.item_name] = storage.agent_characters[job.agent_id].get_item_count(job.item_name) - job.initial_item_count,
        }
    }
    if job.cancelled then
        payload.cancelled = true
        payload.cancelled_tick = job.cancelled_tick
    else
        payload.completion_tick = game.tick
    end
    local json_payload = helpers.table_to_json(payload)
    local ok, err = pcall(function() helpers.send_udp(34202, json_payload) end)
    if not ok then
        game.print(string.format("[UDP] ERROR: %s", err or "unknown"))
    end
end


-- In M.tick_mine_jobs()
function M.tick_mine_jobs(event)
    for agent_id, agent in pairs(storage.agent_characters) do
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
