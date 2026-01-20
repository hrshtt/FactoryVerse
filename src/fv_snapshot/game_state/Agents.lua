--- Agent production statistics snapshot module
--- Tracks agent production statistics and writes to snapshot files
--- This module depends on fv_embodied_agent for Agent class

local snapshot = require("utils.snapshot")
local Agents = require("__fv_embodied_agent__/game_state/Agents")
local udp_payloads = require("utils.udp_payloads")

local M = {}

-- ============================================================================
-- DEDUPLICATION STATE
-- ============================================================================

-- Track last written statistics to avoid duplicate writes
-- Structure: {agent_id = {production = {input = {...}, output = {...}}, manual = {crafted = {...}, mined = {...}}}}
local last_written_stats = {}

--- Compare two tables for equality (shallow comparison for stats)
--- @param t1 table|nil First table
--- @param t2 table|nil Second table
--- @return boolean True if tables have identical key-value pairs
local function tables_equal(t1, t2)
    if t1 == nil and t2 == nil then return true end
    if t1 == nil or t2 == nil then return false end
    if type(t1) ~= "table" or type(t2) ~= "table" then return t1 == t2 end

    -- Check all keys in t1 exist in t2 with same values
    for k, v in pairs(t1) do
        if type(v) == "table" then
            if not tables_equal(v, t2[k]) then return false end
        elseif t2[k] ~= v then
            return false
        end
    end

    -- Check no extra keys in t2
    for k, _ in pairs(t2) do
        if t1[k] == nil then return false end
    end

    return true
end

--- Check if production stats have changed since last write
--- @param agent_id number Agent ID
--- @param stats table Production statistics {input, output}
--- @return boolean True if stats have changed
local function production_stats_changed(agent_id, stats)
    local last = last_written_stats[agent_id] and last_written_stats[agent_id].production
    if not last then return true end
    return not tables_equal(stats.input, last.input) or not tables_equal(stats.output, last.output)
end

--- Check if manual stats have changed since last write
--- @param agent_id number Agent ID
--- @param stats table Manual statistics {crafted, mined}
--- @return boolean True if stats have changed
local function manual_stats_changed(agent_id, stats)
    local last = last_written_stats[agent_id] and last_written_stats[agent_id].manual
    if not last then return true end
    return not tables_equal(stats.crafted, last.crafted) or not tables_equal(stats.mined, last.mined)
end

--- Update last written production stats
--- @param agent_id number Agent ID
--- @param stats table Production statistics {input, output}
local function update_last_production_stats(agent_id, stats)
    last_written_stats[agent_id] = last_written_stats[agent_id] or {}
    -- Deep copy to avoid reference issues
    last_written_stats[agent_id].production = {
        input = {},
        output = {}
    }
    for k, v in pairs(stats.input or {}) do
        last_written_stats[agent_id].production.input[k] = v
    end
    for k, v in pairs(stats.output or {}) do
        last_written_stats[agent_id].production.output[k] = v
    end
end

--- Update last written manual stats
--- @param agent_id number Agent ID
--- @param stats table Manual statistics {crafted, mined}
local function update_last_manual_stats(agent_id, stats)
    last_written_stats[agent_id] = last_written_stats[agent_id] or {}
    -- Deep copy to avoid reference issues
    last_written_stats[agent_id].manual = {
        crafted = {},
        mined = {}
    }
    for k, v in pairs(stats.crafted or {}) do
        last_written_stats[agent_id].manual.crafted[k] = v
    end
    for k, v in pairs(stats.mined or {}) do
        last_written_stats[agent_id].manual.mined[k] = v
    end
end

-- ============================================================================
-- AGENT PRODUCTION SNAPSHOT
-- ============================================================================

--- Snapshot agent production statistics every nth tick
--- Writes to {agent_id}/production_statistics.jsonl
--- Only writes if statistics have changed since last write (deduplication)
function M._on_nth_tick_agent_production_snapshot()
    local agents = Agents.list_agent_forces()

    -- Early exit: No agents to process
    local has_agents = false
    for _ in pairs(agents) do
        has_agents = true
        break
    end
    if not has_agents then
        return
    end

    for agent_id, force_name in pairs(agents) do
        local agent = Agents.get_agent(agent_id)
        if agent and agent.character.valid then
            local stats = agent:get_production_statistics()
            if not stats then goto continue end

            -- Deduplication: only write if stats have changed
            if not production_stats_changed(agent_id, stats) then
                goto continue
            end

            -- Update last written stats
            update_last_production_stats(agent_id, stats)

            -- Append a snapshot entry in JSONL format
            local entry = {
                tick = game.tick,
                statistics = stats
            }
            local json_line = helpers.table_to_json(entry) .. "\n"
            local file_path = snapshot.SNAPSHOT_BASE_DIR .. "/" .. agent_id .. "/production_statistics.jsonl"

            -- Write to disk (return value ignored for determinism)
            helpers.write_file(file_path, json_line, true) -- append

            -- Send UDP notification for file append
            -- CRITICAL: Always send UDP regardless of write success to maintain Factorio determinism
            local payload = udp_payloads.file_appended("agent_production_statistics", nil, file_path, game.tick, 1)
            payload.agent_id = agent_id  -- Include agent_id in payload
            udp_payloads.send_file_io(payload)
        end
        ::continue::
    end
end

-- ============================================================================
-- AGENT MANUAL PRODUCTION SNAPSHOT
-- ============================================================================

--- Snapshot agent manual production statistics every nth tick
--- Writes to {agent_id}/manual_production_statistics.jsonl
--- Only writes if statistics have changed since last write (deduplication)
--- Manual stats track hand-crafted and hand-mined items (not automation)
function M._on_nth_tick_agent_manual_production_snapshot()
    local agents = Agents.list_agent_forces()

    -- Early exit: No agents to process
    local has_agents = false
    for _ in pairs(agents) do
        has_agents = true
        break
    end
    if not has_agents then
        return
    end

    for agent_id, force_name in pairs(agents) do
        local agent = Agents.get_agent(agent_id)
        if agent and agent.character.valid then
            local stats = agent:get_manual_production_statistics()
            if not stats then goto continue end

            -- Deduplication: only write if stats have changed
            if not manual_stats_changed(agent_id, stats) then
                goto continue
            end

            -- Update last written stats
            update_last_manual_stats(agent_id, stats)

            -- Append a snapshot entry in JSONL format
            local entry = {
                tick = game.tick,
                crafted = stats.crafted,
                mined = stats.mined
            }
            local json_line = helpers.table_to_json(entry) .. "\n"
            local file_path = snapshot.SNAPSHOT_BASE_DIR .. "/" .. agent_id .. "/manual_production_statistics.jsonl"

            -- Write to disk (return value ignored for determinism)
            helpers.write_file(file_path, json_line, true) -- append

            -- Send UDP notification for file append
            -- CRITICAL: Always send UDP regardless of write success to maintain Factorio determinism
            local payload = udp_payloads.file_appended("agent_manual_production_statistics", nil, file_path, game.tick, 1)
            payload.agent_id = agent_id  -- Include agent_id in payload
            udp_payloads.send_file_io(payload)
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
            -- Both snapshots run every 300 ticks (5 seconds)
            -- They are grouped together since they can share the same tick interval
            [300] = {
                M._on_nth_tick_agent_production_snapshot,
                M._on_nth_tick_agent_manual_production_snapshot
            }
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

