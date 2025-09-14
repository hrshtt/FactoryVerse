local GameState = require "core.game_state.GameState":new()

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
    rcon.print(json_str)
    log(json_str)
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
	log("Wrote snapshot to " .. file_path)
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
	
	log("Wrote CSV to " .. csv_path)
	return csv_path
end

--- Convert table to CSV row, handling nested structures
--- @param data table - data to convert
--- @param headers table - column headers
--- @return string - CSV row
function Snapshot:_table_to_csv_row(data, headers)
    local values = {}
    for _, header in ipairs(headers) do
        local value = data[header]
        if value == nil then
            table.insert(values, "")
        elseif type(value) == "table" then
            -- Convert table to JSON string for complex nested data
            local json_str = helpers.table_to_json(value)
            table.insert(values, '"' .. json_str:gsub('"', '""') .. '"')
        elseif type(value) == "string" then
            -- Regular string, escape quotes and wrap in quotes
            table.insert(values, '"' .. value:gsub('"', '""') .. '"')
        else
            table.insert(values, tostring(value))
        end
    end
    return table.concat(values, ",")
end

--- Convert array of tables to CSV
--- @param data table - array of data tables
--- @param headers table - column headers
--- @return string - CSV content
function Snapshot:array_to_csv(data, headers)
    if #data == 0 then
        return table.concat(headers, ",") .. "\n"
    end

    local csv_lines = { table.concat(headers, ",") }
    for _, row in ipairs(data) do
        table.insert(csv_lines, self:_table_to_csv_row(row, headers))
    end
    return table.concat(csv_lines, "\n") .. "\n"
end

--- Generic method to emit CSV files grouped by chunks
--- @param data table - array of data to group by chunks
--- @param file_prefix string - base filename prefix
--- @param headers table - CSV column headers
--- @param schema_version string - schema version for metadata
--- @param flatten_fn function - optional function to flatten each row before CSV conversion
function Snapshot:emit_csv_by_chunks(data, file_prefix, headers, schema_version, flatten_fn)
    -- Group by chunk
    local data_by_chunk = {}
    for _, row in ipairs(data) do
        local chunk_key = string.format("%d_%d", row.chunk.x, row.chunk.y)
        if not data_by_chunk[chunk_key] then
            data_by_chunk[chunk_key] = { chunk_x = row.chunk.x, chunk_y = row.chunk.y, rows = {} }
        end
        table.insert(data_by_chunk[chunk_key].rows, row)
    end

    -- Emit CSV for each chunk
    for chunk_key, chunk_data in pairs(data_by_chunk) do
        local flattened_rows = {}
        for _, row in ipairs(chunk_data.rows) do
            table.insert(flattened_rows, flatten_fn and flatten_fn(row) or row)
        end

        local metadata = { schema_version = schema_version }
        local opts = {
            output_dir = "script-output/factoryverse",
            chunk_x = chunk_data.chunk_x,
            chunk_y = chunk_data.chunk_y,
            tick = game and game.tick or 0,
            metadata = metadata
        }

        self:emit_csv(opts, file_prefix, self:array_to_csv(flattened_rows, headers), { headers = headers })
    end
end

--- Process all charted chunks with a custom processor function
--- @param processor_fn function - function to process each chunk, should return data or nil
--- @return table - array of results from processor function
function Snapshot:process_charted_chunks(processor_fn)
    local charted_chunks = self.game_state:get_charted_chunks()
    local results = {}
    
    for _, chunk in ipairs(charted_chunks) do
        local chunk_result = processor_fn(chunk)
        if chunk_result then
            table.insert(results, chunk_result)
        end
    end
    
    return results
end

--- Create chunked output structure
--- @param snapshot_type string - type identifier (e.g. "resources", "entities")
--- @param version string - schema version
--- @param data_by_chunk table - data organized by chunks
--- @return table - standardized chunked output structure
function Snapshot:create_chunked_output(snapshot_type, version, data_by_chunk)
    local surface = self.game_state:get_surface()
    return {
        schema_version = snapshot_type .. "." .. version,
        surface = surface and surface.name or "unknown",
        timestamp = game and game.tick or 0,
        chunks_processed = #data_by_chunk,
        data = data_by_chunk
    }
end

--- Create a chunk buffer for streaming data
--- @param chunk_x number - chunk x coordinate
--- @param chunk_y number - chunk y coordinate
--- @param surface_id number - surface ID (default 1)
--- @return table - buffer structure
function Snapshot:create_chunk_buffer(chunk_x, chunk_y, surface_id)
    return {
        rows = {},
        count = 0,
        chunk_x = chunk_x,
        chunk_y = chunk_y,
        surface = surface_id or 1
    }
end

--- Flush a chunk buffer to CSV file
--- @param buffer table - buffer to flush
--- @param file_prefix string - base filename prefix
--- @param schema_version string - schema version for metadata
--- @param metadata table - optional additional metadata (can include headers)
function Snapshot:flush_chunk_buffer(buffer, file_prefix, schema_version, metadata)
    if not buffer or buffer.count == 0 then return end
    
    local payload = table.concat(buffer.rows, "", 1, buffer.count)
    local opts = {
        output_dir = "script-output/factoryverse",
        chunk_x = buffer.chunk_x,
        chunk_y = buffer.chunk_y,
        tick = game and game.tick or 0,
        metadata = { schema_version = schema_version }
    }
    
    self:emit_csv(opts, file_prefix, payload, metadata)
end

return Snapshot