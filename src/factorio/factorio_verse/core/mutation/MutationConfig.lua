--- MutationConfig.lua
--- Configuration management for mutation logging system
--- Provides easy setup and configuration from control.lua

local MutationLogger = require("core.mutation.MutationLogger")
local TickMutationLogger = require("core.mutation.TickMutationLogger")

--- @class MutationConfig
local MutationConfig = {}

--- Default configuration profiles
local PROFILES = {
    -- Minimal logging - only action-based mutations
    minimal = {
        enabled = true,
        log_actions = true,
        log_tick_events = false,
        debug = false
    },
    
    -- Full logging - both action and tick-based mutations  
    full = {
        enabled = true,
        log_actions = true,
        log_tick_events = true,
        debug = false
    },
    
    -- Debug mode - all logging with debug output
    debug = {
        enabled = true,
        log_actions = true,
        log_tick_events = true,
        debug = true
    },
    
    -- Disabled - no mutation logging
    disabled = {
        enabled = false,
        log_actions = false,
        log_tick_events = false,
        debug = false
    }
}

--- Initialize mutation logging with a configuration profile or custom config
--- @param profile_or_config string|table Profile name or custom configuration table
--- @param tick_interval number|nil Tick interval for autonomous logging (default: 60)
function MutationConfig.setup(profile_or_config, tick_interval)
    local config
    
    if type(profile_or_config) == "string" then
        -- Use predefined profile
        config = PROFILES[profile_or_config]
        if not config then
            error("Unknown mutation logging profile: " .. tostring(profile_or_config))
        end
        log("[MutationConfig] Using profile: " .. profile_or_config)
    elseif type(profile_or_config) == "table" then
        -- Use custom configuration
        config = profile_or_config
        log("[MutationConfig] Using custom configuration")
    else
        -- Default to minimal profile
        config = PROFILES.minimal
        log("[MutationConfig] Using default minimal profile")
    end
    
    -- Configure the mutation logger
    MutationLogger.configure(config)
    
    -- Set up tick-based logging if enabled
    if config.log_tick_events then
        local tick_logger = TickMutationLogger:new(tick_interval)
        tick_logger:register_events()
        log("[MutationConfig] Registered tick-based mutation logging (interval: " .. 
            tostring(tick_interval or 60) .. ")")
    end
    
    log("[MutationConfig] Mutation logging configured - enabled: " .. tostring(config.enabled))
end

--- Get available configuration profiles
--- @return table List of available profile names
function MutationConfig.get_profiles()
    local profiles = {}
    for name, _ in pairs(PROFILES) do
        table.insert(profiles, name)
    end
    return profiles
end

--- Get current configuration
--- @return table Current configuration
function MutationConfig.get_current_config()
    local logger = MutationLogger.get_instance()
    return logger.config
end

--- Enable/disable mutation logging at runtime
--- @param enabled boolean
function MutationConfig.set_enabled(enabled)
    MutationLogger.configure({ enabled = enabled })
    log("[MutationConfig] Mutation logging " .. (enabled and "enabled" or "disabled"))
end

--- Enable/disable debug mode at runtime  
--- @param debug boolean
function MutationConfig.set_debug(debug)
    MutationLogger.configure({ debug = debug })
    log("[MutationConfig] Debug mode " .. (debug and "enabled" or "disabled"))
end

return MutationConfig
