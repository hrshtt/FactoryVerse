--- factorio_verse/core/game_state/PowerGameState.lua
--- PowerGameState sub-module for managing power-related functionality.
--- Static module - no instantiation required.

-- Module-level local references for global lookups (performance optimization)
-- (This module currently doesn't use many globals, but kept for consistency)

local GameStateError = require("utils.Error")

local snapshot = require("utils.snapshot")
local udp_payloads = require("utils.udp_payloads")

local M = {}

-- ============================================================================
-- DEDUPLICATION STATE
-- ============================================================================

-- Track last written power statistics to avoid duplicate writes
local last_written_power_stats = nil

--- Compare two tables for equality (shallow comparison)
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

--- Check if power stats have changed since last write
--- @param stats table Power statistics {input, output, storage}
--- @return boolean True if stats have changed
local function power_stats_changed(stats)
    if not last_written_power_stats then return true end
    return not tables_equal(stats.input, last_written_power_stats.input) or
           not tables_equal(stats.output, last_written_power_stats.output) or
           not tables_equal(stats.storage, last_written_power_stats.storage)
end

--- Update last written power stats (deep copy)
--- @param stats table Power statistics {input, output, storage}
local function update_last_power_stats(stats)
    last_written_power_stats = {
        input = {},
        output = {},
        storage = {}
    }
    for k, v in pairs(stats.input or {}) do
        last_written_power_stats.input[k] = v
    end
    for k, v in pairs(stats.output or {}) do
        last_written_power_stats.output[k] = v
    end
    for k, v in pairs(stats.storage or {}) do
        last_written_power_stats.storage[k] = v
    end
end

-- ============================================================================
-- POWER STATISTICS API
-- ============================================================================

function M.get_global_power_statistics()
    local surface = game.surfaces[1]
    if not surface.global_electric_network_statistics then
        surface.create_global_electric_network()
    end

    local stats = surface.global_electric_network_statistics

    -- Placeholder for power production logic
    return {input = stats.input_counts, output = stats.output_counts, storage = stats.storage_counts}
end

function M._on_nth_tick_global_power_snapshot()
    -- Early exit: Check if surface exists before processing
    local surface = game.surfaces[1]
    if not surface then
        return
    end

    local stats = M.get_global_power_statistics()
    if not stats then return end

    -- Early exit: Don't write if all statistics are empty
    local input = stats.input or {}
    local output = stats.output or {}
    local storage = stats.storage or {}

    -- Check if all three tables are empty (no keys)
    if next(input) == nil and next(output) == nil and next(storage) == nil then
        return
    end

    -- Deduplication: only write if stats have changed
    if not power_stats_changed(stats) then
        return
    end

    -- Update last written stats
    update_last_power_stats(stats)

    -- Append a snapshot entry in JSONL format
    local entry = {
        tick = game.tick,
        statistics = stats
    }
    local json_line = helpers.table_to_json(entry) .. "\n"
    local file_path = snapshot.SNAPSHOT_BASE_DIR .. "/global_power_statistics.jsonl"

    -- Write to disk (return value ignored for determinism)
    helpers.write_file(file_path, json_line, true) -- append

    -- Send UDP notification for file append
    -- CRITICAL: Always send UDP regardless of write success to maintain Factorio determinism
    local payload = udp_payloads.file_appended("power_statistics", nil, file_path, game.tick, 1)
    udp_payloads.send_file_io(payload)
end

M.power_api = {}

--- Get on_tick handlers
--- @return table Array of handler functions
function M.get_on_tick_handlers()
    return {}
end

--- Get events (defined events and nth_tick)
--- @return table {defined_events = {}, nth_tick = {}}
function M.get_events()
    return {
        defined_events = {},
        nth_tick = {[300] = M._on_nth_tick_global_power_snapshot}
    }
end

--- Register remote interface for power admin methods
--- @return table Remote interface table
function M.register_remote_interface()
    return M.power_api
end

return M
