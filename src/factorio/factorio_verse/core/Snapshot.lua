local GameState = require "core.game_state.GameState":new()

--- Base class for all snapshots with shared functionality
--- Provides common interface for snapshot operations and output formatting
--- @class Snapshot
--- @field game_state GameState
local Snapshot = {}
Snapshot.__index = Snapshot

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
	-- Prefer explicit snapshot_id if provided
	local snapshot_id = (opts and opts.snapshot_id)
	if not snapshot_id then
		-- Try meta.snapshot_id, otherwise derive a stable id from tick
		local tick = (payload and payload.meta and payload.meta.tick) or (game and game.tick) or 0
		snapshot_id = "snap-" .. tostring(tick)
	end

	-- Example filename: script-output/factoryverse/entities.snap-12345.json
	local file_path = string.format("%s/%s.%s.json", base_dir, name, snapshot_id)

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

return Snapshot