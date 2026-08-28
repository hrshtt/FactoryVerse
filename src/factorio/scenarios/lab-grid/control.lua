-- ============================================================================
-- LAB GRID SCENARIO - Control Script
-- ============================================================================
-- A scenario with an N×N grid of isolated play areas for parallel multi-agent
-- evaluation. Each cell is a self-contained lab environment where one agent
-- runs independently.
--
-- Key features:
--   - 8×8 grid = 64 isolated cells
--   - 128×128 tile play area per cell (4×4 chunks)
--   - 32 tile gap between cells (1 chunk)
--   - Force-per-cell for production statistics isolation
--   - Build restriction enforcement
--   - Cell reset capability
-- ============================================================================

local grid = require("grid")
local cell = require("cell")

-- ============================================================================
-- STORAGE INITIALIZATION
-- ============================================================================

--- Initialize storage tables
local function init_storage()
    storage.lab_grid = storage.lab_grid or {}
    storage.lab_grid.agent_cells = storage.lab_grid.agent_cells or {}  -- agent_id -> cell_index
    storage.lab_grid.cell_agents = storage.lab_grid.cell_agents or {}  -- cell_index -> agent_id
    storage.lab_grid.cell_forces = storage.lab_grid.cell_forces or {}  -- cell_index -> force_name
    storage.lab_grid.initialized = storage.lab_grid.initialized or false
end

-- ============================================================================
-- FORCE MANAGEMENT
-- ============================================================================

--- Create a force for a cell
--- @param cell_index number
--- @return LuaForce
local function create_cell_force(cell_index)
    local force_name = "cell_" .. cell_index
    local force = game.forces[force_name]

    if not force then
        force = game.create_force(force_name)

        -- Set friendly with player force (for compatibility)
        local player_force = game.forces.player
        force.set_friend(player_force, true)
        player_force.set_friend(force, true)

        -- Set friendly with all existing cell forces
        for existing_index, existing_force_name in pairs(storage.lab_grid.cell_forces) do
            local existing_force = game.forces[existing_force_name]
            if existing_force then
                force.set_friend(existing_force, true)
                existing_force.set_friend(force, true)
            end
        end

        -- Enable all technologies and recipes for this force
        force.enable_all_technologies()
        force.enable_all_recipes()

        storage.lab_grid.cell_forces[cell_index] = force_name
    end

    return force
end

--- Get or create force for a cell
--- @param cell_index number
--- @return LuaForce
local function get_cell_force(cell_index)
    local force_name = storage.lab_grid.cell_forces[cell_index]
    if force_name and game.forces[force_name] then
        return game.forces[force_name]
    end
    return create_cell_force(cell_index)
end

-- ============================================================================
-- AGENT-CELL BINDING
-- ============================================================================

--- Find an empty cell (no agent assigned)
--- @return number|nil cell_index or nil if all full
local function find_empty_cell()
    for cell_index = 0, grid.TOTAL_CELLS - 1 do
        if not storage.lab_grid.cell_agents[cell_index] then
            return cell_index
        end
    end
    return nil
end

--- Assign an agent to a specific cell
--- @param agent_id number
--- @param cell_index number
--- @return boolean success
local function assign_agent_to_cell(agent_id, cell_index)
    -- Check if cell is already occupied
    if storage.lab_grid.cell_agents[cell_index] then
        return false
    end

    -- Check if agent is already assigned elsewhere
    if storage.lab_grid.agent_cells[agent_id] then
        -- Unassign from previous cell
        local old_cell = storage.lab_grid.agent_cells[agent_id]
        storage.lab_grid.cell_agents[old_cell] = nil
    end

    -- Assign to new cell
    storage.lab_grid.agent_cells[agent_id] = cell_index
    storage.lab_grid.cell_agents[cell_index] = agent_id

    return true
end

--- Get the cell assigned to an agent
--- @param agent_id number
--- @return number|nil cell_index
local function get_agent_cell(agent_id)
    return storage.lab_grid.agent_cells[agent_id]
end

--- Unassign an agent from their cell
--- @param agent_id number
local function unassign_agent(agent_id)
    local cell_index = storage.lab_grid.agent_cells[agent_id]
    if cell_index then
        storage.lab_grid.cell_agents[cell_index] = nil
        storage.lab_grid.agent_cells[agent_id] = nil
    end
end

-- ============================================================================
-- AGENT CREATION IN CELL
-- ============================================================================

--- Create an agent in a specific cell (integrates with fv_embodied_agent)
--- @param args table {cell_index: number|nil, starting_inventory: table|nil}
--- @return table Result with agent_id, cell_index, spawn_position
local function create_agent_in_cell(args)
    args = args or {}

    -- Find cell to use
    local cell_index = args.cell_index
    if cell_index == nil then
        cell_index = find_empty_cell()
    end

    if cell_index == nil then
        return {success = false, error = "No empty cells available"}
    end

    if cell_index < 0 or cell_index >= grid.TOTAL_CELLS then
        return {success = false, error = "Invalid cell index: " .. tostring(cell_index)}
    end

    -- Check if cell is occupied
    if storage.lab_grid.cell_agents[cell_index] then
        return {success = false, error = "Cell " .. cell_index .. " is already occupied"}
    end

    -- Get or create force for this cell
    local force = get_cell_force(cell_index)
    local spawn_pos = grid.get_spawn_position(cell_index)

    -- Call fv_embodied_agent to create the agent
    if not remote.interfaces.agent or not remote.interfaces.agent.create_agent then
        return {success = false, error = "fv_embodied_agent mod not loaded"}
    end

    -- Create agent with cell's force
    -- API: create_agent(udp_port, set_unique_forces, default_common_force, initial_inventory)
    local result = remote.call("agent", "create_agent",
        nil,                        -- udp_port (use default)
        false,                      -- set_unique_forces (use shared force)
        force.name,                 -- default_common_force (cell's force)
        args.starting_inventory     -- initial_inventory
    )

    if not result or not result.agent_id then
        return {success = false, error = "Failed to create agent"}
    end

    local agent_id = result.agent_id

    -- Teleport agent to cell spawn position
    local agent_interface = "agent_" .. agent_id
    if remote.interfaces[agent_interface] and remote.interfaces[agent_interface].teleport then
        remote.call(agent_interface, "teleport", {position = spawn_pos})
    end

    -- Bind agent to cell
    assign_agent_to_cell(agent_id, cell_index)

    -- Chart just this cell for the force (on-demand, not bulk)
    -- In SELECTIVE mode, charting does NOT trigger auto-snapshotting
    local cell_bounds = grid.get_play_area_bounds(cell_index)
    force.chart(game.surfaces[1], cell_bounds)

    -- Explicitly trigger a FRESH snapshot for this cell after all setup is
    -- complete. re_snapshot_area, not snapshot_area: chunks already
    -- snapshotted earlier in the session would otherwise be silently skipped
    -- and the session DB would never see this cell's configured state
    -- (SNAP-1b, frozen snapshot tick in the 2026-06-10 field run).
    if remote.interfaces.map and remote.interfaces.map.re_snapshot_area then
        local snapshot_result = remote.call("map", "re_snapshot_area", cell_bounds)
        if snapshot_result and snapshot_result.success then
            game.print(string.format("Lab Grid: Triggered fresh snapshot for cell %d (%d chunks)",
                cell_index, snapshot_result.chunks_queued or 0))
        end
    end

    return {
        success = true,
        agent_id = agent_id,
        cell_index = cell_index,
        spawn_position = spawn_pos,
        force_name = force.name
    }
end

-- ============================================================================
-- BUILD RESTRICTION ENFORCEMENT
-- ============================================================================

--- Check if an entity placement is valid (within agent's cell)
--- @param entity LuaEntity
--- @return boolean is_valid
local function is_valid_placement(entity)
    if not entity or not entity.valid then
        return false
    end

    -- Get the force and find the agent/cell
    local force_name = entity.force.name

    -- If it's a cell force, check bounds
    local cell_match = force_name:match("^cell_(%d+)$")
    if cell_match then
        local cell_index = tonumber(cell_match)
        return grid.is_in_play_area(entity.position, cell_index)
    end

    -- Player force entities are allowed anywhere (for debugging/admin)
    if force_name == "player" then
        return true
    end

    -- Other forces: check if there's an agent binding
    -- This handles cases where agents use custom force names
    for agent_id, cell_index in pairs(storage.lab_grid.agent_cells) do
        -- Check if entity belongs to this cell's force
        local cell_force_name = storage.lab_grid.cell_forces[cell_index]
        if cell_force_name == force_name then
            return grid.is_in_play_area(entity.position, cell_index)
        end
    end

    -- Unknown force - allow (might be admin/debug)
    return true
end

--- Handle entity built event - enforce cell bounds
--- @param event table
local function on_built_entity(event)
    local entity = event.entity
    if not entity or not entity.valid then
        return
    end

    -- Skip certain entity types that shouldn't be restricted
    if entity.type == "character" or entity.type == "item-on-ground" then
        return
    end

    if not is_valid_placement(entity) then
        -- Get items to return
        local products = entity.prototype.mineable_properties
        local items_to_return = {}
        if products and products.products then
            for _, product in pairs(products.products) do
                if product.name then
                    items_to_return[product.name] = (items_to_return[product.name] or 0) + (product.amount or 1)
                end
            end
        end

        -- Destroy the entity
        entity.destroy()

        -- Note: Items would need to be returned to agent inventory via remote call
        -- For now, just log the violation
        game.print("[Lab Grid] Build rejected: entity placed outside assigned cell bounds")
    end
end

-- ============================================================================
-- MAP GENERATION (Performant approach)
-- ============================================================================
-- Key technique: Use set_chunk_generated_status to prevent Factorio from
-- running default terrain generation. Then place tiles directly.
--
-- IMPORTANT: Some chunks around spawn are generated BEFORE on_init runs.
-- We must:
-- 1. Clear pre-generated entities
-- 2. Overwrite pre-generated tiles
-- 3. Use on_chunk_generated as fallback for any late chunks
-- ============================================================================

--- Clear all pre-generated content (entities and tiles) from areas outside our grid
--- @param surface LuaSurface
local function clear_pregenerated_content(surface)
    -- Search a wide area for pre-generated entities (spawn area can be large)
    local search_area = {
        left_top = {x = -512, y = -512},
        right_bottom = {x = grid.MAP_SIZE + 512, y = grid.MAP_SIZE + 512}
    }

    -- Clear entities
    local entities = surface.find_entities(search_area)
    local cleared = 0
    for _, entity in pairs(entities) do
        if entity.valid and entity.type ~= "character" then
            entity.destroy()
            cleared = cleared + 1
        end
    end
    if cleared > 0 then
        game.print("Lab Grid: Cleared " .. cleared .. " pre-generated entities")
    end

    -- Clear tiles in negative coordinate area (pre-generated spawn chunks)
    -- These are outside our grid but may have been generated before on_init
    local negative_tiles = {}
    for y = -256, -1 do
        for x = -256, grid.MAP_SIZE + 255 do
            table.insert(negative_tiles, {name = "out-of-map", position = {x, y}})
        end
    end
    for y = 0, grid.MAP_SIZE + 255 do
        for x = -256, -1 do
            table.insert(negative_tiles, {name = "out-of-map", position = {x, y}})
        end
    end

    if #negative_tiles > 0 then
        surface.set_tiles(negative_tiles, false)
        game.print("Lab Grid: Cleared " .. #negative_tiles .. " pre-generated tiles outside grid")
    end
end

--- Generate all map tiles directly
--- Sets dirt-1 for play areas and out-of-map for gaps
--- Works by iterating through all chunks and setting tiles
--- @param surface LuaSurface
local function generate_all_tiles(surface)
    local chunk_count = math.ceil(grid.MAP_SIZE / grid.CHUNK_SIZE)
    local chunks_processed = 0

    -- Process each chunk and set its tiles
    for chunk_y = 0, chunk_count - 1 do
        for chunk_x = 0, chunk_count - 1 do
            local tiles = {}
            local base_x = chunk_x * grid.CHUNK_SIZE
            local base_y = chunk_y * grid.CHUNK_SIZE

            for y = base_y, base_y + grid.CHUNK_SIZE - 1 do
                for x = base_x, base_x + grid.CHUNK_SIZE - 1 do
                    if x < grid.MAP_SIZE and y < grid.MAP_SIZE then
                        local local_x = x % grid.CELL_SIZE
                        local local_y = y % grid.CELL_SIZE
                        local in_play_area = local_x < grid.PLAY_AREA_SIZE and local_y < grid.PLAY_AREA_SIZE

                        if in_play_area then
                            table.insert(tiles, {name = "dirt-1", position = {x, y}})
                        else
                            table.insert(tiles, {name = "out-of-map", position = {x, y}})
                        end
                    end
                end
            end

            if #tiles > 0 then
                -- set_tiles creates chunks if they don't exist
                surface.set_tiles(tiles, false)
            end

            -- Mark the chunk fully generated: the pathfinder refuses to path
            -- through chunks without generated status, so without this EVERY
            -- walk_to fails map-wide (PATH-1 — the comment block above always
            -- promised this call; it never existed).
            surface.set_chunk_generated_status(
                {x = chunk_x, y = chunk_y},
                defines.chunk_generated_status.entities
            )

            chunks_processed = chunks_processed + 1
        end

        -- Progress update every row
        if chunk_y % 10 == 0 then
            game.print("Lab Grid: Generated row " .. chunk_y .. "/" .. chunk_count)
        end
    end

    return chunks_processed
end

--- Fallback handler for any chunks generated after initialization
--- @param event table
local function on_chunk_generated(event)
    local surface = event.surface
    local area = event.area

    -- Clear any auto-generated entities
    local entities = surface.find_entities(area)
    for _, entity in pairs(entities) do
        if entity.valid and entity.type ~= "character" then
            entity.destroy()
        end
    end

    -- After initialize_map, in-grid chunks already have their full cell layout
    -- (tiles + water + resources). Late engine generation of such a chunk must
    -- be replaced with that layout — the bare dirt-1 rewrite below left the
    -- spawn-origin cell barren (SNAP-1a, 2026-06-10 field run).
    if storage.lab_grid.initialized then
        cell.restore_chunk_content(surface, area)
        return
    end

    -- Generate correct tiles for this chunk
    local tiles = {}
    for y = area.left_top.y, area.right_bottom.y - 1 do
        for x = area.left_top.x, area.right_bottom.x - 1 do
            -- Outside our map bounds?
            if x < 0 or x >= grid.MAP_SIZE or y < 0 or y >= grid.MAP_SIZE then
                table.insert(tiles, {name = "out-of-map", position = {x, y}})
            else
                -- Inside map - determine if play area or gap
                local local_x = x % grid.CELL_SIZE
                local local_y = y % grid.CELL_SIZE
                local in_play_area = local_x < grid.PLAY_AREA_SIZE and local_y < grid.PLAY_AREA_SIZE

                if in_play_area then
                    table.insert(tiles, {name = "dirt-1", position = {x, y}})
                else
                    table.insert(tiles, {name = "out-of-map", position = {x, y}})
                end
            end
        end
    end

    if #tiles > 0 then
        surface.set_tiles(tiles, false)
    end
end

--- Initialize the full map grid
local function initialize_map()
    local surface = game.surfaces[1]

    game.print("Lab Grid: Configuring map generation...")

    -- Step 1: Configure map generation settings to limit map size and disable autoplacement
    local map_settings = surface.map_gen_settings
    map_settings.width = grid.MAP_SIZE
    map_settings.height = grid.MAP_SIZE
    map_settings.starting_area = 0
    map_settings.peaceful_mode = true
    map_settings.autoplace_controls = {}
    map_settings.default_enable_all_autoplace_controls = false
    surface.map_gen_settings = map_settings

    -- Step 2: Clear any content that was pre-generated before on_init
    game.print("Lab Grid: Clearing pre-generated content...")
    clear_pregenerated_content(surface)

    -- Step 3: Generate all tiles for the entire map
    -- This overwrites any pre-generated terrain with lab tiles and gaps
    game.print("Lab Grid: Generating tiles for " .. math.ceil(grid.MAP_SIZE / grid.CHUNK_SIZE)^2 .. " chunks...")
    local chunks = generate_all_tiles(surface)
    game.print("Lab Grid: Generated " .. chunks .. " chunks")

    -- Step 4: Spawn resources in each cell
    game.print("Lab Grid: Spawning resources in " .. grid.TOTAL_CELLS .. " cells...")
    for cell_index = 0, grid.TOTAL_CELLS - 1 do
        cell.spawn_resources(surface, cell_index)
    end

    -- Step 5: Set always day for visibility
    surface.always_day = true

    -- NOTE: We do NOT chart the entire map here.
    -- Charting triggers on_chunk_charted events which fv_snapshot processes.
    -- Charting 1600 chunks at once causes the system to hang.
    -- Instead, cells are charted on-demand when agents are created.

    -- Step 6: Set snapshot orchestration mode to SELECTIVE
    -- This prevents auto-snapshotting on chunk charted events.
    -- We explicitly trigger snapshots per-cell via snapshot_area() after setup.
    if remote.interfaces.map and remote.interfaces.map.set_orchestration_mode then
        local result = remote.call("map", "set_orchestration_mode", "SELECTIVE")
        if result and result.success then
            game.print("Lab Grid: Snapshot orchestration mode set to SELECTIVE")
        else
            game.print("Lab Grid: Warning - Failed to set orchestration mode: " .. (result and result.error or "unknown"))
        end
    else
        game.print("Lab Grid: Warning - fv_snapshot map interface not available for orchestration mode")
    end

    storage.lab_grid.initialized = true
    game.print("Lab Grid initialized: " .. grid.GRID_SIZE .. "x" .. grid.GRID_SIZE ..
               " grid (" .. grid.TOTAL_CELLS .. " cells), " ..
               grid.MAP_SIZE .. "x" .. grid.MAP_SIZE .. " tiles")
end

-- ============================================================================
-- REMOTE INTERFACE
-- ============================================================================

-- Clean up existing interface if it exists (for hot-reload support)
if remote.interfaces["lab_grid"] then
    remote.remove_interface("lab_grid")
end

remote.add_interface("lab_grid", {
    -- Grid configuration
    get_config = function()
        return grid.get_config()
    end,

    -- Cell management
    get_cell_bounds = function(cell_index)
        return grid.get_play_area_bounds(cell_index)
    end,

    get_cell_status = function(cell_index)
        return cell.get_cell_status(cell_index)
    end,

    get_all_cell_status = function()
        local statuses = {}
        for i = 0, grid.TOTAL_CELLS - 1 do
            statuses[i] = cell.get_cell_status(i)
        end
        return statuses
    end,

    reset_cell = function(cell_index, preserve_agent)
        local surface = game.surfaces[1]
        cell.reset_cell(surface, cell_index, preserve_agent)

        -- Clear cell-agent assignment if not preserving agent
        if not preserve_agent then
            local agent_id = storage.lab_grid.cell_agents[cell_index]
            if agent_id then
                storage.lab_grid.agent_cells[agent_id] = nil
                storage.lab_grid.cell_agents[cell_index] = nil
            end
        end

        -- Trigger re-snapshot for this cell after reset
        -- This clears old snapshot data and captures the fresh cell state
        local cell_bounds = grid.get_play_area_bounds(cell_index)
        if remote.interfaces.map and remote.interfaces.map.re_snapshot_area then
            local snapshot_result = remote.call("map", "re_snapshot_area", cell_bounds)
            if snapshot_result and snapshot_result.success then
                game.print(string.format("Lab Grid: Re-snapshotting cell %d (%d chunks)",
                    cell_index, snapshot_result.chunks_queued or 0))
            end
        end

        -- Reset force production statistics
        local force_name = storage.lab_grid.cell_forces[cell_index]
        if force_name and game.forces[force_name] then
            -- Factorio doesn't have a direct reset method, but stats will be
            -- accurate since we cleared all entities
        end

        return {success = true, cell_index = cell_index}
    end,

    reset_all_cells = function(preserve_agents)
        local surface = game.surfaces[1]
        cell.reset_all_cells(surface, preserve_agents)
        return {success = true, cells_reset = grid.TOTAL_CELLS}
    end,

    -- Agent-cell operations
    create_agent_in_cell = create_agent_in_cell,

    get_agent_cell = function(agent_id)
        return get_agent_cell(agent_id)
    end,

    assign_agent_to_cell = function(agent_id, cell_index)
        return assign_agent_to_cell(agent_id, cell_index)
    end,

    unassign_agent = function(agent_id)
        unassign_agent(agent_id)
        return {success = true}
    end,

    find_empty_cell = function()
        return find_empty_cell()
    end,

    -- Force management
    get_cell_force = function(cell_index)
        local force = get_cell_force(cell_index)
        return force.name
    end,

    -- Position utilities
    get_spawn_position = function(cell_index)
        return grid.get_spawn_position(cell_index)
    end,

    is_in_play_area = function(position, cell_index)
        return grid.is_in_play_area(position, cell_index)
    end,

    get_cell_at_position = function(position)
        return grid.get_cell_at_position(position)
    end,

    -- Teleport agent to cell center
    teleport_agent_to_cell = function(agent_id)
        local cell_index = get_agent_cell(agent_id)
        if not cell_index then
            return {success = false, error = "Agent not assigned to a cell"}
        end

        -- Get agent character via fv_embodied_agent (per-agent interface is agent_N)
        local agent_interface = "agent_" .. agent_id
        if remote.interfaces[agent_interface] and remote.interfaces[agent_interface].teleport then
            local spawn_pos = grid.get_spawn_position(cell_index)
            remote.call(agent_interface, "teleport", {position = spawn_pos})
            return {success = true, position = spawn_pos}
        end

        return {success = false, error = "Cannot teleport - agent interface " .. agent_interface .. " not available"}
    end,

    -- Debugging
    get_storage = function()
        return storage.lab_grid
    end,
})

-- ============================================================================
-- EVENT HANDLERS
-- ============================================================================

script.on_init(function()
    game.print("Lab Grid Scenario Initializing...")
    init_storage()
    initialize_map()
end)

script.on_load(function()
    -- Ensure storage is initialized on load
    if not storage.lab_grid then
        init_storage()
    end
end)

script.on_configuration_changed(function()
    game.print("Lab Grid Scenario Configuration Changed")
    init_storage()
    if not storage.lab_grid.initialized then
        initialize_map()
    end
end)

-- Fallback handler for any chunks that slip through or generate late
script.on_event(defines.events.on_chunk_generated, on_chunk_generated)

-- Build restriction enforcement
script.on_event(defines.events.on_built_entity, on_built_entity)
script.on_event(defines.events.script_raised_built, on_built_entity)
script.on_event(defines.events.on_robot_built_entity, on_built_entity)

-- Joining humans are made non-embodied observers by fv_embodied_agent
-- (setting fv-observer-spectator). The scenario does not set a controller.
