--- Agent production statistics snapshot module
--- Tracks agent production statistics and writes to snapshot files
--- This module depends on fv_embodied_agent for custom events (accessed via remote.call)
---
--- File structure:
---   factoryverse/agent-snapshots/{agent_id}/
---     production-statistics.jsonl  - Force-level production (polled every 60 ticks / 1 second)
---     crafting-statistics.jsonl    - Manual crafting counts (event-driven)
---     mining-statistics.jsonl      - Manual mining counts (event-driven)
---
--- Production stats use nth_tick polling since they're cumulative force-level stats.
--- Polling at 60 ticks (1 second) provides responsive rate calculation for throughput verification.
--- Deduplication ensures we only write to disk when stats actually change.
--- Crafting and mining stats use custom events for precise action logging.
---
--- IMPORTANT: fv_embodied_agent data must be accessed via remote.call(), not require().
--- Each mod has isolated storage - require() would access fv_snapshot's storage, not fv_embodied_agent's.

local utils = require("utils.utils")
local udp_payloads = require("utils.udp_payloads")

local M = {}

-- ============================================================================
-- CONSTANTS
-- ============================================================================

-- Agent snapshot directory (separate from chunk-based map snapshots)
local AGENT_SNAPSHOT_DIR = "factoryverse/agent-snapshots"

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

--- Build file path for agent statistics
--- @param agent_id number Agent ID
--- @param stat_type string Statistics type ("production", "crafting", "mining")
--- @return string File path
local function get_agent_stat_path(agent_id, stat_type)
    return AGENT_SNAPSHOT_DIR .. "/" .. tostring(agent_id) .. "/" .. stat_type .. "-statistics.jsonl"
end

--- Check if there are any agents to process
--- Uses remote.call to access fv_embodied_agent's storage
--- @return boolean True if there are agents
local function has_agents()
    if not remote.interfaces.agent then
        return false
    end
    local agents = remote.call("agent", "list_agents")
    return agents and #agents > 0
end

--- Get list of agents with their details
--- Uses remote.call to access fv_embodied_agent's storage
--- @return table[] Array of agent entries
local function get_agents()
    if not remote.interfaces.agent then
        return {}
    end
    return remote.call("agent", "list_agents") or {}
end

--- Deep compare two tables for equality
--- @param t1 table First table
--- @param t2 table Second table
--- @return boolean True if tables are equal
local function tables_equal(t1, t2)
    if t1 == t2 then return true end
    if type(t1) ~= "table" or type(t2) ~= "table" then return false end

    -- Check all keys in t1
    for k, v in pairs(t1) do
        if type(v) == "table" then
            if not tables_equal(v, t2[k]) then return false end
        elseif v ~= t2[k] then
            return false
        end
    end

    -- Check for keys in t2 not in t1
    for k, _ in pairs(t2) do
        if t1[k] == nil then return false end
    end

    return true
end

--- Get or initialize the last production stats storage
--- @return table Storage for last production stats per agent
local function get_last_production_stats()
    if not storage.last_production_stats then
        storage.last_production_stats = {}
    end
    return storage.last_production_stats
end

--- Delete agent statistics files for a given agent
--- Uses helpers.remove_path to delete the agent's statistics directory
--- Note: remove_path returns nil (no way to know if deletion succeeded)
--- @param agent_id number Agent ID
local function delete_agent_statistics(agent_id)
    -- Delete individual statistics files
    local stat_types = {"production", "crafting", "mining"}
    for _, stat_type in ipairs(stat_types) do
        local file_path = get_agent_stat_path(agent_id, stat_type)
        helpers.remove_path(file_path)
    end

    -- Also try to remove the agent directory itself (will only work if empty)
    local agent_dir = AGENT_SNAPSHOT_DIR .. "/" .. tostring(agent_id)
    helpers.remove_path(agent_dir)

    -- Clear last production stats cache for this agent
    local last_stats = get_last_production_stats()
    local agent_key = tostring(agent_id)
    last_stats[agent_key] = nil

    log("[Agents] Deleted statistics for agent " .. tostring(agent_id))
end

-- ============================================================================
-- AGENT PRODUCTION STATISTICS SNAPSHOT (POLLED)
-- ============================================================================

--- Snapshot agent force-level production statistics every nth tick
--- Writes to factoryverse/agent-snapshots/{agent_id}/production-statistics.jsonl
--- This is the aggregate production from automation (assemblers, furnaces, etc.)
--- Uses remote.call to access each agent's interface for production statistics
--- Deduplication: Only writes if stats changed from last snapshot
function M._on_nth_tick_agent_production_snapshot()
    if not has_agents() then
        return
    end

    local agents = get_agents()
    local last_stats = get_last_production_stats()

    for _, agent_info in ipairs(agents) do
        local agent_id = agent_info.id
        local force_name = agent_info.force
        local interface_name = agent_info.interface_name

        -- Skip if agent entity is invalid
        if not agent_info.entity_valid then
            goto continue
        end

        -- Get production statistics via remote.call to the agent's interface
        if not remote.interfaces[interface_name] or not remote.interfaces[interface_name].get_production_statistics then
            goto continue
        end

        local stats = remote.call(interface_name, "get_production_statistics")
        if not stats then goto continue end

        local current_input = stats.input or {}
        local current_output = stats.output or {}

        -- Deduplication: Skip if unchanged from last snapshot
        local agent_key = tostring(agent_id)
        local last = last_stats[agent_key]
        if last then
            -- Compare input and output with last snapshot
            if tables_equal(current_input, last.input) and tables_equal(current_output, last.output) then
                -- No change, skip writing
                goto continue
            end
        end

        -- Stats changed (or first snapshot) - write to disk
        local entry = {
            tick = game.tick,
            agent_id = agent_id,
            force_name = force_name,
            input = current_input,
            output = current_output
        }
        local json_line = helpers.table_to_json(entry) .. "\n"
        local file_path = get_agent_stat_path(agent_id, "production")

        -- Write to disk (return value ignored for determinism)
        helpers.write_file(file_path, json_line, true) -- append

        -- Update last stats for deduplication
        last_stats[agent_key] = {
            input = current_input,
            output = current_output
        }

        -- Send UDP notification for file append
        local payload = udp_payloads.file_appended("agent_production_statistics", nil, file_path, game.tick, 1)
        payload.agent_id = agent_id
        payload.force_name = force_name
        udp_payloads.send_file_io(payload)

        ::continue::
    end
end

-- ============================================================================
-- AGENT CRAFTING STATISTICS (EVENT-DRIVEN)
-- ============================================================================

--- Handle agent crafting completed event
--- Writes to factoryverse/agent-snapshots/{agent_id}/crafting-statistics.jsonl
--- @param event table Event data with agent_id, tick, recipe, count_crafted, products
function M._on_agent_crafting_completed(event)
    local agent_id = event.agent_id
    if not agent_id then return end

    -- Append a snapshot entry in JSONL format
    local entry = {
        tick = event.tick or game.tick,
        agent_id = agent_id,
        recipe = event.recipe,
        count_crafted = event.count_crafted,
        products = event.products or {}
    }
    local json_line = helpers.table_to_json(entry) .. "\n"
    local file_path = get_agent_stat_path(agent_id, "crafting")

    -- Write to disk
    helpers.write_file(file_path, json_line, true) -- append

    -- Send UDP notification for file append
    local payload = udp_payloads.file_appended("agent_crafting_statistics", nil, file_path, event.tick or game.tick, 1)
    payload.agent_id = agent_id
    payload.recipe = event.recipe
    udp_payloads.send_file_io(payload)
end

-- ============================================================================
-- AGENT MINING STATISTICS (EVENT-DRIVEN)
-- ============================================================================

--- Handle agent mining completed event
--- Writes to factoryverse/agent-snapshots/{agent_id}/mining-statistics.jsonl
--- @param event table Event data with agent_id, tick, entity_name, entity_type, position, mode, reason, products
function M._on_agent_mining_completed(event)
    local agent_id = event.agent_id
    if not agent_id then return end

    -- Append a snapshot entry in JSONL format
    local entry = {
        tick = event.tick or game.tick,
        agent_id = agent_id,
        entity_name = event.entity_name,
        entity_type = event.entity_type,
        position = event.position,
        mode = event.mode,
        reason = event.reason,
        products = event.products or {}
    }
    local json_line = helpers.table_to_json(entry) .. "\n"
    local file_path = get_agent_stat_path(agent_id, "mining")

    -- Write to disk
    helpers.write_file(file_path, json_line, true) -- append

    -- Send UDP notification for file append
    local payload = udp_payloads.file_appended("agent_mining_statistics", nil, file_path, event.tick or game.tick, 1)
    payload.agent_id = agent_id
    payload.entity_name = event.entity_name
    udp_payloads.send_file_io(payload)
end

-- ============================================================================
-- AGENT LIFECYCLE HANDLERS
-- ============================================================================

--- Handle agent removed event
--- Deletes agent statistics files when agent is destroyed
--- @param event table Event data with agent_id
function M._on_agent_removed(event)
    local agent_id = event.agent_id
    if not agent_id then return end

    delete_agent_statistics(agent_id)
end

-- ============================================================================
-- EVENT HANDLERS
-- ============================================================================

--- Get custom event IDs from fv_embodied_agent
--- Must be called after fv_embodied_agent has initialized
--- Uses remote.call - cannot access fv_embodied_agent's storage directly
--- @return table|nil Custom events table or nil if not available
local function get_custom_events()
    -- Must use remote.call - fv_embodied_agent's storage is isolated from fv_snapshot
    if remote.interfaces.custom_events and remote.interfaces.custom_events.get_custom_events then
        return remote.call("custom_events", "get_custom_events")
    end
    return nil
end

--- Get events (defined events and nth_tick)
--- @return table {defined_events = {}, nth_tick = {}, custom_events = {}}
function M.get_events()
    local events = {
        defined_events = {},
        nth_tick = {
            -- Production stats polled every 60 ticks (1 second)
            -- Frequent polling enables responsive rate calculation for throughput verification
            -- Deduplication ensures we only write to disk when stats actually change
            [60] = {
                M._on_nth_tick_agent_production_snapshot,
            }
        },
        custom_events = {}
    }

    -- Register handlers for custom events from fv_embodied_agent
    -- These will be resolved at event dispatcher initialization time
    local custom = get_custom_events()
    if custom then
        if custom.on_agent_crafting_completed then
            events.custom_events[custom.on_agent_crafting_completed] = M._on_agent_crafting_completed
        end
        if custom.on_agent_mining_completed then
            events.custom_events[custom.on_agent_mining_completed] = M._on_agent_mining_completed
        end
        if custom.on_agent_removed then
            events.custom_events[custom.on_agent_removed] = M._on_agent_removed
        end
    else
        log("[Agents] Warning: Custom events not available yet. Event handlers will be registered later.")
    end

    return events
end

-- ============================================================================
-- DEFERRED EVENT REGISTRATION
-- ============================================================================

--- Register custom event handlers (called after fv_embodied_agent initializes)
--- This is a fallback for when get_events() is called before custom events are available
function M.register_deferred_events()
    local custom = get_custom_events()
    if not custom then
        log("[Agents] Error: Cannot register deferred events - custom events still not available")
        return false
    end

    if custom.on_agent_crafting_completed then
        script.on_event(custom.on_agent_crafting_completed, M._on_agent_crafting_completed)
        log("[Agents] Registered on_agent_crafting_completed handler")
    end

    if custom.on_agent_mining_completed then
        script.on_event(custom.on_agent_mining_completed, M._on_agent_mining_completed)
        log("[Agents] Registered on_agent_mining_completed handler")
    end

    if custom.on_agent_removed then
        script.on_event(custom.on_agent_removed, M._on_agent_removed)
        log("[Agents] Registered on_agent_removed handler")
    end

    return true
end

-- ============================================================================
-- REMOTE INTERFACE REGISTRATION
-- ============================================================================

--- Register remote interface
--- @return table Remote interface table
function M.register_remote_interface()
    return {
        -- Get the agent snapshot directory path
        get_agent_snapshot_dir = function()
            return AGENT_SNAPSHOT_DIR
        end,
        -- Force a snapshot write for a specific agent (useful for testing/debugging)
        force_snapshot_agent = function(agent_id)
            local interface_name = "agent_" .. tostring(agent_id)

            -- Check if agent interface exists
            if not remote.interfaces[interface_name] then
                return { success = false, error = "Agent not found: " .. tostring(agent_id) }
            end

            -- Get production stats via remote call
            if remote.interfaces[interface_name].get_production_statistics then
                local stats = remote.call(interface_name, "get_production_statistics")
                if stats then
                    -- Get force name from agent info
                    local agents = remote.call("agent", "list_agents") or {}
                    local force_name = "unknown"
                    for _, agent_info in ipairs(agents) do
                        if agent_info.id == agent_id then
                            force_name = agent_info.force
                            break
                        end
                    end

                    local entry = {
                        tick = game.tick,
                        agent_id = agent_id,
                        force_name = force_name,
                        input = stats.input or {},
                        output = stats.output or {}
                    }
                    helpers.write_file(get_agent_stat_path(agent_id, "production"), helpers.table_to_json(entry) .. "\n", true)
                end
            end

            return { success = true, agent_id = agent_id }
        end,
        -- Register deferred event handlers (called by control.lua after on_init)
        register_deferred_events = M.register_deferred_events,
    }
end

return M
