local Snapshot = require "core.Snapshot"
local utils = require "utils"

--- ResourceSnapshot: Detects and analyzes resource patches and water bodies
---
--- DESIGN DECISIONS:
--- 1. Resource patches = connected groups of same resource type using 4-neighbor connectivity
--- 2. Water patches = connected areas of water tiles using flood-fill
--- 3. Cross-chunk processing in raster order enables efficient boundary reconciliation
--- 4. Uses scanline Connected Component Labeling (CCL) for resources
--- 5. Uses Factorio's get_connected_tiles() for water (more efficient than manual flood-fill)
---
--- OUTPUT: Structured data suitable for JSON export and SQL analysis
--- TODO: Add trees to ResourceSnapshot
local ResourceSnapshot = Snapshot:new()
ResourceSnapshot.__index = ResourceSnapshot

function ResourceSnapshot:new()
    local instance = Snapshot:new()
    setmetatable(instance, self)
    return instance
end

function ResourceSnapshot:take()
    log("Taking resource snapshot")

    local charted_chunks = self.game_state:get_charted_chunks()
    local resource_data = self:_analyze_resource_patches(charted_chunks)
    local output = self:create_output("snapshot.resources", "v1", resource_data)

	-- Emit JSON for SQL ingestion (does not change return value)
	self:emit_json({ output_dir = "script-output/factoryverse" }, "resources", {
		meta = {
			schema_version = "snapshot.resources.v1",
			surface = output.surface,
			tick = output.timestamp,
		},
		data = output.data,
	})

    self:print_summary(output, function(out)
        local summary = { surface = out.surface, resources = {}, tick = out.timestamp }
        for _, resource in ipairs(out.data.resources) do
            table.insert(summary.resources, {
                name = resource.name,
                patch_count = resource.patch_count
            })
        end
        return summary
    end)

    return output
end

function ResourceSnapshot:take_water()
    local water_data = self.game_state:get_water_tiles_in_chunks(
        self.game_state:get_charted_chunks()
    )

    local patches = self:_analyze_water_patches(water_data.tiles, water_data.tile_names)
    local output = self:create_output("snapshot.water", "v1", {
        patch_count = #patches,
        patches = patches
    })

    	-- Emit JSON for SQL ingestion (does not change return value)
	self:emit_json({ output_dir = "script-output/factoryverse" }, "water", {
		meta = {
			schema_version = "snapshot.water.v1",
			surface = output.surface,
			tick = output.timestamp,
		},
		data = output.data,
	})

    self:print_summary(output, function(out)
        -- Show top 5 largest patches
        local sorted = {}
        for _, p in ipairs(out.data.patches) do table.insert(sorted, p) end
        table.sort(sorted, function(a, b) return a.tiles > b.tiles end)

        local top = {}
        for i = 1, math.min(5, #sorted) do
            local p = sorted[i]
            table.insert(top, {
                id = p.id,
                tiles = p.tiles,
                bbox = p.bbox,
                centroid = {
                    x = p.centroid.x,
                    y = p.centroid.y
                }
            })
        end

        return {
            surface = out.surface,
            water = { patch_count = out.data.patch_count, top = top },
            tick = out.timestamp
        }
    end)

    return output
end

--- RESOURCE PATCH ANALYSIS (Connected Component Labeling)

--- Analyze resource patches using scanline CCL across chunk boundaries
--- @param chunks table - list of charted chunks
--- @return table - structured resource data
function ResourceSnapshot:_analyze_resource_patches(chunks)
    -- Sort chunks in raster order for efficient boundary reconciliation
    table.sort(chunks, function(a, b)
        if a.y == b.y then return a.x < b.x end
        return a.y < b.y
    end)

    local state = {
        resources = {}, -- [name] = ResourceTracker
        next_gid = 1
    }

    -- Process each chunk in order
    for _, chunk in ipairs(chunks) do
        self:_process_chunk_for_resources(chunk, state)
    end

    return self:_finalize_resource_output(state)
end

--- Process a single chunk for resource detection
--- @param chunk table - chunk data {x, y, area}
--- @param state table - global tracking state
function ResourceSnapshot:_process_chunk_for_resources(chunk, state)
    local cx, cy = chunk.x, chunk.y
    local chunk_key = utils.chunk_key(cx, cy)
    local resources_in_chunk = self.game_state:get_resources_in_chunks({ chunk })

    -- Fast skip if the engine reports no resources in this chunk
    if not resources_in_chunk or next(resources_in_chunk) == nil then
        return
    end

    for resource_name, entities in pairs(resources_in_chunk) do
        local tracker = self:_get_resource_tracker(state, resource_name)

        -- Run local CCL on this chunk
        local grid = self:_entities_to_grid(entities)
        local bounds = self:_get_chunk_bounds(chunk.area)
        local ccl_result = self:_run_local_ccl(grid, bounds)

        -- Store edge information for boundary reconciliation
        tracker.edges[chunk_key] = ccl_result.edges
        tracker.local2global[chunk_key] = {}

        -- Reconcile with neighbors (north and west already processed)
        self:_reconcile_chunk_boundaries(tracker, chunk_key, cx, cy)

        -- Assign global IDs and accumulate patch data
        self:_accumulate_patch_data(tracker, chunk_key, ccl_result, state)
    end
end

--- Run Connected Component Labeling on a position grid within chunk bounds
--- This is the core algorithm: scanline CCL with local equivalence tracking
--- @param grid table - [y][x] = amount
--- @param bounds table - {min_x, min_y, max_x, max_y}
--- @return table - {labels=grid, runs=runs_by_label, edges=edge_segments}
function ResourceSnapshot:_run_local_ccl(grid, bounds)
    local min_x, min_y = bounds.min_x, bounds.min_y
    local max_x, max_y = bounds.max_x, bounds.max_y

    local next_local = 1
    local label_grid = {}             -- [y][x] = local_label
    local local_dsu = utils.DSU:new() -- for local equivalence resolution
    local edges = { north = {}, south = {}, west = {}, east = {} }

    -- Scanline CCL with 4-connectivity
    for y = min_y, max_y do
        local row = grid[y]
        if row then
            for x = min_x, max_x do
                if row[x] then
                    -- Check west and north neighbors
                    local west_lbl = (label_grid[y] and label_grid[y][x - 1]) or nil
                    local north_lbl = (label_grid[y - 1] and label_grid[y - 1][x]) or nil

                    local label
                    if west_lbl and north_lbl then
                        label = west_lbl
                        if north_lbl ~= west_lbl then
                            local_dsu:union(west_lbl, north_lbl)
                        end
                    elseif west_lbl or north_lbl then
                        label = west_lbl or north_lbl
                    else
                        label = next_local
                        next_local = next_local + 1
                    end

                    if not label_grid[y] then label_grid[y] = {} end
                    label_grid[y][x] = label
                end
            end
        end
    end

    -- Build runs and edges from labeled grid
    local runs_by_label = self:_extract_runs_and_edges(label_grid, grid, bounds, edges, local_dsu)

    return {
        labels = label_grid,
        runs = runs_by_label,
        edges = edges,
        local_dsu = local_dsu
    }
end

--- Extract horizontal runs and edge segments from labeled grid
--- @param label_grid table - [y][x] = local_label
--- @param amount_grid table - [y][x] = amount
--- @param bounds table - chunk bounds
--- @param edges table - edge segments to populate
--- @param local_dsu table - local DSU for label resolution
--- @return table - runs grouped by resolved label
function ResourceSnapshot:_extract_runs_and_edges(label_grid, amount_grid, bounds, edges, local_dsu)
    local min_x, min_y = bounds.min_x, bounds.min_y
    local max_x, max_y = bounds.max_x, bounds.max_y
    local runs_by_label = {}

    for y = min_y, max_y do
        local label_row = label_grid[y]
        local amount_row = amount_grid[y]
        if label_row and amount_row then
            local run_label, run_x, run_len, run_sum = nil, nil, 0, 0

            for x = min_x, max_x + 1 do -- +1 for sentinel
                local label = label_row[x]
                if label then label = local_dsu:find(label) end

                if label and (run_label == nil or label == run_label) then
                    -- Continue or start run
                    if run_label == nil then
                        run_label, run_x, run_len, run_sum = label, x, 0, 0
                    end
                    run_len = run_len + 1
                    run_sum = run_sum + (amount_row[x] or 0)
                else
                    -- End current run
                    if run_label then
                        self:_add_run_to_label(runs_by_label, run_label, y, run_x, run_len, run_sum)

                        -- Add edge segments for boundary reconciliation
                        if y == min_y then
                            table.insert(edges.north, { y = y, x = run_x, len = run_len, lbl = run_label, k = run_x })
                        end
                        if y == max_y then
                            table.insert(edges.south, { y = y, x = run_x, len = run_len, lbl = run_label, k = run_x })
                        end
                    end

                    -- Start new run
                    if label then
                        run_label, run_x, run_len, run_sum = label, x, 1, (amount_row[x] or 0)
                    else
                        run_label = nil
                    end
                end
            end
        end
    end

    -- Add vertical edges (west/east boundaries)
    for y = min_y, max_y do
        local label_row = label_grid[y]
        if label_row then
            local west_lbl = label_row[min_x]
            if west_lbl then
                table.insert(edges.west, { y = y, x = min_x, len = 1, lbl = local_dsu:find(west_lbl), k = y })
            end

            local east_lbl = label_row[max_x]
            if east_lbl then
                table.insert(edges.east, { y = y, x = max_x, len = 1, lbl = local_dsu:find(east_lbl), k = y })
            end
        end
    end

    return runs_by_label
end

--- Add a run segment to the runs collection
--- @param runs_by_label table - collection to add to
--- @param label number - component label
--- @param y number - row coordinate
--- @param x number - start x coordinate
--- @param len number - run length
--- @param sum_amount number - total amount in run
function ResourceSnapshot:_add_run_to_label(runs_by_label, label, y, x, len, sum_amount)
    if not runs_by_label[label] then runs_by_label[label] = {} end
    if not runs_by_label[label][y] then runs_by_label[label][y] = {} end

    table.insert(runs_by_label[label][y], {
        x = x, y = y, len = len, sum_amount = sum_amount
    })
end

--- BOUNDARY RECONCILIATION (link components across chunk boundaries)

--- Reconcile chunk boundaries with already-processed neighbors
--- @param tracker table - resource tracker
--- @param chunk_key string - current chunk key
--- @param cx number - chunk x coordinate
--- @param cy number - chunk y coordinate
function ResourceSnapshot:_reconcile_chunk_boundaries(tracker, chunk_key, cx, cy)
    local edges = tracker.edges[chunk_key]

    -- North neighbor
    local north_key = utils.chunk_key(cx, cy - 1)
    local north_edges = tracker.edges[north_key]
    if north_edges and north_edges.south and #north_edges.south > 0 and #edges.north > 0 then
        self:_reconcile_edge_pair(tracker, north_edges.south, edges.north, north_key, chunk_key)
    end

    -- West neighbor
    local west_key = utils.chunk_key(cx - 1, cy)
    local west_edges = tracker.edges[west_key]
    if west_edges and west_edges.east and #west_edges.east > 0 and #edges.west > 0 then
        self:_reconcile_edge_pair(tracker, west_edges.east, edges.west, west_key, chunk_key)
    end
end

--- Reconcile two edge lists by linking overlapping segments
--- @param tracker table - resource tracker with global DSU
--- @param edges_a table - neighbor chunk edges
--- @param edges_b table - current chunk edges
--- @param chunk_a string - neighbor chunk key
--- @param chunk_b string - current chunk key
function ResourceSnapshot:_reconcile_edge_pair(tracker, edges_a, edges_b, chunk_a, chunk_b)
    table.sort(edges_a, function(a, b) return a.k < b.k end)
    table.sort(edges_b, function(a, b) return a.k < b.k end)

    local i, j = 1, 1
    while i <= #edges_a and j <= #edges_b do
        local seg_a, seg_b = edges_a[i], edges_b[j]
        local a_start, a_len = (seg_a.x or seg_a.y), (seg_a.len or 1)
        local b_start, b_len = (seg_b.x or seg_b.y), (seg_b.len or 1)
        local a_end = a_start + a_len - 1
        local b_end = b_start + b_len - 1

        if utils.ranges_overlap(a_start, a_end, b_start, b_end) then
            -- Link the global components
            local gid_a = self:_get_global_id(tracker, chunk_a, seg_a.lbl)
            local gid_b = self:_get_global_id(tracker, chunk_b, seg_b.lbl)
            tracker.dsu:union(gid_a, gid_b)
        end

        if a_end < b_end then i = i + 1 else j = j + 1 end
    end
end

--- HELPER FUNCTIONS

--- Get or create resource tracker for a resource type
--- @param state table - global state
--- @param name string - resource name
--- @return table - resource tracker
function ResourceSnapshot:_get_resource_tracker(state, name)
    local tracker = state.resources[name]
    if not tracker then
        tracker = {
            dsu = utils.DSU:new(),
            local2global = {},
            patches = {},
            edges = {}
        }
        state.resources[name] = tracker
    end
    return tracker
end

--- Get or assign global ID for local label
--- @param tracker table - resource tracker
--- @param chunk_key string - chunk identifier
--- @param local_label number - local component label
--- @return number - global ID
function ResourceSnapshot:_get_global_id(tracker, chunk_key, local_label)
    if not tracker.local2global[chunk_key] then
        tracker.local2global[chunk_key] = {}
    end

    local gid = tracker.local2global[chunk_key][local_label]
    if not gid then
        gid = tracker.next_gid or 1
        tracker.next_gid = gid + 1
        tracker.local2global[chunk_key][local_label] = gid
        tracker.dsu:find(gid) -- initialize in DSU
    end

    return gid
end

--- Convert entity list to position grid
--- @param entities table - resource entities
--- @return table - [y][x] = amount
function ResourceSnapshot:_entities_to_grid(entities)
    local grid = {}
    for _, entity in ipairs(entities) do
        local x = utils.floor(entity.position.x)
        local y = utils.floor(entity.position.y)

        local row = grid[y]
        if not row then
            row = {}
            grid[y] = row
        end
        row[x] = (row[x] or 0) + (entity.amount or 0)
    end
    return grid
end

--- Get chunk bounds from area
--- @param area table - {left_top, right_bottom}
--- @return table - {min_x, min_y, max_x, max_y}
function ResourceSnapshot:_get_chunk_bounds(area)
    return {
        min_x = utils.floor(area.left_top.x),
        min_y = utils.floor(area.left_top.y),
        max_x = utils.floor(area.right_bottom.x) - 1,
        max_y = utils.floor(area.right_bottom.y) - 1
    }
end

--- Accumulate patch data from CCL results into global patches
--- @param tracker table - resource tracker
--- @param chunk_key string - chunk identifier
--- @param ccl_result table - CCL output
--- @param state table - global state
function ResourceSnapshot:_accumulate_patch_data(tracker, chunk_key, ccl_result, state)
    for local_label, runs_by_y in pairs(ccl_result.runs) do
        local gid = self:_get_global_id(tracker, chunk_key, local_label)
        local canonical_gid = tracker.dsu:find(gid)

        -- Get or create patch data
        local patch = tracker.patches[canonical_gid]
        if not patch then
            patch = {
                tiles = 0,
                amount = 0,
                min_x = 1e9,
                min_y = 1e9,
                max_x = -1e9,
                max_y = -1e9,
                sum_x = 0,
                sum_y = 0,
                row_spans = {}
            }
            tracker.patches[canonical_gid] = patch
        end

        -- Add runs to patch
        for y, runs in pairs(runs_by_y) do
            for _, run in ipairs(runs) do
                self:_add_run_to_patch(patch, y, run.x, run.len, run.sum_amount)
            end
        end
    end
end

--- Add a run segment to patch data
--- @param patch table - patch data
--- @param y number - row coordinate
--- @param x number - start x
--- @param len number - length
--- @param sum_amount number - total amount
function ResourceSnapshot:_add_run_to_patch(patch, y, x, len, sum_amount)
    -- Add to row spans
    if not patch.row_spans[y] then patch.row_spans[y] = {} end
    table.insert(patch.row_spans[y], {
        x = x, y = y, len = len, tile_count = len, sum_amount = sum_amount
    })

    -- Update aggregates
    patch.tiles = patch.tiles + len
    patch.amount = patch.amount + sum_amount

    -- Update bounds
    local x2 = x + len - 1
    if y < patch.min_y then patch.min_y = y end
    if y > patch.max_y then patch.max_y = y end
    if x < patch.min_x then patch.min_x = x end
    if x2 > patch.max_x then patch.max_x = x2 end

    -- Update centroid sum (use integer arithmetic to avoid floating-point precision loss)
    -- Instead of (x + x2) * 0.5 * len, use (x + x2) * len / 2 but keep as integer operations
    patch.sum_x = patch.sum_x + (x + x2) * len
    patch.sum_y = patch.sum_y + y * len * 2
end

--- Create final output structure from tracking state
--- @param state table - tracking state
--- @return table - structured output
function ResourceSnapshot:_finalize_resource_output(state)
    local resources_out = {}

    for resource_name, tracker in pairs(state.resources) do
        local patches_out = {}

        for gid, patch in pairs(tracker.patches) do
            local canonical_gid = tracker.dsu:find(gid)
            if canonical_gid == gid then -- only emit canonical patches
                -- Calculate centroid with precise division to Factorio's coordinate grid
                local cx = (patch.tiles > 0) and (math.floor(patch.sum_x / (patch.tiles * 2) * 256 + 0.5) / 256) or 0
                local cy = (patch.tiles > 0) and (math.floor(patch.sum_y / (patch.tiles * 2) * 256 + 0.5) / 256) or 0

                table.insert(patches_out, {
                    patch_id = gid,
                    resource_name = resource_name,
                    tiles = patch.tiles,
                    total_amount = patch.amount,
                    bbox = {
                        min_x = patch.min_x,
                        min_y = patch.min_y,
                        max_x = patch.max_x,
                        max_y = patch.max_y
                    },
                    centroid = { x = cx, y = cy },
                    row_spans = patch.row_spans
                })
            end
        end

        table.insert(resources_out, {
            name = resource_name,
            patch_count = #patches_out,
            patches = patches_out
        })
    end

    return { resources = resources_out }
end

--- WATER PATCH ANALYSIS (Flood Fill)

--- Analyze water patches using flood fill
--- @param tiles table - water tiles
--- @param tile_names table - water tile names
--- @return table - water patch data
function ResourceSnapshot:_analyze_water_patches(tiles, tile_names)
    local visited = {}
    local patches = {}
    local next_id = 1

    for _, tile in ipairs(tiles) do
        local x, y = utils.extract_position(tile)
        if x and y then
            local key = utils.chunk_key(x, y)
            if not visited[key] then
                local connected = self.game_state:get_connected_water_tiles(tile.position, tile_names)
                local patch = self:_create_water_patch_from_tiles(connected, next_id)

                -- Mark all tiles as visited
                for _, t in ipairs(connected) do
                    local tx, ty = utils.extract_position(t)
                    if tx and ty then
                        visited[utils.chunk_key(tx, ty)] = true
                    end
                end

                table.insert(patches, patch)
                next_id = next_id + 1
            end
        end
    end

    return patches
end

--- Create water patch data from connected tiles
--- @param tiles table - connected water tiles
--- @param id number - patch ID
--- @return table - patch data
function ResourceSnapshot:_create_water_patch_from_tiles(tiles, id)
    local patch = {
        id = id,
        tiles = 0,
        bbox = { min_x = 1e9, min_y = 1e9, max_x = -1e9, max_y = -1e9 },
        sum_x = 0,
        sum_y = 0
    }

    -- Track tile positions per row to build row-wise spans for granular placement logic
    local rows = {}

    for _, tile in ipairs(tiles) do
        local x, y = utils.extract_position(tile)
        if x and y then
            patch.tiles = patch.tiles + 1

            if x < patch.bbox.min_x then patch.bbox.min_x = x end
            if y < patch.bbox.min_y then patch.bbox.min_y = y end
            if x > patch.bbox.max_x then patch.bbox.max_x = x end
            if y > patch.bbox.max_y then patch.bbox.max_y = y end

            patch.sum_x = patch.sum_x + x
            patch.sum_y = patch.sum_y + y

            if not rows[y] then rows[y] = {} end
            rows[y][x] = true
        end
    end

    -- Compress per-row x positions into contiguous spans
    if next(rows) ~= nil then
        patch.row_spans = {}
        for y, xs in pairs(rows) do
            local x_list = {}
            for x, _ in pairs(xs) do table.insert(x_list, x) end
            table.sort(x_list)

            local seg_start, prev_x = nil, nil
            for i = 1, #x_list do
                local xv = x_list[i]
                if seg_start == nil then
                    seg_start = xv
                    prev_x = xv
                else
                    if xv == prev_x + 1 then
                        prev_x = xv
                    else
                        if not patch.row_spans[y] then patch.row_spans[y] = {} end
                        table.insert(patch.row_spans[y], { x = seg_start, y = y, len = prev_x - seg_start + 1, tile_count = prev_x - seg_start + 1 })
                        seg_start = xv
                        prev_x = xv
                    end
                end
            end

            if seg_start ~= nil then
                if not patch.row_spans[y] then patch.row_spans[y] = {} end
                table.insert(patch.row_spans[y], { x = seg_start, y = y, len = (prev_x - seg_start + 1), tile_count = (prev_x - seg_start + 1) })
            end
        end
    end

    -- Calculate centroid with precise division to avoid floating-point drift
    -- Factorio MapPosition uses double precision but tile coordinates are integers
    if patch.tiles > 0 then
        -- Use math.floor to snap to Factorio's coordinate grid (minimum precision: 1/256 = 0.00390625)
        patch.centroid = {
            x = math.floor(patch.sum_x / patch.tiles * 256 + 0.5) / 256,
            y = math.floor(patch.sum_y / patch.tiles * 256 + 0.5) / 256
        }
    else
        patch.centroid = { x = 0, y = 0 }
    end

    return patch
end

--- VISUALIZATION/DEBUG

function ResourceSnapshot:render(output)
    -- Same render logic as before, but working with new output structure
    local DRAW_SPANS, DRAW_BBOX, DRAW_CENTROID, DRAW_LABEL = true, true, true, true
    local ONLY_IN_ALT, TTL_TICKS = false, nil
    local surface = game.surfaces[1]

    if rendering then rendering.clear() end

    local function tint_for(name)
        local map = {
            ["iron-ore"] = { r = 0.55, g = 0.75, b = 1.00, a = 1 },
            ["copper-ore"] = { r = 1.00, g = 0.60, b = 0.30, a = 1 },
            ["coal"] = { r = 0.35, g = 0.35, b = 0.35, a = 1 },
            ["stone"] = { r = 0.80, g = 0.80, b = 0.80, a = 1 },
            ["crude-oil"] = { r = 0.45, g = 0.10, b = 0.80, a = 1 }
        }
        return map[name] or { r = 0.90, g = 0.90, b = 0.90, a = 1 }
    end

    for _, resource in ipairs(output.data.resources) do
        local tint = tint_for(resource.name)
        for _, patch in ipairs(resource.patches) do
            -- Draw row spans
            if DRAW_SPANS and patch.row_spans then
                for y, segments in pairs(patch.row_spans) do
                    for _, seg in ipairs(segments) do
                        rendering.draw_rectangle {
                            surface = surface,
                            left_top = { seg.x, y },
                            right_bottom = { seg.x + seg.len, y + 1 },
                            color = { r = tint.r, g = tint.g, b = tint.b, a = 0.20 },
                            filled = true,
                            only_in_alt_mode = ONLY_IN_ALT,
                            time_to_live = TTL_TICKS,
                            draw_on_ground = true
                        }
                    end
                end
            end

            -- Draw bbox, centroid, labels (same as before...)
            if DRAW_BBOX and patch.bbox then
                rendering.draw_rectangle {
                    surface = surface,
                    left_top = { patch.bbox.min_x, patch.bbox.min_y },
                    right_bottom = { patch.bbox.max_x + 1, patch.bbox.max_y + 1 },
                    color = { r = tint.r, g = tint.g, b = tint.b, a = 0.90 },
                    filled = false, width = 1,
                    only_in_alt_mode = ONLY_IN_ALT,
                    time_to_live = TTL_TICKS,
                    draw_on_ground = true
                }
            end

            if DRAW_CENTROID and patch.centroid then
                rendering.draw_circle {
                    surface = surface,
                    target = { patch.centroid.x, patch.centroid.y },
                    radius = 0.35, filled = true,
                    color = { r = tint.r, g = tint.g, b = tint.b, a = 0.90 },
                    only_in_alt_mode = ONLY_IN_ALT,
                    time_to_live = TTL_TICKS,
                    draw_on_ground = true
                }
            end

            if DRAW_LABEL then
                rendering.draw_text {
                    surface = surface,
                    target = { patch.centroid.x, patch.centroid.y - 0.8 },
                    text = {
                        "", resource.name, " #", tostring(patch.patch_id),
                        "\ntiles:", tostring(patch.tiles),
                        " amt:", tostring(patch.total_amount)
                    },
                    color = { 1, 1, 1, 1 }, scale_with_zoom = true,
                    only_in_alt_mode = ONLY_IN_ALT,
                    time_to_live = TTL_TICKS
                }
            end
        end
    end
end

return ResourceSnapshot
