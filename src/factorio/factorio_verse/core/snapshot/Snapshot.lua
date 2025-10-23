local GameState = require "core.game_state.GameState"
local EntitiesSnapshot = require "core.snapshot.EntitiesSnapshot"
local ResourceSnapshot = require "core.snapshot.ResourceSnapshot"
local AgentSnapshot = require "core.snapshot.AgentSnapshot"
local utils = require "utils"

--- Snapshot Orchestrator: Unified entry point for all snapshot operations
--- Handles disk writes, async processing, and RCON responses
--- @class Snapshot
--- @field game_state GameState
local Snapshot = {}
Snapshot.__index = Snapshot

-- Singleton instance
local _instance = nil

--- Get singleton instance
--- @return Snapshot
function Snapshot:get_instance()
    if not _instance then
        _instance = {
            game_state = GameState:new()
        }
        setmetatable(_instance, self)
    end
    return _instance
end

--- Legacy new() method for backward compatibility (returns singleton)
--- @return Snapshot
function Snapshot:new()
    return self:get_instance()
end

--- Standard output structure for all snapshots
--- @param snapshot_type string - type identifier (e.g. "resources", "entities")
--- @param version string - schema version
--- @param data table - the actual snapshot data
--- @return table - standardized output structure
function Snapshot:create_output(snapshot_type, version, data)
    local surface = self.game_state:get_surface()
    return {
        schema_version = snapshot_type .. "." .. version,
        surface = surface and surface.name or "unknown",
        timestamp = game and game.tick or 0,
        data = data
    }
end

--- Print snapshot summary to console and RCON
--- @param output table - snapshot output to summarize
--- @param summary_fn function - optional function to create custom summary
function Snapshot:print_summary(output, summary_fn)
    local summary = output
    if summary_fn then
        summary = summary_fn(output)
    end

    local json_str = helpers.table_to_json(summary)
    utils.triple_print(json_str)
end

-- ============================================================================
-- PUBLIC API METHODS
-- ============================================================================

--- Take complete map snapshot (async if requested)
--- @param options table - {
---   components = {"entities", "resources"}, -- optional, defaults to both
---   async = true,                           -- optional, defaults to false
---   chunks_per_tick = 2                     -- optional, defaults to 2 when async=true
--- }
--- @return table - {status, session_id} or {status, stats} for sync
function Snapshot:take_map_snapshot(options)
    options = options or {}
    local components = options.components or { "entities", "resources" }
    local async = options.async or false
    local chunks_per_tick = options.chunks_per_tick or 2

    local charted_chunks = self.game_state:get_charted_chunks()

    if not async then
        -- Synchronous: process all chunks immediately
        return self:_process_all_chunks_sync(charted_chunks, components)
    else
        -- Asynchronous: create session and process over multiple ticks
        return self:_create_snapshot_session(charted_chunks, components, chunks_per_tick)
    end
end

--- Take snapshot for a single chunk (always synchronous)
--- @param chunk_x number
--- @param chunk_y number
--- @param options table - {components = {"entities", "resources"}}
--- @return table - {entities_written, resources_written, manifests_written}
function Snapshot:take_chunk_snapshot(chunk_x, chunk_y, options)
    options = options or {}
    local components = options.components or { "entities", "resources" }

    local chunk = {
        x = chunk_x,
        y = chunk_y,
        area = {
            left_top = { x = chunk_x * 32, y = chunk_y * 32 },
            right_bottom = { x = (chunk_x + 1) * 32, y = (chunk_y + 1) * 32 }
        }
    }

    return self:_process_single_chunk(chunk, components)
end

--- Take snapshot of specific entities for RCON (uses inventory view)
--- @param unit_numbers table - array of unit numbers
--- @return string - JSON string for RCON
function Snapshot:take_entity_inventory(unit_numbers)
    local results = EntitiesSnapshot.get_inventory_views(unit_numbers)
    return helpers.table_to_json({ entities = results, count = #unit_numbers })
end

--- Take snapshot of agent (uses agent view)
--- @param agent_id number - agent ID
--- @return string - JSON string for RCON
function Snapshot:take_agent_snapshot(agent_id)
    local result = AgentSnapshot.get_agent_view(agent_id)
    return helpers.table_to_json(result)
end

--- Take recurring snapshot of entity status (every 60 ticks)
--- Appends status records to JSONL files per chunk
--- @return table - {chunks_processed, status_records}
function Snapshot:take_recurring_status()
    local charted_chunks = self.game_state:get_charted_chunks()

    if not self.game_state:get_surface() then
        return { chunks_processed = 0, status_records = 0 }
    end

    local chunks_processed = 0
    local total_records = 0

    for _, chunk in ipairs(charted_chunks) do
        -- Get status view from EntitiesSnapshot
        local status_records = EntitiesSnapshot.get_status_view_for_chunk(chunk)

        if #status_records > 0 then
            local opts = {
                output_dir = "script-output/factoryverse",
                chunk_x = chunk.x,
                chunk_y = chunk.y
            }
            self:emit_status_jsonl(opts, status_records)
            chunks_processed = chunks_processed + 1
            total_records = total_records + #status_records
        end
    end

    return { chunks_processed = chunks_processed, status_records = total_records }
end

--- Update single entity after action mutation (called from Action:_post_run)
--- @param unit_number number
--- @param last_position table|nil - {x, y} if entity was moved/removed
--- @return boolean - success
function Snapshot:update_entity_from_action(unit_number, last_position)
    local entity = game.get_entity_by_unit_number(unit_number)
    if not entity or not entity.valid then
        return self:remove_entity_from_action(unit_number, last_position)
    end

    local chunks = self:_get_entity_chunks(entity)
    local component_type = EntitiesSnapshot.determine_component_type(entity.type, entity.name)
    local serialized = EntitiesSnapshot.serialize_entity(entity, {})
    if not serialized then
        return false
    end

    -- Write to all affected chunks (handles multi-chunk entities)
    for _, chunk in ipairs(chunks) do
        local opts = {
            output_dir = "script-output/factoryverse",
            chunk_x = chunk.x,
            chunk_y = chunk.y,
            tick = game.tick or 0
        }

        self:emit_entity_json(opts, component_type, unit_number, entity.name, serialized)
        self:_update_component_manifest(chunk.x, chunk.y, component_type)
    end

    return true
end

--- Remove entity files after action removal (called from Action:_post_run)
--- @param unit_number number
--- @param last_position table|nil - {x, y} for chunk calculation
--- @return boolean - success
function Snapshot:remove_entity_from_action(unit_number, last_position)
    if not last_position then return false end

    local chunk_x = math.floor(last_position.x / 32)
    local chunk_y = math.floor(last_position.y / 32)

    -- Remove from all component directories
    local component_types = { "entities", "belts", "pipes", "poles" }
    for _, comp_type in ipairs(component_types) do
        local file_pattern = string.format("script-output/factoryverse/chunks/%d/%d/%s/%d-*.json",
            chunk_x, chunk_y, comp_type, unit_number)
        pcall(helpers.remove_path, file_pattern)
    end

    -- Update manifests
    for _, comp_type in ipairs(component_types) do
        self:_update_component_manifest(chunk_x, chunk_y, comp_type)
    end

    return true
end

function Snapshot:emit_json(opts, name, payload)
    local base_dir = (opts and opts.output_dir) or "script-output/factoryverse"

    -- Get chunk coordinates from opts or derive from payload
    local chunk_x = (opts and opts.chunk_x) or 0
    local chunk_y = (opts and opts.chunk_y) or 0
    local chunk_dir = string.format("%s/chunks/%d/%d", base_dir, chunk_x, chunk_y)

    -- Get tick for filename
    local tick = (opts and opts.tick) or (payload and payload.meta and payload.meta.tick) or (game and game.tick) or 0

    -- New filename format: script-output/factoryverse/chunks/<chunkx>/<chunky>/{type}-<tick>.json
    local file_path = string.format("%s/%s-%d.json", chunk_dir, name, tick)

    -- Ensure a fresh write: try to remove any existing file first
    if helpers and helpers.remove_path then
        pcall(helpers.remove_path, file_path)
    end

    -- Factorio will create subdirs under script-output if needed.
    local json_str = helpers.table_to_json(payload)
    helpers.write_file(file_path, json_str, false)

    -- Optional: print where it was written
    return file_path
end

--- Emit entity JSON file for a specific entity
--- @param opts table - options {output_dir, chunk_x, chunk_y, tick}
--- @param component_type string - component type ("entities", "belts", "pipes", "poles")
--- @param unit_number number - entity unit number
--- @param entity_name string - entity prototype name
--- @param payload table - entity data to serialize
--- @return string - file path written
function Snapshot:emit_entity_json(opts, component_type, unit_number, entity_name, payload)
    local base_dir = (opts and opts.output_dir) or "script-output/factoryverse"

    -- Get chunk coordinates from opts
    local chunk_x = (opts and opts.chunk_x) or 0
    local chunk_y = (opts and opts.chunk_y) or 0
    local chunk_dir = string.format("%s/chunks/%d/%d", base_dir, chunk_x, chunk_y)

    -- Create component subdirectory
    local component_dir = string.format("%s/%s", chunk_dir, component_type)

    -- Get tick for metadata
    local tick = (opts and opts.tick) or (game and game.tick) or 0

    -- Add tick to payload for tracking
    payload.tick = tick

    -- Filename format: {unit_number}-{entity_name}.json
    local file_path = string.format("%s/%d-%s.json", component_dir, unit_number, entity_name)

    -- Atomic write: remove existing file first, then write new one
    if helpers and helpers.remove_path then
        pcall(helpers.remove_path, file_path)
    end

    -- Factorio will create subdirs under script-output if needed
    local json_str = helpers.table_to_json(payload)
    helpers.write_file(file_path, json_str, false)

    return file_path
end

--- Emit status records to JSONL file (append-only)
--- @param opts table - options {output_dir, chunk_x, chunk_y}
--- @param status_records table - array of status records
--- @return string - file path written
function Snapshot:emit_status_jsonl(opts, status_records)
    local base_dir = (opts and opts.output_dir) or "script-output/factoryverse"

    -- Get chunk coordinates from opts
    local chunk_x = (opts and opts.chunk_x) or 0
    local chunk_y = (opts and opts.chunk_y) or 0
    local chunk_dir = string.format("%s/chunks/%d/%d", base_dir, chunk_x, chunk_y)

    -- Create entities subdirectory
    local entities_dir = string.format("%s/entities", chunk_dir)
    local file_path = string.format("%s/status.jsonl", entities_dir)

    -- Convert records to JSONL format
    local jsonl_lines = {}
    for _, record in ipairs(status_records) do
        table.insert(jsonl_lines, helpers.table_to_json(record))
    end
    local jsonl_data = table.concat(jsonl_lines, "\n") .. "\n"

    -- Append to file (create if doesn't exist)
    helpers.write_file(file_path, jsonl_data, true)

    return file_path
end

--- Emit resource data as JSONL to chunk directory
--- @param opts table - {output_dir, chunk_x, chunk_y, tick}
--- @param resource_type string - "resources", "rocks", "trees"
--- @param resource_data table - array of resource records
function Snapshot:emit_resource_jsonl(opts, resource_type, resource_data)
    local base_dir = (opts and opts.output_dir) or "script-output/factoryverse"

    -- Get chunk coordinates from opts
    local chunk_x = (opts and opts.chunk_x) or 0
    local chunk_y = (opts and opts.chunk_y) or 0
    local chunk_dir = string.format("%s/chunks/%d/%d", base_dir, chunk_x, chunk_y)

    -- Create resource subdirectory
    local resource_dir = string.format("%s/%s", chunk_dir, resource_type)
    local file_path = string.format("%s/%s.jsonl", resource_dir, resource_type)

    -- Convert records to JSONL format
    local jsonl_lines = {}
    for _, record in ipairs(resource_data) do
        table.insert(jsonl_lines, helpers.table_to_json(record))
    end
    local jsonl_data = table.concat(jsonl_lines, "\n") .. "\n"

    -- Append to file (create if doesn't exist)
    helpers.write_file(file_path, jsonl_data, true)

    return file_path
end

--- Emit manifest JSON file for chunk summary
--- @param opts table - options {output_dir, chunk_x, chunk_y, tick}
--- @param manifest_data table - manifest data structure
--- @return string - file path written
function Snapshot:emit_manifest_json(opts, manifest_data)
    local base_dir = (opts and opts.output_dir) or "script-output/factoryverse"

    -- Get chunk coordinates from opts
    local chunk_x = (opts and opts.chunk_x) or 0
    local chunk_y = (opts and opts.chunk_y) or 0
    local chunk_dir = string.format("%s/chunks/%d/%d", base_dir, chunk_x, chunk_y)

    -- Create entities subdirectory
    local entities_dir = string.format("%s/entities", chunk_dir)
    local file_path = string.format("%s/manifest.json", entities_dir)

    -- Get tick for metadata
    local tick = (opts and opts.tick) or (game and game.tick) or 0
    manifest_data.tick = tick
    manifest_data.chunk = { x = chunk_x, y = chunk_y }

    -- Atomic write: remove existing file first, then write new one
    if helpers and helpers.remove_path then
        pcall(helpers.remove_path, file_path)
    end

    -- Factorio will create subdirs under script-output if needed
    local json_str = helpers.table_to_json(manifest_data)
    helpers.write_file(file_path, json_str, false)

    return file_path
end

--- Legacy CSV emission method - kept for ResourceSnapshot compatibility
--- @deprecated Use emit_entity_json, emit_status_jsonl, emit_manifest_json instead
--- @param opts table - options {output_dir, chunk_x, chunk_y, tick, metadata}
--- @param name string - base filename (without extension)
--- @param csv_data string - raw CSV data
--- @param metadata table - optional metadata for this CSV file
--- @return string - file path written
function Snapshot:emit_csv(opts, name, csv_data, metadata)
    local base_dir = (opts and opts.output_dir) or "script-output/factoryverse"

    -- Get chunk coordinates from opts
    local chunk_x = (opts and opts.chunk_x) or 0
    local chunk_y = (opts and opts.chunk_y) or 0
    local chunk_dir = string.format("%s/chunks/%d/%d", base_dir, chunk_x, chunk_y)

    -- Get tick for filename
    local tick = (opts and opts.tick) or (game and game.tick or 0)

    -- New filename format: script-output/factoryverse/chunks/<chunkx>/<chunky>/{type}-<tick>.csv
    local csv_path = string.format("%s/%s-%d.csv", chunk_dir, name, tick)
    helpers.write_file(csv_path, csv_data, false)

    -- Write metadata JSON file in new structure: script-output/factoryverse/metadata/{tick}/{snap-category}.json
    local meta_dir = string.format("%s/metadata/%d", base_dir, tick)
    local meta_path = string.format("%s/%s.json", meta_dir, name)
    local meta_data = opts.metadata or {}
    meta_data.tick = tick
    meta_data.surface = self.game_state:get_surface() and self.game_state:get_surface().name or "unknown"
    meta_data.timestamp = tick
    meta_data.files = meta_data.files or {}

    -- Set headers at top level if provided in metadata
    if metadata and metadata.headers then
        meta_data.headers = metadata.headers
    end

    -- Add this CSV file to the metadata (simplified structure)
    table.insert(meta_data.files, {
        path = csv_path,
        lines = (function()
            local count = 0
            for _ in string.gmatch(csv_data, "\n") do count = count + 1 end
            return count
        end)()
    })

    -- Write metadata (overwrite each time to accumulate files)
    local meta_json = helpers.table_to_json(meta_data)
    helpers.write_file(meta_path, meta_json, false)

    return csv_path
end

-- ============================================================================
-- PRIVATE ORCHESTRATION METHODS
-- ============================================================================

--- Process all chunks synchronously
--- @param chunks table - array of chunks
--- @param components table - array of component types
--- @return table - {status, stats}
function Snapshot:_process_all_chunks_sync(chunks, components)
    local stats = { chunks = 0, entities = 0, resources = 0 }

    for _, chunk in ipairs(chunks) do
        local chunk_stats = self:_process_single_chunk(chunk, components)
        stats.chunks = stats.chunks + 1
        stats.entities = stats.entities + (chunk_stats.entities or 0)
        stats.resources = stats.resources + (chunk_stats.resources or 0)
    end

    return { status = "complete", stats = stats }
end

--- Process a single chunk for specified components
--- @param chunk table - {x, y, area}
--- @param components table - array of component types
--- @return table - {entities, resources}
function Snapshot:_process_single_chunk(chunk, components)
    local stats = { entities = 0, resources = 0 }

    for _, component in ipairs(components) do
        if component == "entities" then
            stats.entities = self:_process_entities_for_chunk(chunk)
        elseif component == "resources" then
            stats.resources = self:_process_resources_for_chunk(chunk)
        end
    end

    return stats
end

--- Process entities component for a chunk
--- @param chunk table - {x, y, area}
--- @return number - entities written
function Snapshot:_process_entities_for_chunk(chunk)
    local gathered = EntitiesSnapshot.gather_entities_for_chunk(chunk, {})

    local total_written = 0
    local manifests = { entities = {}, belts = {}, pipes = {}, poles = {} }

    -- Write each component type
    for comp_type, entities in pairs(gathered) do
        for _, entity_data in ipairs(entities) do
            local opts = {
                output_dir = "script-output/factoryverse",
                chunk_x = chunk.x,
                chunk_y = chunk.y,
                tick = game.tick or 0
            }

            self:emit_entity_json(opts, comp_type, entity_data.unit_number, entity_data.name, entity_data)

            -- Track for manifest
            manifests[comp_type].entity_counts = manifests[comp_type].entity_counts or {}
            manifests[comp_type].entity_counts[entity_data.name] =
                (manifests[comp_type].entity_counts[entity_data.name] or 0) + 1
            manifests[comp_type].unit_numbers = manifests[comp_type].unit_numbers or {}
            table.insert(manifests[comp_type].unit_numbers, entity_data.unit_number)

            total_written = total_written + 1
        end
    end

    -- Write separate manifest for each component type
    for comp_type, manifest_data in pairs(manifests) do
        if manifest_data.entity_counts and next(manifest_data.entity_counts) then
            self:_write_component_manifest(chunk.x, chunk.y, comp_type, manifest_data)
        end
    end

    return total_written
end

--- Process resources component for a chunk
--- @param chunk table - {x, y, area}
--- @return number - resources written
function Snapshot:_process_resources_for_chunk(chunk)
    local gathered = ResourceSnapshot.gather_resources_for_chunk(chunk)

    local total_written = 0

    -- Write resources as JSONL
    if #gathered.resources > 0 then
        local opts = {
            output_dir = "script-output/factoryverse",
            chunk_x = chunk.x,
            chunk_y = chunk.y,
            tick = game.tick or 0
        }
        self:emit_resource_jsonl(opts, "resources", gathered.resources)
        total_written = total_written + #gathered.resources
    end

    -- Write rocks as JSONL
    if #gathered.rocks > 0 then
        local opts = {
            output_dir = "script-output/factoryverse",
            chunk_x = chunk.x,
            chunk_y = chunk.y,
            tick = game.tick or 0
        }
        self:emit_resource_jsonl(opts, "rocks", gathered.rocks)
        total_written = total_written + #gathered.rocks
    end

    -- Write trees as JSONL
    if #gathered.trees > 0 then
        local opts = {
            output_dir = "script-output/factoryverse",
            chunk_x = chunk.x,
            chunk_y = chunk.y,
            tick = game.tick or 0
        }
        self:emit_resource_jsonl(opts, "trees", gathered.trees)
        total_written = total_written + #gathered.trees
    end

    return total_written
end

--- Create async snapshot session
--- @param chunks table - array of chunks
--- @param components table - array of component types
--- @param chunks_per_tick number - chunks to process per tick
--- @return table - {status, session_id, total_chunks}
function Snapshot:_create_snapshot_session(chunks, components, chunks_per_tick)
    if not storage.snapshot_sessions then
        storage.snapshot_sessions = {}
    end

    local session_id = "map_" .. (game.tick or 0)
    storage.snapshot_sessions[session_id] = {
        started_tick = game.tick or 0,
        chunks = chunks,
        current_index = 0,
        chunks_per_tick = chunks_per_tick,
        components = components,
        in_progress = true,
        stats = { chunks_done = 0, entities = 0, resources = 0 }
    }

    -- Register tick handler if not already active
    if not storage._snapshot_tick_handler_registered then
        script.on_nth_tick(1, function(event)
            Snapshot:_process_snapshot_sessions()
        end)
        storage._snapshot_tick_handler_registered = true
    end

    return { status = "queued", session_id = session_id, total_chunks = #chunks }
end

--- Process active snapshot sessions (called every tick)
function Snapshot:_process_snapshot_sessions()
    if not storage.snapshot_sessions then return end

    for session_id, session in pairs(storage.snapshot_sessions) do
        if session.in_progress then
            local chunks_this_tick = math.min(
                session.chunks_per_tick,
                #session.chunks - session.current_index
            )

            for i = 1, chunks_this_tick do
                local chunk_idx = session.current_index + i
                local chunk = session.chunks[chunk_idx]

                if chunk then
                    local chunk_stats = self:_process_single_chunk(chunk, session.components)
                    session.stats.chunks_done = session.stats.chunks_done + 1
                    session.stats.entities = session.stats.entities + (chunk_stats.entities or 0)
                    session.stats.resources = session.stats.resources + (chunk_stats.resources or 0)
                end
            end

            session.current_index = session.current_index + chunks_this_tick

            -- Check completion
            if session.current_index >= #session.chunks then
                session.in_progress = false
                local elapsed = (game.tick or 0) - session.started_tick
                log(string.format("Snapshot session %s completed: %d chunks, %d entities, %d resources in %d ticks",
                    session_id, session.stats.chunks_done, session.stats.entities, session.stats.resources, elapsed))
            end
        end
    end
end

--- Get chunks an entity belongs to (for multi-chunk entities)
--- @param entity LuaEntity - the entity
--- @return table - array of {x, y} chunk coordinates
function Snapshot:_get_entity_chunks(entity)
    local chunks = {}
    local position = entity.position
    if not position then return chunks end

    local center_chunk_x = math.floor(position.x / 32)
    local center_chunk_y = math.floor(position.y / 32)
    table.insert(chunks, { x = center_chunk_x, y = center_chunk_y })

    local bb = entity.bounding_box
    if bb and bb.left_top and bb.right_bottom then
        local min_cx = math.floor(bb.left_top.x / 32)
        local min_cy = math.floor(bb.left_top.y / 32)
        local max_cx = math.floor(bb.right_bottom.x / 32)
        local max_cy = math.floor(bb.right_bottom.y / 32)

        for cx = min_cx, max_cx do
            for cy = min_cy, max_cy do
                if not (cx == center_chunk_x and cy == center_chunk_y) then
                    table.insert(chunks, { x = cx, y = cy })
                end
            end
        end
    end

    return chunks
end

--- Write manifest for a specific component in a chunk
--- @param chunk_x number - chunk x coordinate
--- @param chunk_y number - chunk y coordinate
--- @param component_type string - component type
--- @param manifest_data table - manifest data
--- @return string - file path written
function Snapshot:_write_component_manifest(chunk_x, chunk_y, component_type, manifest_data)
    local base_dir = "script-output/factoryverse"
    local component_dir = string.format("%s/chunks/%d/%d/%s", base_dir, chunk_x, chunk_y, component_type)
    local file_path = string.format("%s/manifest.json", component_dir)

    manifest_data.tick = game.tick or 0
    manifest_data.chunk = { x = chunk_x, y = chunk_y }
    manifest_data.component = component_type

    if helpers and helpers.remove_path then
        pcall(helpers.remove_path, file_path)
    end

    local json_str = helpers.table_to_json(manifest_data)
    helpers.write_file(file_path, json_str, false)

    return file_path
end

--- Update component manifest by rescanning chunk (for action post-hooks)
--- @param chunk_x number - chunk x coordinate
--- @param chunk_y number - chunk y coordinate
--- @param component_type string - component type
function Snapshot:_update_component_manifest(chunk_x, chunk_y, component_type)
    local chunk = {
        x = chunk_x,
        y = chunk_y,
        area = {
            left_top = { x = chunk_x * 32, y = chunk_y * 32 },
            right_bottom = { x = (chunk_x + 1) * 32, y = (chunk_y + 1) * 32 }
        }
    }

    local gathered = EntitiesSnapshot.gather_entities_for_chunk(chunk, { component_filter = component_type })
    local entities = gathered[component_type] or {}

    local manifest_data = {
        entity_counts = {},
        unit_numbers = {}
    }

    for _, entity_data in ipairs(entities) do
        manifest_data.entity_counts[entity_data.name] =
            (manifest_data.entity_counts[entity_data.name] or 0) + 1
        table.insert(manifest_data.unit_numbers, entity_data.unit_number)
    end

    self:_write_component_manifest(chunk_x, chunk_y, component_type, manifest_data)
end

return Snapshot
