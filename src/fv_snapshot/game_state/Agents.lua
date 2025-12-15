--- Agent production statistics snapshot module
--- Tracks agent production statistics and writes to snapshot files
--- This module depends on fv_embodied_agent for Agent class

local snapshot = require("utils.snapshot")
local Agents = require("__fv_embodied_agent__/game_state/Agents")

local M = {}

-- ============================================================================
-- AGENT PRODUCTION SNAPSHOT
-- ============================================================================

--- Snapshot agent production statistics every nth tick
--- Writes to {agent_id}/production_statistics.jsonl
function M._on_nth_tick_agent_production_snapshot()
    local agents = Agents.list_agent_forces()
    for agent_id, force_name in pairs(agents) do
        local agent = Agents.get_agent(agent_id)
        if agent and agent.character.valid then
            stats = agent:get_production_statistics()
            if not stats then goto continue end
            -- Append a snapshot entry in JSONL format
            local entry = {
                tick = game.tick,
                statistics = stats
            }
            local json_line = helpers.table_to_json(entry) .. "\n"
            helpers.write_file(
                snapshot.SNAPSHOT_BASE_DIR .. "/" .. agent_id .. "/production_statistics.jsonl",
                json_line,
                true -- append
                -- for_player omitted (server/global)
            )
        end
        ::continue::
    end
end

-- ============================================================================
-- EVENT HANDLERS
-- ============================================================================

--- Get events (defined events and nth_tick)
--- @return table {defined_events = {}, nth_tick = {}}
function M.get_events()
    return {
        defined_events = {},
        nth_tick = {
            [300] = M._on_nth_tick_agent_production_snapshot  -- Every 300 ticks (5 seconds)
        }
    }
end

-- ============================================================================
-- REMOTE INTERFACE REGISTRATION
-- ============================================================================

--- Register remote interface (empty for this module)
--- @return table Remote interface table
function M.register_remote_interface()
    return {}
end

return M

