local GameState = require "core.game_state.GameState":new()
local utils = require "utils"

--- Base class for all snapshots with shared functionality
--- Provides common interface for snapshot operations and output formatting
--- @class Snapshot
--- @field game_state GameState
local Snapshot = {}
Snapshot.__index = Snapshot

--- @return Snapshot
function Snapshot:new()
    local instance = {}
    setmetatable(instance, self)
    instance.game_state = GameState
    return instance
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

--- Base take method - override in subclasses
function Snapshot:take()
    error("take() method must be implemented by subclass")
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

--- Emit CSV data with metadata tracking
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

return Snapshot
