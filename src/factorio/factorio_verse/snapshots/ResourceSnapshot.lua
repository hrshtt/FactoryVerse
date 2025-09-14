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
local MAX_LINES = 2000          -- ~100 KB CSV per flush
local UDP_PORT = 27600          -- UDP collector port
local USE_UDP = false           -- Toggle between UDP and file output

-- CSV headers for different data types
local RESOURCE_TILES_HEADERS = { "kind", "x", "y", "amount" }
local RESOURCE_ROCKS_HEADERS = { "name", "x", "y", "size_hint" }

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
    log("Taking resource snapshot - streaming all tiles")

    local tile_count = self:process_charted_chunks(function(chunk)
        return self:_stream_tiles_from_chunk(chunk)
    end)
    
    -- Sum up tile counts from all chunks
    local total_tiles = 0
    local chunks_processed = 0
    for _, count in ipairs(tile_count) do
        total_tiles = total_tiles + count
        chunks_processed = chunks_processed + 1
    end
    
    -- Flush all remaining buffers immediately
    self:_flush_all()
    
    local output = self:create_output("snapshot.tiles", "v1", {
        tile_count = total_tiles,
        chunks_processed = chunks_processed,
        buffer_count = 0, -- All flushed now
        flush_mode = USE_UDP and "udp" or "file"
	})

    self:print_summary(output, function(out)
        return { 
            surface = out.surface, 
            tiles_streamed = out.data.tile_count,
            chunks_processed = out.data.chunks_processed,
            buffers_active = out.data.buffer_count,
            mode = out.data.flush_mode,
            tick = out.timestamp 
        }
    end)

    return output
end

--- Stream tiles from a single chunk
--- @param chunk table - chunk with x, y coordinates
--- @return number - tiles streamed from this chunk
function ResourceSnapshot:_stream_tiles_from_chunk(chunk)
    local chunk_tiles = 0
    
    -- Process resources in this chunk
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
    
    -- Process rocks in this chunk
    self:_stream_rocks_from_chunk(chunk)
    
    -- Flush this chunk's buffer immediately
    self:_flush_chunk_buffer(chunk.x, chunk.y)
    
    return chunk_tiles
end

--- Stream rocks from a specific chunk
--- @param chunk table - chunk with x, y coordinates
function ResourceSnapshot:_stream_rocks_from_chunk(chunk)
    local surface = game.surfaces[1] -- Assuming surface 1, could be made configurable
    
    -- Calculate chunk boundaries (32x32 tiles per chunk)
    local x0 = chunk.x * 32
    local y0 = chunk.y * 32
    local x1 = (chunk.x + 1) * 32
    local y1 = (chunk.y + 1) * 32
    
    -- Find all simple-entity types in this chunk area
    local entities = surface.find_entities_filtered({
        area = {{x0, y0}, {x1, y1}},
        type = "simple-entity",
        force = "neutral"
    })
    
    -- Filter for actual rocks and build CSV payload
    local rock_rows = {}
    local rock_count = 0
    
    for _, entity in ipairs(entities) do
        -- Use the rock-specific filter to ensure we only get actual rocks
        if entity.prototype.count_as_rock_for_filtered_deconstruction then
            local x = utils.floor(entity.position.x)
            local y = utils.floor(entity.position.y)
            local name = entity.name
            
            -- Calculate size hint from collision box
            local collision_box = entity.prototype.collision_box
            local width = collision_box.right_bottom.x - collision_box.left_top.x
            local height = collision_box.right_bottom.y - collision_box.left_top.y
            local size_hint = math.max(math.floor(width), math.floor(height))
            
            rock_count = rock_count + 1
            rock_rows[rock_count] = name .. "," .. x .. "," .. y .. "," .. size_hint .. "\n"
        end
    end
    
    -- Emit rocks CSV for this chunk if any rocks found
    if rock_count > 0 then
        -- Add header row
        local header_row = table.concat(RESOURCE_ROCKS_HEADERS, ",") .. "\n"
        local payload = header_row .. table.concat(rock_rows, "", 1, rock_count)
        local metadata = {
            chunk_x = chunk.x,
            chunk_y = chunk.y,
            surface_id = 1,
            line_count = rock_count + 1  -- +1 for header
        }
        
        self:emit_csv({ 
            output_dir = "script-output/factoryverse",
            chunk_x = chunk.x,
            chunk_y = chunk.y,
            tick = game and game.tick or 0,
            metadata = { schema_version = "rocks.raw.v1" }
        }, "resource_rocks", payload, { headers = RESOURCE_ROCKS_HEADERS })
    end
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
        b = self:create_chunk_buffer(chunk_x, chunk_y, 1)
        b.headers = RESOURCE_TILES_HEADERS
        b.has_header = false  -- Track if header has been added
        BUFS[k] = b 
    end
    
    -- Add header if this is the first row
    if not b.has_header then
        b.count = b.count + 1
        b.rows[b.count] = table.concat(RESOURCE_TILES_HEADERS, ",") .. "\n"
        b.has_header = true
    end
    
    b.count = b.count + 1
    b.rows[b.count] = kind .. "," .. x .. "," .. y .. "," .. tostring(amount) .. "\n"
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
    
    if USE_UDP then
        -- Split into safe datagrams (~8KB)
        local payload = table.concat(b.rows, "", 1, b.count)
        local chunk_size = 8192
        for i = 1, #payload, chunk_size do
            helpers.send_udp(UDP_PORT, string.sub(payload, i, i + chunk_size - 1))
        end
    else
        -- Use parent class method for CSV file writing
        local metadata = {
            chunk_x = chunk_x,
            chunk_y = chunk_y,
            surface_id = b.surface,
            line_count = b.count
        }
        
        self:flush_chunk_buffer(b, "resource_tiles", "tiles.raw.v1", { headers = b.headers })
    end
    
    -- Clear this chunk's buffer
    BUFS[k] = nil
end

--- Flush a single buffer (legacy method for compatibility)
--- @param k string - buffer key
function ResourceSnapshot:_flush_one(k)
    local b = BUFS[k]
    if not b or b.count == 0 then return end
    
    if USE_UDP then
        -- Split into safe datagrams (~8KB)
        local payload = table.concat(b.rows, "", 1, b.count)
        local chunk_size = 8192
        for i = 1, #payload, chunk_size do
            helpers.send_udp(UDP_PORT, string.sub(payload, i, i + chunk_size - 1))
        end
    else
        -- Use parent class method for CSV file writing
        local metadata = {
            chunk_x = b.cx,
            chunk_y = b.cy,
            kind = b.kind,
            surface_id = b.surface,
            line_count = b.count
        }
        
        self:flush_chunk_buffer(b, "resource_tiles", "tiles.raw.v1", { headers = b.headers })
    end
    
    -- Reset buffer
    BUFS[k] = {
        rows = {}, 
        count = 0, 
        cx = b.cx, 
        cy = b.cy, 
        kind = b.kind, 
        surface = b.surface,
        headers = b.headers,
        has_header = false
    }
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
