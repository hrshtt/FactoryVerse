local Snapshot = require "core.Snapshot"
local utils = require "utils"

--- ResourceSnapshot: High-performance tile streaming to Postgres
---
--- DESIGN DECISIONS:
--- 1. Stream raw tiles in CSV format for maximum throughput
--- 2. Chunked buffering by surface/chunk/kind for efficient batching
--- 3. Dual output: files (reliable) and UDP (low-latency)
--- 4. Compression for large batches to reduce I/O overhead
--- 5. Time and size-based flush triggers for balanced performance
---
--- OUTPUT: Raw tile data streamed to files or UDP for Postgres ingestion
--- @class ResourceSnapshot : Snapshot
local ResourceSnapshot = Snapshot:new()
ResourceSnapshot.__index = ResourceSnapshot

-- Configuration constants
local MAX_LINES = 2000 -- ~100 KB CSV per flush
local UDP_PORT = 27600 -- UDP collector port
local USE_UDP = false  -- Toggle between UDP and file output

-- Global buffers: keyed by "surface:cx:cy:kind" -> buffer table
local BUFS = {}

---@return ResourceSnapshot
function ResourceSnapshot:new()
    local instance = Snapshot:new()
    setmetatable(instance, self)
    ---@cast instance ResourceSnapshot
    return instance
end

function ResourceSnapshot:take()
    log("Taking resource snapshot - streaming all resources including crude oil and rocks")

    local charted_chunks = self.game_state:get_charted_chunks()
    local tile_count = self:_stream_all_tiles_from_chunks(charted_chunks)

    -- Flush all remaining buffers immediately
    self:_flush_all()

    local output = self:create_output("snapshot.resources", "v1", {
        tile_count = tile_count,
        buffer_count = 0, -- All flushed now
        flush_mode = USE_UDP and "udp" or "file"
    })

    self:print_summary(output, function(out)
        return {
            surface = out.surface,
            resources_streamed = out.data.tile_count,
            buffers_active = out.data.buffer_count,
            mode = out.data.flush_mode,
            tick = out.timestamp
        }
    end)

    return output
end


--- TILE STREAMING FUNCTIONS

--- Stream all tiles (resources + water) from all charted chunks
--- @param chunks table - list of charted chunks
--- @return number - total tiles streamed
function ResourceSnapshot:_stream_all_tiles_from_chunks(chunks)
    local total_tiles = 0

    for _, chunk in ipairs(chunks) do
        local chunk_tiles = 0

        -- Process resources in this chunk (including crude oil)
        local resources_in_chunk = self.game_state:get_resources_in_chunks({ chunk })
        if resources_in_chunk then
            for resource_name, entities in pairs(resources_in_chunk) do
                for _, entity in ipairs(entities) do
                    local x = utils.floor(entity.position.x)
                    local y = utils.floor(entity.position.y)
                    local amount = entity.amount or 0
                    self:_enqueue_tile_for_chunk(chunk.x, chunk.y, x, y, resource_name, amount)
                    chunk_tiles = chunk_tiles + 1
                end
            end
        end

        -- Process water tiles in this chunk
        local water_data = self.game_state:get_water_tiles_in_chunks({ chunk })
        if water_data and water_data.tiles then
            for _, tile in ipairs(water_data.tiles) do
                local x, y = utils.extract_position(tile)
                if x and y then
                    self:_enqueue_tile_for_chunk(chunk.x, chunk.y, x, y, "water", 0) -- Water has no yield
                    chunk_tiles = chunk_tiles + 1
                end
            end
        end

        -- Process rock entities in this chunk
        local surface = self.game_state:get_surface()
        if surface then
            local rock_entities = surface.find_entities_filtered({
                area = chunk.area,
                type = "simple-entity"
            })
            for _, entity in ipairs(rock_entities) do
                local name = entity.name
                if name and (name:match("rock") or name:match("stone")) and entity.valid then
                    -- Determine rock size from name
                    local size = 1
                    if name:match("huge") then
                        size = 3
                    elseif name:match("big") then
                        size = 2
                    end
                    
                    -- Get mining results as JSON string
                    local resources = {}
                    if entity.prototype and entity.prototype.mineable_properties and entity.prototype.mineable_properties.products then
                        for _, product in pairs(entity.prototype.mineable_properties.products) do
                            local resource_info = {
                                name = product.name,
                                amount = product.amount or product.amount_min or 1,
                                probability = product.probability or 1
                            }
                            if product.amount_max and product.amount_max ~= resource_info.amount then
                                resource_info.amount_max = product.amount_max
                            end
                            table.insert(resources, resource_info)
                        end
                    end
                    
                    -- Create rock data
                    local rock_data = {
                        name = name,
                        type = entity.type,
                        position = entity.position,
                        size = size,
                        resources = resources,
                        chunk = { x = chunk.x, y = chunk.y }
                    }
                    
                    -- Use existing buffer system but with "rocks" schema
                    local flattened = self:flatten_data("rocks", rock_data)
                    local headers = self:get_headers("rocks")
                    local csv_row = self:_table_to_csv_row(flattened, headers)
                    
                    -- Add to buffer with special key for rocks
                    local k = "rocks_" .. chunk.x .. "_" .. chunk.y
                    local b = BUFS[k]
                    if not b then
                        b = { rows = {}, count = 0, chunk_x = chunk.x, chunk_y = chunk.y, surface = 1, type = "rocks" }
                        BUFS[k] = b
                    end
                    b.count = b.count + 1
                    b.rows[b.count] = csv_row .. "\n"
                    
                    chunk_tiles = chunk_tiles + 1
                end
            end
        end

        -- Flush this chunk's buffer immediately
        self:_flush_chunk_buffer(chunk.x, chunk.y)
        self:_flush_rocks_buffer(chunk.x, chunk.y)

        total_tiles = total_tiles + chunk_tiles
    end

    return total_tiles
end


--- Enqueue a tile for a specific chunk
--- @param chunk_x number - chunk x coordinate
--- @param chunk_y number - chunk y coordinate
--- @param x number - tile x coordinate
--- @param y number - tile y coordinate
--- @param kind string - tile kind (resource name, water, etc.)
--- @param amount number - resource yield amount (0 for water)
function ResourceSnapshot:_enqueue_tile_for_chunk(chunk_x, chunk_y, x, y, kind, amount)
    local k = self:_chunk_buffer_key(chunk_x, chunk_y)
    local b = BUFS[k]

    if not b then
        b = {
            rows = {},
            count = 0,
            chunk_x = chunk_x,
            chunk_y = chunk_y,
            surface = 1
        }
        BUFS[k] = b
    end

    -- Create tile data according to schema
    local tile_data = {
        kind = kind,
        x = x,
        y = y,
        amount = amount
    }

    -- Flatten using schema manager
    local flattened = self:flatten_data("resources", tile_data)

    -- Convert to CSV row
    local headers = self:get_headers("resources")
    local csv_row = self:_table_to_csv_row(flattened, headers)

    b.count = b.count + 1
    b.rows[b.count] = csv_row .. "\n"
end

--- Generate buffer key for chunk-based buffering
--- @param chunk_x number - chunk x coordinate
--- @param chunk_y number - chunk y coordinate
--- @return string - buffer key
function ResourceSnapshot:_chunk_buffer_key(chunk_x, chunk_y)
    return "chunk_" .. chunk_x .. "_" .. chunk_y
end

--- Flush a specific chunk's buffer
--- @param chunk_x number - chunk x coordinate
--- @param chunk_y number - chunk y coordinate
function ResourceSnapshot:_flush_chunk_buffer(chunk_x, chunk_y)
    local k = self:_chunk_buffer_key(chunk_x, chunk_y)
    local b = BUFS[k]
    if not b or b.count == 0 then return end

    -- Get headers and create proper CSV with header row
    local headers = self:get_headers("resources")
    local header_row = table.concat(headers, ",") .. "\n"
    local payload = header_row .. table.concat(b.rows, "", 1, b.count)

    if USE_UDP then
        -- Split into safe datagrams (~8KB)
        local chunk_size = 8192
        for i = 1, #payload, chunk_size do
            helpers.send_udp(UDP_PORT, string.sub(payload, i, i + chunk_size - 1))
        end
    else
        -- Use emit_csv for direct CSV file writing - one file per chunk
        local metadata = {
            chunk_x = chunk_x,
            chunk_y = chunk_y,
            surface_id = b.surface,
            line_count = b.count,
            headers = headers
        }

        self:emit_csv({
            output_dir = "script-output/factoryverse",
            chunk_x = chunk_x,
            chunk_y = chunk_y,
            tick = game and game.tick or 0,
            metadata = { schema_version = "resources.raw.v1" }
        }, "resources", payload, metadata)
    end

    -- Clear this chunk's buffer
    BUFS[k] = nil
end

--- Flush a single buffer (legacy method for compatibility)
--- @param k string - buffer key
function ResourceSnapshot:_flush_one(k)
    local b = BUFS[k]
    if not b or b.count == 0 then return end

    local payload = table.concat(b.rows, "", 1, b.count)

    if USE_UDP then
        -- Split into safe datagrams (~8KB)
        local chunk_size = 8192
        for i = 1, #payload, chunk_size do
            helpers.send_udp(UDP_PORT, string.sub(payload, i, i + chunk_size - 1))
        end
    else
        -- Use emit_csv for direct CSV file writing
        local metadata = {
            chunk_x = b.cx,
            chunk_y = b.cy,
            kind = b.kind,
            surface_id = b.surface,
            line_count = b.count
        }

        self:emit_csv({
            output_dir = "script-output/factoryverse",
            chunk_x = b.cx,
            chunk_y = b.cy,
            tick = game and game.tick or 0,
            metadata = { schema_version = "resources.raw.v1" }
        }, "resources", payload, metadata)
    end

    -- Reset buffer
    BUFS[k] = {
        rows = {},
        count = 0,
        cx = b.cx,
        cy = b.cy,
        kind = b.kind,
        surface = b.surface
    }
end

--- Flush a specific rock chunk's buffer
--- @param chunk_x number - chunk x coordinate
--- @param chunk_y number - chunk y coordinate
function ResourceSnapshot:_flush_rocks_buffer(chunk_x, chunk_y)
    local k = "rocks_" .. chunk_x .. "_" .. chunk_y
    local b = BUFS[k]
    if not b or b.count == 0 then return end

    -- Get headers and create proper CSV with header row
    local headers = self:get_headers("rocks")
    local header_row = table.concat(headers, ",") .. "\n"
    local payload = header_row .. table.concat(b.rows, "", 1, b.count)

    if USE_UDP then
        -- Split into safe datagrams (~8KB)
        local chunk_size = 8192
        for i = 1, #payload, chunk_size do
            helpers.send_udp(UDP_PORT, string.sub(payload, i, i + chunk_size - 1))
        end
    else
        -- Use emit_csv for direct CSV file writing
        self:emit_csv({
            output_dir = "script-output/factoryverse",
            chunk_x = chunk_x,
            chunk_y = chunk_y,
            tick = game and game.tick or 0,
            metadata = { schema_version = "rocks.raw.v1" }
        }, "rocks", payload, { headers = headers })
    end

    -- Clear this chunk's buffer
    BUFS[k] = nil
end

--- Flush all buffers (time-based trigger)
function ResourceSnapshot:_flush_all()
    for k, _ in pairs(BUFS) do
        self:_flush_one(k)
    end
end

--- Get count of active buffers
--- @return number - number of active buffers
function ResourceSnapshot:_get_buffer_count()
    local count = 0
    for _, b in pairs(BUFS) do
        if b.count > 0 then count = count + 1 end
    end
    return count
end

--- Convert table to CSV row, handling nested structures
--- @param data table - data to convert
--- @param headers table - column headers
--- @return string - CSV row
function ResourceSnapshot:_table_to_csv_row(data, headers)
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


--- CONFIGURATION HELPERS

--- Set output mode (UDP or file)
--- @param use_udp boolean - true for UDP, false for file output
function ResourceSnapshot:set_output_mode(use_udp)
    USE_UDP = use_udp
end

--- Set flush parameters
--- @param max_lines number - max lines per buffer before flush
function ResourceSnapshot:set_flush_params(max_lines)
    MAX_LINES = max_lines
end

--- VISUALIZATION/DEBUG

function ResourceSnapshot:render(output)
    -- Simple visualization for streaming mode
    local surface = game.surfaces[1]
    if rendering then rendering.clear() end

    -- Show buffer status
    local buffer_count = self:_get_buffer_count()
    if buffer_count > 0 then
        rendering.draw_text {
            surface = surface,
            target = { 0, 0 },
            text = {
                "Tile Streaming Active",
                "\nBuffers: " .. tostring(buffer_count),
                "\nMode: " .. (USE_UDP and "UDP" or "File")
            },
            color = { 1, 1, 1, 1 },
            scale_with_zoom = true
        }
    end
end

return ResourceSnapshot
