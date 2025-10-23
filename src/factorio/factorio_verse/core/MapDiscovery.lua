--- Map discovery system with proper event pattern
local Config = require("core.Config")

local MapDiscovery = {}

-- Get events for map discovery (follows snapshot/action pattern)
function MapDiscovery.get_events()
    local scan_interval = Config.MAP_DISCOVERY.scan_interval_ticks
    if not scan_interval then
        return nil -- No ongoing discovery
    end
    
    return {
        tick_interval = scan_interval,
        handler = function(event)
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
    local GameStateModule = package.loaded["core.game_state.GameState"]
    if GameStateModule then
        local gs = GameStateModule:new()
        gs:register_charted_area({
            left_top = { x = area[1].x, y = area[1].y },
            right_bottom = { x = area[2].x, y = area[2].y }
        })
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
                local GameStateModule = package.loaded["core.game_state.GameState"]
                if GameStateModule then
                    local gs = GameStateModule:new()
                    gs:register_charted_area(area)
                end
                
                -- Only chart, don't force generate - let Factorio handle chunk generation naturally
                -- agent.surface.request_to_generate_chunks(agent.position, vision_radius + 1)
                -- agent.surface.force_generate_chunk_requests()
            end
        end
    end
end

return MapDiscovery
