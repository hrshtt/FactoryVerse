--- Centralized configuration for factorio_verse mod
local Config = {}

--- Map discovery mode: "preset_only" | "imported_only" | "progressive" | "imported_and_progressive"
--- "preset_only": Force chart large area, no ongoing discovery
--- "imported_only": Minimal charting, no ongoing discovery  
--- "progressive": Initial charting + ongoing agent discovery
--- "imported_and_progressive": Initial charting + ongoing agent discovery
Config.MAP_DISCOVERY_MODE = "preset_only"

-- Auto-configure based on mode
local function get_map_discovery_config()
    if Config.MAP_DISCOVERY_MODE == "preset_only" then
        return {
            initial_radius_chunks = 5,  -- ~150 tiles radius (5 chunks * 32 tiles/chunk)
            agent_vision_radius = 0,      -- No ongoing discovery
            scan_interval_ticks = nil,    -- Disabled
        }
    elseif Config.MAP_DISCOVERY_MODE == "imported_only" then
        return {
            initial_radius_chunks = 0,    -- No additional charting
            agent_vision_radius = 0,      -- No ongoing discovery
            scan_interval_ticks = nil,    -- Disabled
        }
    elseif Config.MAP_DISCOVERY_MODE == "progressive" then
        return {
            initial_radius_chunks = 25,   -- Moderate initial area
            agent_vision_radius = 1,      -- 3x3 around agents
            scan_interval_ticks = 15,     -- Every 15 ticks
        }
    elseif Config.MAP_DISCOVERY_MODE == "imported_and_progressive" then
        return {
            initial_radius_chunks = 0,    -- No additional charting
            agent_vision_radius = 1,      -- 3x3 around agents
            scan_interval_ticks = 15,    -- Every 15 ticks
        }
    else
        -- Fallback to preset_only
        return {
            initial_radius_chunks = 5,
            agent_vision_radius = 0,
            scan_interval_ticks = nil,
        }
    end
end

Config.MAP_DISCOVERY = get_map_discovery_config()

return Config
