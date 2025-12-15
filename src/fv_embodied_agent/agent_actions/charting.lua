local ChartingHelpers = {}

--- Helper function: Convert map/world coordinates to chunk coordinates
--- Factorio chunks are 32x32 tiles; chunk coord = floor(pos / 32)
--- @param position table {x:number, y:number}
--- @return table {x:number, y:number} chunk coordinates
local function map_to_chunk_coords(position)
    -- The math.floor ensures negative positions are handled correctly
    return {
        x = math.floor(position.x / 32),
        y = math.floor(position.y / 32)
    }
end

local function get_chunk_area(chunk_x, chunk_y)
    return {
        {x = chunk_x * 32, y = chunk_y * 32},
        -- Full chunk bounding box: bottom-right at next tile coordinate
        {x = (chunk_x + 1) * 32, y = (chunk_y + 1) * 32}
    }
end

--- Chart a single chunk at the given chunk coordinates
--- Internal API that consolidates charting, tracking, and event raising
--- @param self Agent
--- @param chunk_x number
--- @param chunk_y number
--- @return boolean True if chunk was charted, false if already charted
function ChartingHelpers._chart_chunk(self, chunk_x, chunk_y, rechart)
    local surface = game.surfaces[1]
    local force = self.character.force
    rechart = rechart or false

    local was_already_charted = force.is_chunk_charted(surface, {x = chunk_x, y = chunk_y})

    game.print(string.format("Chunk (%d, %d) was already charted: %s", chunk_x, chunk_y, tostring(was_already_charted)))
    
    -- Skip charting if already charted (unless rechart is true)
    if was_already_charted and not rechart then
        -- Chunk is already charted, but still mark for snapshotting if needed
        -- (chunks may have been charted by player but not snapshotted yet)
        if storage.chunk_tracker then
            storage.chunk_tracker:mark_chunk_needs_snapshot(chunk_x, chunk_y)
        end
        return false
    end
    
    -- Chart area uses tile coordinates, not chunk coordinates
    -- Chunk (x, y) covers tiles from (32*x, 32*y) to (32*x+31, 32*y+31)
    force.chart(surface, get_chunk_area(chunk_x, chunk_y))
    
    -- Track chunk in agent's charted_chunks
    table.insert(self.charted_chunks, {x = chunk_x, y = chunk_y})
    
    -- Mark chunk as needing snapshot (on_tick handler will process it)
    -- IMPORTANT: Access ChunkTracker via storage to avoid circular dependency
    -- (Map requires Agent, Agent requires charting, so charting cannot require Map)
    -- ChunkTracker is stored in storage.chunk_tracker and initialized by Map.init()
    if storage.chunk_tracker then
        storage.chunk_tracker:mark_chunk_needs_snapshot(chunk_x, chunk_y)
        game.print(string.format("Marked chunk (%d, %d) as needing snapshot", chunk_x, chunk_y))
        -- game.print(helpers.table_to_json(storage.chunk_tracker.chunk_lookup))
    else
        game.print(string.format("Chunk (%d, %d) was not already charted: %s", chunk_x, chunk_y, tostring(was_already_charted)))
    end
    
    -- Raise custom event (for any other listeners)
    script.raise_event(self.on_chunk_charted, {chunk_x = chunk_x, chunk_y = chunk_y})
    
    return true
end

--- Chart the starting area (7x7 chunks centered on spawn)
--- Uses ceil(200/32) = 7 chunks, so 3 chunks in each direction from center
--- @param self Agent
--- @return boolean
function ChartingHelpers.chart_spawn_area(self)
    local surface = game.surfaces[1]
    local force = self.character.force
    local spawn_position = force.get_spawn_position(surface)
    local r = 7
    
    -- Calculate spawn chunk coordinates
    local spawn_chunk = map_to_chunk_coords(spawn_position)
    
    -- Chart 7x7 chunks (3 chunks in each direction from center)
    for dx = -r, r do
        for dy = -r, r do
            local chunk_x = spawn_chunk.x + dx
            local chunk_y = spawn_chunk.y + dy
            ChartingHelpers._chart_chunk(self, chunk_x, chunk_y)
            -- game.print(string.format("Charting chunk (%d, %d)", chunk_x, chunk_y))
        end
    end
    
    return true
end

function ChartingHelpers.get_chunks_in_view(self)
    local center_chunk = map_to_chunk_coords(self.character.position)
    local chunks_in_view = {}

    -- Chart 5x5 chunks centered on the agent's current chunk
    -- This means 2 chunks in each direction from center
    for dx = -2, 2 do
        for dy = -2, 2 do
            local chunk_x = center_chunk.x + dx
            local chunk_y = center_chunk.y + dy
            table.insert(chunks_in_view, {x = chunk_x, y = chunk_y})
        end
    end
    return chunks_in_view
end

--- Chart a 5x5 chunk area around the agent's current position
--- Mimics LuaPlayer charting behavior: reveals 5x5 chunks centered on current chunk
--- @param self Agent
--- @return boolean
function ChartingHelpers.chart_view(self, rechart)
    rechart = rechart or false
    local chunks_in_view = ChartingHelpers.get_chunks_in_view(self)
    for _, chunk in pairs(chunks_in_view) do
        ChartingHelpers._chart_chunk(self, chunk.x, chunk.y, rechart)
    end
    return true
end

return ChartingHelpers