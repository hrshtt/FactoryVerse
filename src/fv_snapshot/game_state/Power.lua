--- factorio_verse/core/game_state/PowerGameState.lua
--- PowerGameState sub-module for managing power-related functionality.
--- Static module - no instantiation required.

-- Module-level local references for global lookups (performance optimization)
-- (This module currently doesn't use many globals, but kept for consistency)

local GameStateError = require("utils.Error")

local snapshot = require("utils.snapshot")
local udp_payloads = require("utils.udp_payloads")
local forces = require("utils.forces")

-- Static tables/handles built at require time (frozen-runtime rule: no dynamic
-- require, no per-tick rebuild). `defines` is available in the control stage.
local FIVE_SECONDS = defines.flow_precision_index.five_seconds

-- Cache helpers for the per-network sampler hot path (called every 5s over all
-- charted poles). The legacy global path below keeps its inline helpers.* calls
-- unchanged on purpose.
local table_to_json = helpers.table_to_json
local write_file = helpers.write_file

local M = {}

-- ============================================================================
-- PER-NETWORK POWER SAMPLER  (module docstring)
-- ----------------------------------------------------------------------------
-- Writes one JSONL line per 5s window to factoryverse/snapshots/power_networks.jsonl
-- describing every *live* electric network (poles grouped by electric_network_id).
--
-- Semantics that callers/ingesters MUST understand:
--   * PER-SAMPLE ID: engine `electric_network_id` is EPHEMERAL — it renumbers
--     arbitrarily when a network splits/merges, and the engine's stat history
--     rides that id. It is a per-sample handle ONLY. The durable reference for a
--     network is its ANCHOR POLE (name + position).
--   * ANCHOR-POLE RULE: within a network, the anchor is the pole with the
--     lexicographically smallest (x, y). This is order-independent (a min), so it
--     is deterministic across consecutive samples of an unchanged network.
--   * UNIT CONVENTION: get_flow_count returns Joules/tick; watts = J/tick * 60.
--     `input_counts` keys are CONSUMER prototypes (-> consumption_w_by_prototype),
--     `output_counts` keys are PRODUCER prototypes (-> production_w_by_prototype).
--     `category=` is REQUIRED in 2.0 ('input'|'output'); the 2.x boolean form is
--     rejected. Stats are read ONCE per network, from the anchor pole.
--   * READER-PASSIVITY LAW (GLOBAL-NET-1 / cert L1.14): this sampler is strictly
--     read-only. It NEVER creates or destroys a network and NEVER touches
--     create_global_electric_network — reading such stats would power the whole
--     surface (Fulgora mechanic) and mutate physics.
--   * HEARTBEAT: exactly one line is written per window, ALWAYS — even with zero
--     networks ({"tick":N,"networks":[]}). No value-dedup (the old dedup pattern
--     on the global path below caused the VERIF-1 frozen-feed class; the new file
--     must not repeat it).
-- ============================================================================

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
    -- GLOBAL-NET-1: never create the global electric network from a reader.
    -- Creating it powers every electric entity on the surface without poles
    -- (Fulgora mechanic), so the stats snapshot would mutate game physics.
    -- No global network => report empty stats.
    if not surface.has_global_electric_network then
        return {input = {}, output = {}, storage = {}}
    end

    local stats = surface.global_electric_network_statistics
    if not stats then
        return {input = {}, output = {}, storage = {}}
    end

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

-- ============================================================================
-- PER-NETWORK POWER SAMPLER
-- ============================================================================

--- Sample every live electric network and append exactly ONE jsonl line.
--- Read-only (GLOBAL-NET-1 / L1.14). See the module docstring for id/anchor/unit
--- semantics. Runs only during MAINTENANCE (see gating note below).
function M._on_nth_tick_power_networks_sample()
    -- PHASE GATING (judgment call, documented): the aggregator in control.lua
    -- registers Power's nth_tick handlers WITHOUT phase gating (unlike the
    -- Entities status walk, which control.lua gates inline). We gate here.
    -- We read storage.system_state.phase DIRECTLY rather than require("game_state.Map"):
    -- Map does not require Power today (no cycle *today*), but reading the storage
    -- Map owns is the same source of truth (Map.get_system_phase just returns
    -- storage.system_state.phase) with zero inter-module coupling and no require-order
    -- fragility. During INITIAL_SNAPSHOTTING (or before system_state exists) we emit
    -- nothing — matching the status walk, and safe because charting is still in flight.
    local sys = storage.system_state
    if not (sys and sys.phase == "MAINTENANCE") then
        return
    end

    local surface = game.surfaces[1]
    if not surface then
        return
    end

    local tracked = forces.get_tracked_forces()

    -- (1) Enumerate poles (per C1) and group by electric_network_id.
    -- networks[nid] = { anchor = <LuaEntity pole>, pole_count = n }
    local poles = surface.find_entities_filtered{type = "electric-pole", force = tracked}
    local networks = {}
    local n_poles = #poles
    for i = 1, n_poles do
        local pole = poles[i]
        if pole and pole.valid then
            local nid = pole.electric_network_id
            if nid ~= nil then
                local net = networks[nid]
                if net == nil then
                    networks[nid] = {anchor = pole, pole_count = 1}
                else
                    net.pole_count = net.pole_count + 1
                    -- Anchor = lexicographically smallest (x, y). Order-independent min.
                    local ap = net.anchor.position
                    local pp = pole.position
                    if pp.x < ap.x or (pp.x == ap.x and pp.y < ap.y) then
                        net.anchor = pole
                    end
                end
            end
        end
    end

    -- (2) ONE member scan per window over all tracked-force entities. Bucket
    -- member_count by network id, and (cheaply, in the same pass) accumulate
    -- storage_j from accumulator `energy` (current stored joules). storage_j is
    -- therefore best-effort = sum of accumulator energy among members; 0.0 when a
    -- network has no accumulators (per C1 this is acceptable).
    local member_count_by_id = {}
    local storage_j_by_id = {}
    local members = surface.find_entities_filtered{force = tracked}
    local n_members = #members
    for i = 1, n_members do
        local e = members[i]
        if e and e.valid then
            local nid = e.electric_network_id
            if nid ~= nil then
                member_count_by_id[nid] = (member_count_by_id[nid] or 0) + 1
                if e.type == "accumulator" then
                    storage_j_by_id[nid] = (storage_j_by_id[nid] or 0.0) + e.energy
                end
            end
        end
    end

    -- (3) Build one network object per group, reading stats ONCE from the anchor.
    local networks_out = {}
    for nid, net in pairs(networks) do
        local anchor = net.anchor
        local stats = anchor.electric_network_statistics
        local production_by = {}
        local consumption_by = {}
        local production_w = 0.0
        local consumption_w = 0.0

        if stats then
            -- output_counts keys = PRODUCER prototypes -> production
            for proto in pairs(stats.output_counts) do
                local w = stats.get_flow_count{
                    name = proto,
                    category = "output",
                    precision_index = FIVE_SECONDS,
                } * 60
                production_by[proto] = w
                production_w = production_w + w
            end
            -- input_counts keys = CONSUMER prototypes -> consumption
            for proto in pairs(stats.input_counts) do
                local w = stats.get_flow_count{
                    name = proto,
                    category = "input",
                    precision_index = FIVE_SECONDS,
                } * 60
                consumption_by[proto] = w
                consumption_w = consumption_w + w
            end
        end

        local apos = anchor.position
        networks_out[#networks_out + 1] = {
            network_id = nid,
            anchor_pole = {
                name = anchor.name,
                position = {x = apos.x, y = apos.y},
            },
            pole_count = net.pole_count,
            member_count = member_count_by_id[nid] or 0,
            production_w = production_w,
            consumption_w = consumption_w,
            storage_j = storage_j_by_id[nid] or 0.0,
            production_w_by_prototype = production_by,
            consumption_w_by_prototype = consumption_by,
        }
    end

    -- Stable, deterministic array order (pairs() over sparse int keys is unordered).
    table.sort(networks_out, function(a, b) return a.network_id < b.network_id end)

    -- (4) Write EXACTLY ONE line, ALWAYS (heartbeat). No value-dedup.
    -- helpers.table_to_json serializes an EMPTY Lua table as `{}`, not `[]`, so we
    -- special-case the zero-network heartbeat to honor the frozen C1 line shape
    -- `{"tick":N,"networks":[]}` exactly. The non-empty case is a 1..n sequence and
    -- serializes as a JSON array correctly.
    local json_line
    if #networks_out == 0 then
        json_line = '{"tick":' .. game.tick .. ',"networks":[]}\n'
    else
        json_line = table_to_json({tick = game.tick, networks = networks_out}) .. "\n"
    end

    local file_path = snapshot.SNAPSHOT_BASE_DIR .. "/power_networks.jsonl"

    -- Write to disk (return value ignored for determinism).
    write_file(file_path, json_line, true) -- append

    -- CRITICAL: send UDP unconditionally after attempting the write, regardless of
    -- write success, to maintain Factorio determinism (mirrors Power.lua global path).
    local payload = udp_payloads.file_appended("power_networks", nil, file_path, game.tick, 1)
    udp_payloads.send_file_io(payload)
end

--- Composed nth_tick(300) handler: global reader THEN per-network sampler.
--- Both the honest-empty global snapshot and the per-network sampler want the
--- 300-tick window; get_events returns a single handler per interval, so we
--- compose them deterministically (global first, then sampler). The global
--- handler body is unchanged.
function M._on_nth_tick_power_300()
    M._on_nth_tick_global_power_snapshot()
    M._on_nth_tick_power_networks_sample()
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
        -- Composed 300-tick handler: global snapshot THEN per-network sampler.
        nth_tick = {[300] = M._on_nth_tick_power_300}
    }
end

--- Register remote interface for power admin methods
--- @return table Remote interface table
function M.register_remote_interface()
    return M.power_api
end

return M
