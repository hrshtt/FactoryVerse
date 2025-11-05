--- Map discovery system with proper event pattern
local Config = require("core.Config")
local utils = require("core.utils")

local MapDiscovery = {}

-- Get nth_tick handlers for map discovery (follows dispatcher pattern)
function MapDiscovery.get_nth_tick_handlers()
    local scan_interval = Config.MAP_DISCOVERY.scan_interval_ticks
    if not scan_interval then
        return {} -- No ongoing discovery
    end
    
    return {
        [scan_interval] = function(event)
            MapDiscovery.scan_and_discover()
        end
    }
end

-- Initialize discovery for fresh map
function MapDiscovery.initialize(surface, force, center_position)
    local radius = Config.MAP_DISCOVERY.initial_radius_chunks
    if radius <= 0 then return end
    
    local radius_tiles = radius * 32
    local area = {
        { x = center_position.x - radius_tiles, y = center_position.y - radius_tiles },
        { x = center_position.x + radius_tiles, y = center_position.y + radius_tiles }
    }
    force.chart(surface, area)
    
    -- Register charted area for headless server fallback
    local GameStateModule = package.loaded["core.GameState"]
    if GameStateModule then
        local gs = GameStateModule:new()
        gs:map():register_charted_area({
            left_top = { x = area[1].x, y = area[1].y },
            right_bottom = { x = area[2].x, y = area[2].y }
        })
        log(string.format("[MapDiscovery.initialize] Registered initial charted area: (%d to %d, %d to %d)", 
            area[1].x, area[2].x, area[1].y, area[2].y))
    end
    
    -- Don't force generate chunks synchronously - this causes crashes when called from RCON
    -- Chunks will be generated naturally by the engine over time
    -- surface.request_to_generate_chunks(center_position, radius)
    -- surface.force_generate_chunk_requests()
end

-- Scan agents and discover new chunks
function MapDiscovery.scan_and_discover()
    local vision_radius = Config.MAP_DISCOVERY.agent_vision_radius
    if not storage.agent_characters or vision_radius <= 0 then return end
    
    for _, agent in pairs(storage.agent_characters) do
        if agent and agent.valid then
            local chunk_x = math.floor(agent.position.x / 32)
            local chunk_y = math.floor(agent.position.y / 32)
            
            -- Check if charting needed
            local needs_chart = false
            for dx = -vision_radius, vision_radius do
                for dy = -vision_radius, vision_radius do
                    if not agent.force.is_chunk_charted(agent.surface, { x = chunk_x + dx, y = chunk_y + dy }) then
                        needs_chart = true
                        break
                    end
                end
                if needs_chart then break end
            end
            
            if needs_chart then
                local area = {
                    left_top = { x = (chunk_x - vision_radius) * 32, y = (chunk_y - vision_radius) * 32 },
                    right_bottom = { x = (chunk_x + vision_radius + 1) * 32, y = (chunk_y + vision_radius + 1) * 32 }
                }
                agent.force.chart(agent.surface, area)
                
                -- Register charted area for headless server fallback
                local GameStateModule = package.loaded["core.GameState"]
                if GameStateModule then
                    local gs = GameStateModule:new()
                    gs:map():register_charted_area(area)
                    log(string.format("[MapDiscovery.scan_and_discover] Agent moved - registered new charted area around chunk (%d, %d)", 
                        chunk_x, chunk_y))
                end
                
                -- Only chart, don't force generate - let Factorio handle chunk generation naturally
                -- agent.surface.request_to_generate_chunks(agent.position, vision_radius + 1)
                -- agent.surface.force_generate_chunk_requests()
            end
        end
    end
end

--- @class MapGameState
--- @field game_state GameState
local MapGameState = {}
MapGameState.__index = MapGameState

-- MapDiscovery as submodule
MapGameState.MapDiscovery = MapDiscovery

--- @param game_state GameState
--- @return MapGameState
function MapGameState:new(game_state)
    local instance = {
        game_state = game_state
    }
    setmetatable(instance, self)
    return instance
end



--- Register a charted area by converting it to chunk coordinates
--- Called after force.chart() to ensure snapshot works on headless servers
--- @param area table - {left_top = {x, y}, right_bottom = {x, y}}
function MapGameState:register_charted_area(area)
    if not area or not area.left_top or not area.right_bottom then
        return
    end
    
    if not storage.registered_charted_areas then
        storage.registered_charted_areas = {}
    end
    
    -- Convert world coordinates to chunk coordinates
    local min_chunk_x = math.floor(area.left_top.x / 32)
    local min_chunk_y = math.floor(area.left_top.y / 32)
    local max_chunk_x = math.floor(area.right_bottom.x / 32)
    local max_chunk_y = math.floor(area.right_bottom.y / 32)
    
    -- Register each chunk in the area
    for cx = min_chunk_x, max_chunk_x do
        for cy = min_chunk_y, max_chunk_y do
            local chunk_key = utils.chunk_key(cx, cy)
            storage.registered_charted_areas[chunk_key] = { x = cx, y = cy }
        end
    end
end

--- Check if a chunk was registered as charted (fallback for headless servers)
--- @param chunk_x number
--- @param chunk_y number
--- @return boolean
function MapGameState:is_registered_charted(chunk_x, chunk_y)
    if not storage.registered_charted_areas then
        return false
    end
    local chunk_key = utils.chunk_key(chunk_x, chunk_y)
    return storage.registered_charted_areas[chunk_key] ~= nil
end

--- @return LuaForce
function MapGameState:get_player_force()
    return game.forces["player"]
end

function MapGameState:get_visible_chunks(sort_by_distance)
    local surface = game.surfaces[1]
    local force = self:get_player_force()
    local visible_chunks = {}

    if not (surface and force) then
        return visible_chunks
    end

    for chunk in surface.get_chunks() do
        if force.is_chunk_visible(surface, chunk) then
            table.insert(visible_chunks, { x = chunk.x, y = chunk.y, area = chunk.area })
        end
    end

    if sort_by_distance == true then
        utils.sort_coordinates_by_distance(visible_chunks)
    end

    return visible_chunks
end

function MapGameState:get_charted_chunks(sort_by_distance)
    local surface = game.surfaces[1]
    local force = self:get_player_force()
    local charted_chunks = {}
    local generated_count = 0

    if not (surface and force) then
        return charted_chunks
    end

    -- ========================================================================
    -- SOURCE 1: PLAYER-CHARTED CHUNKS (Primary method - most reliable)
    -- ========================================================================
    -- Try to get chunks charted by LuaPlayer characters via force.is_chunk_charted()
    -- This works reliably on:
    --   - Saves where players have explored the map
    --   - Any server with connected LuaPlayer characters
    -- This does NOT work reliably on:
    --   - Headless servers with no connected players (known Factorio limitation)
    --   - force.chart() called but is_chunk_charted() still returns false
    for chunk in surface.get_chunks() do
        generated_count = generated_count + 1
        if force.is_chunk_charted(surface, chunk) then
            table.insert(charted_chunks, { x = chunk.x, y = chunk.y, area = chunk.area })
        end
    end

    -- ========================================================================
    -- SOURCE 2: AGENT-TRACKED CHUNKS (Fallback - headless servers)
    -- ========================================================================
    -- If is_chunk_charted() returned empty, fall back to manually registered areas
    -- This is populated by:
    --   - MapDiscovery:scan_and_discover() (on agent movement)
    --   - MapDiscovery.initialize() (on initial setup)
    -- We explicitly call gs:register_charted_area() because LuaEntity agents
    -- don't auto-chart chunks like LuaPlayer does
    if #charted_chunks == 0 and storage.registered_charted_areas then
        for _, chunk_data in pairs(storage.registered_charted_areas) do
            if chunk_data then
                -- Reconstruct area for registered chunk
                local area = {
                    left_top = { x = chunk_data.x * 32, y = chunk_data.y * 32 },
                    right_bottom = { x = (chunk_data.x + 1) * 32, y = (chunk_data.y + 1) * 32 }
                }
                table.insert(charted_chunks, { x = chunk_data.x, y = chunk_data.y, area = area })
            end
        end
    end

    if sort_by_distance == true then
        utils.sort_coordinates_by_distance(charted_chunks)
    end

    return charted_chunks
end

-- ============================================================================
-- CHUNK PRIMITIVES & UTILITIES
-- ============================================================================

--- Create a chunk object with area from chunk coordinates
--- @param chunk_x number - chunk x coordinate
--- @param chunk_y number - chunk y coordinate
--- @return table - {x = chunk_x, y = chunk_y, area = {left_top = {...}, right_bottom = {...}}}
function MapGameState:create_chunk(chunk_x, chunk_y)
    return {
        x = chunk_x,
        y = chunk_y,
        area = {
            left_top = { x = chunk_x * 32, y = chunk_y * 32 },
            right_bottom = { x = (chunk_x + 1) * 32, y = (chunk_y + 1) * 32 }
        }
    }
end

--- Convert world position to chunk coordinates
--- @param position table - {x, y} world position
--- @return number, number - chunk_x, chunk_y
function MapGameState:position_to_chunk(position)
    local chunk_x = math.floor(position.x / 32)
    local chunk_y = math.floor(position.y / 32)
    return chunk_x, chunk_y
end

--- Get area for chunk coordinates
--- @param chunk_x number
--- @param chunk_y number
--- @return table - {left_top = {x, y}, right_bottom = {x, y}}
function MapGameState:get_chunk_area(chunk_x, chunk_y)
    return {
        left_top = { x = chunk_x * 32, y = chunk_y * 32 },
        right_bottom = { x = (chunk_x + 1) * 32, y = (chunk_y + 1) * 32 }
    }
end

--- Get chunks that an entity's bounding box intersects (for multi-chunk entities)
--- @param entity LuaEntity - the entity
--- @return table - array of {x, y} chunk coordinates
function MapGameState:get_entity_chunks(entity)
    local chunks = {}
    local position = entity.position
    if not position then return chunks end

    local center_chunk_x, center_chunk_y = self:position_to_chunk(position)
    table.insert(chunks, { x = center_chunk_x, y = center_chunk_y })

    local bb = entity.bounding_box
    if bb and bb.left_top and bb.right_bottom then
        local min_cx = math.floor(bb.left_top.x / 32)
        local min_cy = math.floor(bb.left_top.y / 32)
        local max_cx = math.floor(bb.right_bottom.x / 32)
        local max_cy = math.floor(bb.right_bottom.y / 32)

        for cx = min_cx, max_cx do
            for cy = min_cy, max_cy do
                if not (cx == center_chunk_x and cy == center_chunk_y) then
                    table.insert(chunks, { x = cx, y = cy })
                end
            end
        end
    end

    return chunks
end

-- ============================================================================
-- SPATIAL/MAP QUERIES
-- ============================================================================

--- Get all resource entities in a chunk
--- @param chunk table - {x, y, area}
--- @return table - entities grouped by resource name {resource_name = {entity1, entity2, ...}}
function MapGameState:get_resources_in_chunk(chunk)
    local surface = game.surfaces[1]
    if not surface then return {} end

    local resources_by_name = {}
    local entities = surface.find_entities_filtered {
        area = chunk.area,
        type = "resource"
    }

    for _, entity in ipairs(entities) do
        local name = entity.name
        if not resources_by_name[name] then
            resources_by_name[name] = {}
        end
        table.insert(resources_by_name[name], entity)
    end

    return resources_by_name
end

--- Get water tiles in a chunk using prototype detection for mod compatibility
--- @param chunk table - {x, y, area}
--- @return table - {tiles = {...}, tile_names = {...}}
function MapGameState:get_water_tiles_in_chunk(chunk)
    local surface = game.surfaces[1]
    if not surface then return { tiles = {}, tile_names = {} } end

    -- Detect water tile names via prototypes for mod compatibility
    local water_tile_names = {}
    local ok_proto, tiles_or_err = pcall(function()
        return prototypes.get_tile_filtered({ { filter = "collision-mask", mask = "water-tile" } })
    end)

    if ok_proto and tiles_or_err then
        for _, t in pairs(tiles_or_err) do
            table.insert(water_tile_names, t.name)
        end
    else
        -- fallback to vanilla names
        water_tile_names = { "water", "deepwater", "water-green", "deepwater-green" }
    end

    local tiles = surface.find_tiles_filtered {
        area = chunk.area,
        name = water_tile_names
    }

    return {
        tiles = tiles,
        tile_names = water_tile_names
    }
end

--- Find rock entities in a chunk
--- @param chunk table - {x, y, area}
--- @return table - array of rock entities
function MapGameState:find_rocks_in_chunk(chunk)
    local surface = game.surfaces[1]
    if not surface then return {} end

    local rock_entities = surface.find_entities_filtered({ area = chunk.area, type = "simple-entity" })
    local rocks = {}
    for _, entity in ipairs(rock_entities) do
        if entity.name and (entity.name:match("rock") or entity.name:match("stone")) then
            table.insert(rocks, entity)
        end
    end
    return rocks
end

--- Find tree entities in a chunk
--- @param chunk table - {x, y, area}
--- @return table - array of tree entities
function MapGameState:find_trees_in_chunk(chunk)
    local surface = game.surfaces[1]
    if not surface then return {} end

    return surface.find_entities_filtered({ area = chunk.area, type = "tree" })
end

-- ============================================================================
-- CHUNK-LEVEL ENTITY WRAPPERS
-- ============================================================================

--- Gather all entities for a specific chunk (wrapper around EntitiesGameState)
--- @param chunk table - {x, y, area}
--- @param options table - {component_filter = nil|"entities"|"belts"|"pipes"|"poles"}
--- @return table - {entities = {...}, belts = {...}, pipes = {...}, poles = {...}}
function MapGameState:gather_entities_for_chunk(chunk, options)
    options = options or {}
    local entities_state = self.game_state:entities()
    local surface = game.surfaces[1]
    if not surface then return { entities = {}, belts = {}, pipes = {}, poles = {} } end

    local force = self.game_state:get_player_force()
    if not force then return { entities = {}, belts = {}, pipes = {}, poles = {} } end

    local allowed_types = entities_state:get_allowed_entity_types()
    local filter = { area = chunk.area, force = force, type = allowed_types }
    local entities_raw = surface.find_entities_filtered(filter)

    local categorized = { entities = {}, belts = {}, pipes = {}, poles = {} }

    for _, entity in ipairs(entities_raw) do
        if entity and entity.valid then
            -- Filter rocks
            if entity.type == "simple-entity" and (entity.name == "rock-huge" or entity.name == "rock-big" or entity.name == "sand-rock-big") then
                goto continue
            end

            local component_type = entities_state:determine_component_type(entity.type, entity.name)

            -- Apply component filter if specified
            if not options.component_filter or options.component_filter == component_type then
                local serialized = entities_state:serialize_entity(entity, options)
                if serialized then
                    table.insert(categorized[component_type], serialized)
                end
            end
        end
        ::continue::
    end

    return categorized
end

--- Get status view for entities in a chunk
--- Status records use position instead of unit_number
--- @param chunk table - {x, y, area}
--- @return table - array of {position_x, position_y, entity_name, status, status_name, health, tick}
function MapGameState:get_status_view_for_chunk(chunk)
    local entities_state = self.game_state:entities()
    local surface = game.surfaces[1]
    if not surface then return {} end

    local force = self.game_state:get_player_force()
    if not force then return {} end

    local allowed_types = entities_state:get_allowed_entity_types()
    local filter = { area = chunk.area, force = force, type = allowed_types }
    local entities = surface.find_entities_filtered(filter)
    
    local status_records = {}
    for _, entity in ipairs(entities) do
        if entity and entity.valid then
            -- Filter rocks
            if entity.type == "simple-entity" then
                local n = entity.name
                if n == "rock-huge" or n == "rock-big" or n == "sand-rock-big" then
                    goto continue
                end
            end

            table.insert(status_records, {
                position_x = entity.position.x,
                position_y = entity.position.y,
                entity_name = entity.name,
                status = entity.status or 0,
                status_name = utils.status_to_name(entity.status),
                health = entity.health or 0,
                tick = game.tick or 0
            })
        end
        ::continue::
    end

    return status_records
end

-- ============================================================================
-- CHUNK-LEVEL RESOURCE WRAPPERS
-- ============================================================================

--- Gather all resources for a specific chunk (wrapper around ResourceGameState)
--- @param chunk table - {x, y, area}
--- @return table - {resources = {...}, rocks = {...}, trees = {...}, water = {...}}
function MapGameState:gather_resources_for_chunk(chunk)
    local resource_state = self.game_state:resource_state()

    local gathered = {
        resources = {}, -- Mineable resources (iron, copper, coal, crude-oil, etc.)
        rocks = {},     -- Simple entities (rock-huge, rock-big, etc.)
        trees = {},     -- Tree entities
        water = {}      -- Water tiles
    }

    -- Resources (including crude oil)
    local resources_in_chunk = self:get_resources_in_chunk(chunk)
    for resource_name, entities in pairs(resources_in_chunk) do
        for _, entity in ipairs(entities) do
            table.insert(gathered.resources, resource_state:serialize_resource_tile(entity, resource_name))
        end
    end

    -- Rocks
    local rock_entities = self:find_rocks_in_chunk(chunk)
    for _, entity in ipairs(rock_entities) do
        table.insert(gathered.rocks, resource_state:serialize_rock(entity, chunk))
    end

    -- Trees
    local tree_entities = self:find_trees_in_chunk(chunk)
    for _, entity in ipairs(tree_entities) do
        table.insert(gathered.trees, resource_state:serialize_tree(entity, chunk))
    end

    -- Water
    local water_data = self:get_water_tiles_in_chunk(chunk)
    if water_data and water_data.tiles then
        for _, tile in ipairs(water_data.tiles) do
            local x, y = utils.extract_position(tile)
            if x and y then
                table.insert(gathered.water, { kind = "water", x = x, y = y, amount = 0 })
            end
        end
    end

    return gathered
end

return MapGameState
