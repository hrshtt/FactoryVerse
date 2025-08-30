local GameState = require("core.game_state.GameState")


local triple_print = function(print_str)
    game.print(print_str)
    log(print_str)
    rcon.print(print_str)
end

local M = {}
M.helpers = {}
M.commands = {}

M.helpers.create_agent_characters = function(num_agents, destroy_existing)
    return GameState:new():agent():create_agent_characters(num_agents, destroy_existing)
end

M.helpers.test = function()
    -- Option A: Chunked Connected-Component Labeling (CCL) with border merges
    -- Scrappy, single function implementation. Processes charted chunks, builds patches per resource.

    local surface = game.surfaces[1]
    local charted_chunks = GameState:new():get_charted_chunks(true) -- assumes it returns { {x=.., y=.., area=...}, ... }

    -- 1) Sort chunks into raster order (cy asc, then cx asc) to simplify north/west reconciliation
    table.sort(charted_chunks, function(a, b)
        if a.y == b.y then return a.x < b.x end
        return a.y < b.y
    end)

    -- Utilities
    local function chunk_key(cx, cy) return cx .. ":" .. cy end
    local function floor(v) return math.floor(v) end

    -- Global state per resource name
    local resources = {}  -- [resource_name] = { next_gid=1, dsu_parent={}, dsu_size={},
                          --   local2global = { [chunk_key] = { [local_label]=gid } },
                          --   patches = { [gid] = { tiles=0, amount=0, min_x=1e9, min_y=1e9, max_x=-1e9, max_y=-1e9,
                          --                           sum_x=0, sum_y=0, row_spans={} } },
                          --   edges = { [chunk_key] = { north={}, south={}, west={}, east={} } }
                          -- }

    local function res_get(name)
        local R = resources[name]
        if not R then
            R = { next_gid = 1, dsu_parent = {}, dsu_size = {}, local2global = {}, patches = {}, edges = {} }
            resources[name] = R
        end
        return R
    end

    local function dsu_find(R, x)
        local p = R.dsu_parent[x]
        if not p then R.dsu_parent[x] = x; R.dsu_size[x] = 1; return x end
        if p ~= x then R.dsu_parent[x] = dsu_find(R, p) end
        return R.dsu_parent[x]
    end

    local function dsu_union(R, a, b)
        a = dsu_find(R, a); b = dsu_find(R, b)
        if a == b then return a end
        if (R.dsu_size[a] or 1) < (R.dsu_size[b] or 1) then a, b = b, a end
        R.dsu_parent[b] = a
        R.dsu_size[a] = (R.dsu_size[a] or 1) + (R.dsu_size[b] or 1)
        return a
    end

    local function patch_get(R, gid)
        gid = dsu_find(R, gid)
        local P = R.patches[gid]
        if not P then
            P = { tiles=0, amount=0, min_x=1e9, min_y=1e9, max_x=-1e9, max_y=-1e9, sum_x=0, sum_y=0, row_spans={} }
            R.patches[gid] = P
        end
        return P, gid
    end

    -- Helper to append a row-span segment to a patch
    local function add_row_span(P, y, x, len, sum_amount)
        local row = P.row_spans[y]
        if not row then row = {}; P.row_spans[y] = row end
        table.insert(row, { x = x, len = len, tile_count = len, sum_amount = sum_amount })
    end

    -- Main loop: per chunk in raster order
    for _, chunk in ipairs(charted_chunks) do
        local cx, cy = chunk.x, chunk.y
        local ck = chunk_key(cx, cy)
        local area = chunk.area

        -- 2) Pull only resources in this chunk
        local entities = surface.find_entities_filtered{ area = area, type = "resource" }
        if #entities == 0 then
            -- still create empty edges placeholder to simplify neighbor lookups
            for name, R in pairs(resources) do
                R.edges[ck] = R.edges[ck] or { north={}, south={}, west={}, east={} }
            end
        end

        -- 3) Bucket entities by resource name for independent labeling
        local by_name = {} -- [name] = { list = {entity,...}, grid = { [y] = { [x] = amount } } }
        for i=1,#entities do
            local e = entities[i]
            local name = e.name
            local bx = floor(e.position.x)
            local by = floor(e.position.y)
            local b = by_name[name]
            if not b then b = { list = {}, grid = {} }; by_name[name] = b end
            table.insert(b.list, e)
            local row = b.grid[by]; if not row then row = {}; b.grid[by] = row end
            row[bx] = (row[bx] or 0) + (e.amount or 0)
        end

        -- 4) For each resource name, run a local CCL inside the chunk and build edge maps
        for name, bucket in pairs(by_name) do
            local R = res_get(name)
            R.edges[ck] = R.edges[ck] or { north={}, south={}, west={}, east={} }
            local E = R.edges[ck]

            -- Determine chunk bounds (integers) from area
            local min_x = floor(area.left_top.x)
            local min_y = floor(area.left_top.y)
            local max_x = floor(area.right_bottom.x) - 1
            local max_y = floor(area.right_bottom.y) - 1

            -- local labeling state
            local next_local = 1
            local label_at = {}      -- [y][x] = local_label
            local amounts_at = {}    -- [y][x] = amount (summed if duplicate entities exist)

            -- scanline CCL (4-neighbour): process rows from min_y..max_y, cols from min_x..max_x
            for y = min_y, max_y do
                local row = bucket.grid[y]
                if row then
                    for x = min_x, max_x do
                        local amt = row[x]
                        if amt then
                            -- neighbors: west (x-1,y) and north (x,y-1)
                            local left_lbl = (label_at[y] and label_at[y][x-1]) or nil
                            local up_lbl = (label_at[y-1] and label_at[y-1][x]) or nil
                            local lbl
                            if left_lbl and up_lbl then
                                lbl = left_lbl
                                if up_lbl ~= left_lbl then
                                    -- record an equivalence later; for simplicity, union now in a local DSU via a map
                                    -- We'll emulate with a small parent map per chunk.
                                    -- Create table on demand
                                    local local_parent = label_at._parent
                                    if not local_parent then local_parent = {}; label_at._parent = local_parent end
                                    local function lfind(a)
                                        local p = local_parent[a]
                                        if not p then local_parent[a] = a; return a end
                                        if p ~= a then local_parent[a] = lfind(p) end
                                        return local_parent[a]
                                    end
                                    local function lunion(a,b)
                                        a = lfind(a); b = lfind(b)
                                        if a ~= b then local_parent[b] = a end
                                    end
                                    lunion(left_lbl, up_lbl)
                                end
                            elseif left_lbl or up_lbl then
                                lbl = left_lbl or up_lbl
                            else
                                lbl = next_local
                                next_local = next_local + 1
                            end
                            -- set label and amount
                            local ly = label_at[y]; if not ly then ly = {}; label_at[y] = ly end
                            ly[x] = lbl
                            local ay = amounts_at[y]; if not ay then ay = {}; amounts_at[y] = ay end
                            ay[x] = amt
                        end
                    end
                end
            end

            -- compress local labels using the local parent map (resolve equivalences)
            local local_parent = label_at._parent or {}
            local function lfind(a)
                local p = local_parent[a]
                if not p then local_parent[a] = a; return a end
                if p ~= a then local_parent[a] = lfind(p) end
                return local_parent[a]
            end

            -- Build per-row runs per resolved local label, and collect edge maps
            local local_runs = {} -- [local_label] = { [y] = { {x,len,sum_amount}, ... } }
            for y = min_y, max_y do
                local ly = label_at[y]
                local ay = amounts_at[y]
                if ly and ay then
                    local run_lbl, run_x, run_len, run_sum = nil, nil, 0, 0
                    for x = min_x, max_x + 1 do -- sentinel at end
                        local lbl = ly[x]
                        if lbl then lbl = lfind(lbl) end
                        if lbl and (run_lbl == nil or lbl == run_lbl) then
                            -- continue run
                            if run_lbl == nil then run_lbl, run_x, run_len, run_sum = lbl, x, 0, 0 end
                            run_len = run_len + 1
                            run_sum = run_sum + (ay[x] or 0)
                        else
                            if run_lbl ~= nil then
                                local runs_y = local_runs[run_lbl]; if not runs_y then runs_y = {}; local_runs[run_lbl] = runs_y end
                                local ry = runs_y[y]; if not ry then ry = {}; runs_y[y] = ry end
                                table.insert(ry, { x = run_x, len = run_len, sum_amount = run_sum })
                                -- Edge capture
                                if y == min_y then table.insert(E.north, { y=y, x=run_x, len=run_len, lbl=run_lbl }) end
                                if y == max_y then table.insert(E.south, { y=y, x=run_x, len=run_len, lbl=run_lbl }) end
                            end
                            -- start new run if lbl exists
                            if lbl then
                                run_lbl, run_x, run_len, run_sum = lbl, x, 1, (ay[x] or 0)
                            else
                                run_lbl, run_x, run_len, run_sum = nil, nil, 0, 0
                            end
                        end
                    end
                end
            end
            -- Vertical edges (west/east) from per-column scan using per-row labels
            for y = min_y, max_y do
                local ly = label_at[y]
                if ly then
                    local lbl_w = ly[min_x]
                    if lbl_w then table.insert(E.west, { y=y, x=min_x, len=1, lbl=lfind(lbl_w) }) end
                    local lbl_e = ly[max_x]
                    if lbl_e then table.insert(E.east, { y=y, x=max_x, len=1, lbl=lfind(lbl_e) }) end
                end
            end

            -- 5) Reconcile with north / west neighbors (already processed in raster order)
            local function assign_gid(local_lbl)
                local map = R.local2global[ck]; if not map then map = {}; R.local2global[ck] = map end
                local gid = map[local_lbl]
                if not gid then
                    gid = R.next_gid; R.next_gid = R.next_gid + 1
                    map[local_lbl] = gid
                    -- ensure DSU root
                    dsu_find(R, gid)
                end
                return gid
            end

            -- north neighbor reconciliation
            local nk = chunk_key(cx, cy - 1)
            local nE = R.edges[nk]
            if nE and nE.south and #nE.south > 0 and #E.north > 0 then
                -- match by overlapping x ranges at same y
                local i, j = 1, 1
                table.sort(nE.south, function(a,b) return a.x < b.x end)
                table.sort(E.north, function(a,b) return a.x < b.x end)
                while i <= #nE.south and j <= #E.north do
                    local a = nE.south[i] -- neighbor run
                    local b = E.north[j]  -- current run
                    -- same y implicit (a.y==min_y-1, b.y==min_y), but vertical adjacency is guaranteed between chunks
                    local ax1, ax2 = a.x, a.x + a.len - 1
                    local bx1, bx2 = b.x, b.x + b.len - 1
                    if ax2 < bx1 then
                        i = i + 1
                    elseif bx2 < ax1 then
                        j = j + 1
                    else
                        -- overlapping columns -> they connect (4-neighbour)
                        local gidA = R.local2global[nk] and R.local2global[nk][a.lbl]
                        local gidB = assign_gid(b.lbl)
                        if gidA then dsu_union(R, gidA, gidB) end
                        -- advance the smaller end
                        if ax2 < bx2 then i = i + 1 else j = j + 1 end
                    end
                end
            end

            -- west neighbor reconciliation
            local wk = chunk_key(cx - 1, cy)
            local wE = R.edges[wk]
            if wE and wE.east and #wE.east > 0 and #E.west > 0 then
                table.sort(wE.east, function(a,b) return a.y < b.y end)
                table.sort(E.west, function(a,b) return a.y < b.y end)
                local i, j = 1, 1
                while i <= #wE.east and j <= #E.west do
                    local a = wE.east[i]
                    local b = E.west[j]
                    if a.y < b.y then i = i + 1
                    elseif b.y < a.y then j = j + 1
                    else
                        -- same row, adjacent columns across chunk boundary -> connect
                        local gidA = R.local2global[wk] and R.local2global[wk][a.lbl]
                        local gidB = assign_gid(b.lbl)
                        if gidA then dsu_union(R, gidA, gidB) end
                        i = i + 1; j = j + 1
                    end
                end
            end

            -- 6) Assign global ids for all local labels that still lack one
            for local_lbl, runs_by_y in pairs(local_runs) do
                -- ensure gid exists
                assign_gid(local_lbl)
            end

            -- 7) Aggregate rows into patches using canonical gids
            for local_lbl, runs_by_y in pairs(local_runs) do
                local gid = R.local2global[ck][local_lbl]
                local root = dsu_find(R, gid)
                local P = patch_get(R, root)
                for y, runs in pairs(runs_by_y) do
                    for _, seg in ipairs(runs) do
                        add_row_span(P, y, seg.x, seg.len, seg.sum_amount)
                        -- aggregates
                        P.tiles = P.tiles + seg.len
                        P.amount = P.amount + (seg.sum_amount or 0)
                        -- bbox and centroid sums
                        local x1 = seg.x; local x2 = seg.x + seg.len - 1
                        if y < P.min_y then P.min_y = y end
                        if y > P.max_y then P.max_y = y end
                        if x1 < P.min_x then P.min_x = x1 end
                        if x2 > P.max_x then P.max_x = x2 end
                        -- centroid approx via segment midpoints
                        local midx = (x1 + x2) * 0.5
                        P.sum_x = P.sum_x + midx * seg.len
                        P.sum_y = P.sum_y + y * seg.len
                    end
                end
            end
        end

        -- Ensure edges tables exist for resources not present in this chunk (so later lookups are safe)
        for name, R in pairs(resources) do
            R.edges[ck] = R.edges[ck] or { north={}, south={}, west={}, east={} }
        end
    end

    -- 8) Finalize: compress DSU representatives and produce a compact summary per resource
    local out = { schema_version = "snapshot.resources.v1-scrappy", surface = surface.name, resources = {} }

    for name, R in pairs(resources) do
        -- Relabel patches to canonical ids and compute centroid
        local list = {}
        for gid, P in pairs(R.patches) do
            local root = dsu_find(R, gid)
            if root ~= gid then
                -- merge P into root patch
                local Q = R.patches[root]
                if Q then
                    Q.tiles = Q.tiles + P.tiles
                    Q.amount = Q.amount + P.amount
                    if P.min_x < Q.min_x then Q.min_x = P.min_x end
                    if P.min_y < Q.min_y then Q.min_y = P.min_y end
                    if P.max_x > Q.max_x then Q.max_x = P.max_x end
                    if P.max_y > Q.max_y then Q.max_y = P.max_y end
                    Q.sum_x = Q.sum_x + P.sum_x
                    Q.sum_y = Q.sum_y + P.sum_y
                    -- merge row_spans (append; consumers can re-sort by y/x later)
                    for y, rows in pairs(P.row_spans) do
                        local dest = Q.row_spans[y]; if not dest then dest = {}; Q.row_spans[y] = dest end
                        for _, seg in ipairs(rows) do table.insert(dest, seg) end
                    end
                else
                    R.patches[root] = P
                end
                R.patches[gid] = nil
            end
        end
        -- Emit
        local patches_out = {}
        for gid, P in pairs(R.patches) do
            local tiles = P.tiles
            local cx = (tiles > 0) and (P.sum_x / tiles) or 0
            local cy = (tiles > 0) and (P.sum_y / tiles) or 0
            table.insert(patches_out, {
                patch_id = gid,
                resource_name = name,
                tiles = tiles,
                total_amount = P.amount,
                bbox = { min_x = P.min_x, min_y = P.min_y, max_x = P.max_x, max_y = P.max_y },
                centroid = { x = cx, y = cy },
                row_spans = P.row_spans
            })
        end
        table.insert(out.resources, { name = name, patch_count = #patches_out, patches = patches_out })
    end

    -- 9) Print a brief summary to console and RCON (avoid spamming with full row_spans if huge)
    local summary = { surface = out.surface, resources = {} }
    for _, R in ipairs(out.resources) do
        table.insert(summary.resources, { name = R.name, patch_count = R.patch_count })
    end

    rcon.print(helpers.table_to_json(summary))
    log(helpers.table_to_json(summary))

    -- If you want full output for debugging, uncomment the next line (may be large!)
    -- rcon.print(helpers.table_to_json(out))
end

M.load_helpers = function()
    if remote.interfaces["helpers"] then
        log("Found: " .. helpers.table_to_json(remote.interfaces["helpers"]))
        remote.remove_interface("helpers")
        log("Removed stale 'helpers' interface")
    end
    remote.add_interface("helpers", M.helpers)
    log("Loaded: " .. helpers.table_to_json(remote.interfaces["helpers"]))
    log("Added fresh 'helpers' interface")
end

M.commands.pause = function()
    commands.add_command("pause", "Pause the game", function()
        game.tick_paused = true
    end)
end

M.commands.resume = function()
    commands.add_command("resume", "Resume the game", function()
        game.tick_paused = false
    end)
end

M.commands.set_speed = function()
    commands.add_command("set_speed", "Set the game speed", function(command)
        local success, speed = pcall(tonumber, command.parameter)
        if success then
            game.speed = speed
        else
            game.print("Invalid speed: " .. command.parameter)
        end
    end)
end

M.commands.print_speed = function()
    commands.add_command("print_speed", "Print the game speed", function()
        local print_str = helpers.table_to_json({speed = game.speed})
        triple_print(print_str)
    end)
end

M.commands.is_paused = function()
    commands.add_command("is_paused", "Print if the game is paused", function()
        local print_str = helpers.table_to_json({paused = game.tick_paused})
        triple_print(print_str)
    end)
end

M.commands.reload_scripts = function()
    commands.add_command("reload_scripts", "Reload the scripts", function()
        triple_print("Reloading scripts")
        game.reload_script()
    end)
end

M.commands.remove_biters = function()
    commands.add_command("remove_biters", "Remove biters", function()
        game.forces["enemy"].kill_all_units()
        game.map_settings.enemy_expansion.enabled = false
        game.map_settings.enemy_evolution.enabled = false
        local surface = game.surfaces[1]
        for _, entity in pairs(surface.find_entities_filtered({type="unit-spawner"})) do
            entity.destroy()
        end
    end)
end

M.load_commands = function()
    for name, command in pairs(commands.commands) do
        if command then
            local ok = commands.remove_command(name)
            log("Removed command: " .. name .. " " .. tostring(ok))
        end
    end
    log("Loading commands")
    for name, command in pairs(M.commands) do
        if type(command) == "function" then
            local ok, err = pcall(command)
            if not ok then
                log("Error loading command: " .. name .. " " .. err)
            else
                log("Loaded command: " .. name)
            end
        end
    end
end

return M