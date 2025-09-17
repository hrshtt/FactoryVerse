local GameState = require "core.game_state.GameState":new()

--- Component Schema Definition - Single source of truth for all component types
local ComponentSchema = {
    -- Base entity component
    entity = {
        fields = {
            unit_number = "number",
            name = "string",
            type = "string",
            force = "string",
            position_x = "number",
            position_y = "number",
            direction = "number",
            direction_name = "string",
            orientation = "number",
            orientation_name = "string",
            chunk_x = "number",
            chunk_y = "number",
            health = "number",
            status = "number",
            status_name = "string",
            bounding_box_min_x = "number",
            bounding_box_min_y = "number",
            bounding_box_max_x = "number",
            bounding_box_max_y = "number",
            electric_network_id = "number",
            electric_buffer_size = "number",
            energy = "number",
            tile_width = "number",
            tile_height = "number"
        },
        flatten_rules = {
            position = { x = "position_x", y = "position_y" },
            chunk = { x = "chunk_x", y = "chunk_y" },
            bounding_box = {
                min_x = "bounding_box_min_x",
                min_y = "bounding_box_min_y",
                max_x = "bounding_box_max_x",
                max_y = "bounding_box_max_y"
            }
        }
    },


    -- Crafting component
    crafting = {
        fields = {
            unit_number = "number",
            recipe = "string",
            crafting_progress = "number",
            chunk_x = "number",
            chunk_y = "number"
        },
        flatten_rules = {
            chunk = { x = "chunk_x", y = "chunk_y" }
        }
    },

    -- Burner component
    burner = {
        fields = {
            unit_number = "number",
            remaining_burning_fuel = "number",
            currently_burning = "string",
            chunk_x = "number",
            chunk_y = "number"
        },
        flatten_rules = {
            chunk = { x = "chunk_x", y = "chunk_y" },
            burner = {
                remaining_burning_fuel = "remaining_burning_fuel",
                currently_burning = "currently_burning",
            }
        }
    },

    -- Inventory component
    inventory = {
        fields = {
            unit_number = "number",
            inventories_json = "json", -- Complex nested data
            chunk_x = "number",
            chunk_y = "number"
        },
        flatten_rules = {
            chunk = { x = "chunk_x", y = "chunk_y" },
            inventories = "inventories_json" -- Map to _json suffixed field
        }
    },

    -- Pipe component
    pipe = {
        fields = {
            unit_number = "number",
            name = "string",
            type = "string",
            position_x = "number",
            position_y = "number",
            direction = "number",
            direction_name = "string",
            fluid_contents_json = "json",      -- Complex nested data
            pipe_neighbours_json = "json",     -- Input/output connections like belts
            pipe_to_ground_type = "string",
            underground_neighbour_unit = "number",
            chunk_x = "number",
            chunk_y = "number"
        },
        flatten_rules = {
            position = { x = "position_x", y = "position_y" },
            chunk = { x = "chunk_x", y = "chunk_y" },
            fluid_contents = "fluid_contents_json",          -- Map to _json suffixed field
            pipe_neighbours = "pipe_neighbours_json"         -- Map to _json suffixed field
        }
    },

    -- Inserter component
    inserter = {
        fields = {
            unit_number = "number",
            pickup_position_x = "number",
            pickup_position_y = "number",
            drop_position_x = "number",
            drop_position_y = "number",
            pickup_target_unit = "number",
            drop_target_unit = "number",
            chunk_x = "number",
            chunk_y = "number"
        },
        flatten_rules = {
            chunk = { x = "chunk_x", y = "chunk_y" },
            pickup_position = { x = "pickup_position_x", y = "pickup_position_y" },
            drop_position = { x = "drop_position_x", y = "drop_position_y" }
        }
    },

    -- Belt component
    belt = {
        fields = {
            unit_number = "number",
            name = "string",
            type = "string",
            position_x = "number",
            position_y = "number",
            direction = "number",
            direction_name = "string",
            item_lines_json = "json",      -- Complex nested data
            belt_neighbours_json = "json", -- Complex nested data
            belt_to_ground_type = "string",
            underground_neighbour_unit = "number",
            chunk_x = "number",
            chunk_y = "number"
        },
        flatten_rules = {
            position = { x = "position_x", y = "position_y" },
            chunk = { x = "chunk_x", y = "chunk_y" },
            item_lines = "item_lines_json",          -- Map to _json suffixed field
            belt_neighbours = "belt_neighbours_json" -- Map to _json suffixed field
        }
    },

    -- Resources component (for ResourceSnapshot)
    resources = {
        fields = {
            kind = "string",
            x = "number",
            y = "number",
            amount = "number"
        },
        flatten_rules = {}
    },

    -- Rocks component (for ResourceSnapshot)
    rocks = {
        fields = {
            name = "string",
            type = "string",
            position_x = "number",
            position_y = "number",
            size = "number",
            resource_json = "json",
            chunk_x = "number",
            chunk_y = "number"
        },
        flatten_rules = {
            position = { x = "position_x", y = "position_y" },
            chunk = { x = "chunk_x", y = "chunk_y" },
            resources = "resource_json" -- Map to _json suffixed field
        }
    },

    -- Trees component (for ResourceSnapshot)
    trees = {
        fields = {
            name = "string",
            position_x = "number",
            position_y = "number",
            bounding_box_min_x = "number",
            bounding_box_min_y = "number",
            bounding_box_max_x = "number",
            bounding_box_max_y = "number"
        },
        flatten_rules = {
            position = { x = "position_x", y = "position_y" },
            bounding_box = {
                min_x = "bounding_box_min_x",
                min_y = "bounding_box_min_y",
                max_x = "bounding_box_max_x",
                max_y = "bounding_box_max_y"
            }
        }
    }
}

--- Schema Manager - Centralized schema management for all components
--- @class SchemaManager
local SchemaManager = {}

--- Get headers for a component type
--- @param component_type string - component type name
--- @return table - array of header names
function SchemaManager:get_headers(component_type)
    local schema = ComponentSchema[component_type]
    if not schema then
        error("Unknown component type: " .. tostring(component_type))
    end

    local headers = {}
    for field_name, _ in pairs(schema.fields) do
        table.insert(headers, field_name)
    end

    -- Sort for consistent ordering
    table.sort(headers)
    return headers
end

--- Flatten data according to component schema rules
--- @param component_type string - component type name
--- @param data table - data to flatten
--- @return table - flattened data
function SchemaManager:flatten_data(component_type, data)
    local schema = ComponentSchema[component_type]
    if not schema then
        error("Unknown component type: " .. tostring(component_type))
    end

    local flattened = {}
    local rules = schema.flatten_rules or {}

    for k, v in pairs(data) do
        if rules[k] then
            if type(rules[k]) == "string" then
                -- Simple field mapping (e.g., inventories -> inventories_json)
                flattened[rules[k]] = v
            elseif type(rules[k]) == "table" then
                -- Apply flattening rules for nested structures
                for nested_key, flattened_key in pairs(rules[k]) do
                    if type(nested_key) == "string" and type(flattened_key) == "string" then
                        -- Simple field mapping
                        if v[nested_key] ~= nil then
                            flattened[flattened_key] = v[nested_key]
                        end
                    elseif type(nested_key) == "table" and type(flattened_key) == "string" then
                        -- Nested structure flattening (like position -> position_x, position_y)
                        for sub_key, sub_flattened_key in pairs(nested_key) do
                            if v[sub_key] ~= nil then
                                flattened[sub_flattened_key] = v[sub_key]
                            end
                        end
                    end
                end
            end
        else
            -- Direct field copy
            flattened[k] = v
        end
    end

    return flattened
end

--- Validate data against component schema
--- @param component_type string - component type name
--- @param data table - data to validate
--- @return boolean, string|nil - is_valid, error_message
function SchemaManager:validate_data(component_type, data)
    local schema = ComponentSchema[component_type]
    if not schema then
        return false, "Unknown component type: " .. tostring(component_type)
    end

    local flattened = self:flatten_data(component_type, data)
    local expected_fields = schema.fields

    for field_name, field_type in pairs(expected_fields) do
        if flattened[field_name] == nil then
            -- Field is missing - this might be okay for optional fields
            -- Could add optional field tracking in schema
        else
            local actual_type = type(flattened[field_name])
            if field_type == "json" and actual_type == "table" then
                -- JSON fields are stored as tables, converted during CSV generation
                -- This is fine
            elseif actual_type ~= field_type then
                return false, string.format("Field %s expected type %s, got %s",
                    field_name, field_type, actual_type)
            end
        end
    end

    return true, nil
end

--- Get SQL schema for a component type
--- @param component_type string - component type name
--- @return string - SQL CREATE TABLE statement
function SchemaManager:get_sql_schema(component_type)
    local schema = ComponentSchema[component_type]
    if not schema then
        error("Unknown component type: " .. tostring(component_type))
    end

    local sql_fields = {}
    for field_name, field_type in pairs(schema.fields) do
        local sql_type = self:_lua_type_to_sql_type(field_type)
        table.insert(sql_fields, string.format("    %s %s", field_name, sql_type))
    end

    return string.format("CREATE TABLE %s (\n%s\n);", component_type, table.concat(sql_fields, ",\n"))
end

--- Convert Lua type to SQL type
--- @param lua_type string - Lua type name
--- @return string - SQL type name
function SchemaManager:_lua_type_to_sql_type(lua_type)
    local type_map = {
        number = "NUMERIC",
        string = "TEXT",
        json = "JSONB"
    }
    return type_map[lua_type] or "TEXT"
end

--- Base class for all snapshots with shared functionality
--- Provides common interface for snapshot operations and output formatting
--- @class Snapshot
--- @field game_state GameState
--- @field schema_manager SchemaManager
local Snapshot = {}
Snapshot.__index = Snapshot

--- @return Snapshot
function Snapshot:new()
    local instance = {}
    setmetatable(instance, self)
    instance.game_state = GameState
    instance.schema_manager = SchemaManager
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

--- Get headers for a component type using schema manager
--- @param component_type string - component type name
--- @return table - array of header names
function Snapshot:get_headers(component_type)
    return self.schema_manager:get_headers(component_type)
end

--- Flatten data using schema manager
--- @param component_type string - component type name
--- @param data table - data to flatten
--- @return table - flattened data
function Snapshot:flatten_data(component_type, data)
    return self.schema_manager:flatten_data(component_type, data)
end

--- Validate data using schema manager
--- @param component_type string - component type name
--- @param data table - data to validate
--- @return boolean, string|nil - is_valid, error_message
function Snapshot:validate_data(component_type, data)
    return self.schema_manager:validate_data(component_type, data)
end

--- Get SQL schema for a component type
--- @param component_type string - component type name
--- @return string - SQL CREATE TABLE statement
function Snapshot:get_sql_schema(component_type)
    return self.schema_manager:get_sql_schema(component_type)
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

return Snapshot
