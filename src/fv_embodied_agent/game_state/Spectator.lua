--- factorio_verse/core/game_state/Spectator.lua
--- Spectator module for managing spectator mode and auto-follow functionality.
--- Static module - no instantiation required.

local M = {}

-- ============================================================================
-- CONFIGURATION
-- ============================================================================

--- Initialize spectator storage
local function initialize_storage()
    if not storage.spectator then
        storage.spectator = {
            enabled = false,  -- Global flag to enable/disable spectator mode
            following_agent_id = nil,  -- Agent ID to follow (nil = no follow)
        }
    end
end

--- Get spectator config
--- @return table Spectator config
local function get_config()
    initialize_storage()
    return storage.spectator
end

-- ============================================================================
-- SPECTATOR FUNCTIONS
-- ============================================================================

--- Make a player a spectator
--- @param player LuaPlayer
local function make_spectator(player)
    if not player or not player.valid then
        return
    end
    
    local character = player.character
    player.set_controller({type = defines.controllers.spectator})
    
    -- Destroy character if it exists
    if character and character.valid then
        character.destroy()
    end
end

--- Get target character to follow
--- @return LuaEntity|nil Target character entity or nil
local function get_follow_target()
    local config = get_config()
    
    if not config.enabled or not config.following_agent_id then
        return nil
    end
    
    if not storage.agents then
        return nil
    end
    
    local agent = storage.agents[config.following_agent_id]
    if not agent then
        return nil
    end
    
    -- Try to get character from agent
    local character = agent.character
    if character and character.valid then
        return character
    end
    
    -- Fallback: try entity field
    if agent.entity and agent.entity.valid then
        return agent.entity
    end
    
    return nil
end

--- Update camera positions for all players to follow target
local function update_camera_positions()
    local target = get_follow_target()
    
    if not target or not target.valid then
        return
    end
    
    -- Update all players' positions to match target
    for _, player in pairs(game.connected_players) do
        if player and player.valid then
            -- Only update if player is in spectator mode
            if player.controller_type == defines.controllers.spectator then
                player.position = target.position
            end
        end
    end
end

-- ============================================================================
-- REMOTE INTERFACE API
-- ============================================================================

--- Make all connected players spectators
local function make_all_players_spectators()
    for _, player in pairs(game.connected_players) do
        if player and player.valid then
            make_spectator(player)
        end
    end
end

--- Enable spectator mode and optionally set agent to follow
--- @param enabled boolean Enable/disable spectator mode
--- @param agent_id number|nil Agent ID to follow (nil = stop following)
--- @return table Result {success: boolean, message: string}
function M.enable_spectator_mode(enabled, agent_id)
    local config = get_config()
    local was_enabled = config.enabled
    config.enabled = enabled or false
    
    if enabled and agent_id then
        -- Validate agent exists
        if not storage.agents or not storage.agents[agent_id] then
            return {
                success = false,
                message = "Agent " .. tostring(agent_id) .. " not found"
            }
        end
        config.following_agent_id = agent_id
    else
        config.following_agent_id = nil
    end
    
    -- If enabling spectator mode, convert all existing players
    if enabled and not was_enabled then
        make_all_players_spectators()
        
        -- If following an agent, update positions immediately
        if config.following_agent_id then
            local target = get_follow_target()
            if target and target.valid then
                for _, player in pairs(game.connected_players) do
                    if player and player.valid and player.controller_type == defines.controllers.spectator then
                        player.position = target.position
                    end
                end
            end
        end
    end
    
    local message = enabled and "Spectator mode enabled" or "Spectator mode disabled"
    if enabled and agent_id then
        message = message .. " (following agent " .. tostring(agent_id) .. ")"
    end
    
    return {
        success = true,
        message = message
    }
end

--- Get spectator mode status
--- @return table Status {enabled: boolean, following_agent_id: number|nil}
function M.get_spectator_status()
    local config = get_config()
    return {
        enabled = config.enabled,
        following_agent_id = config.following_agent_id
    }
end

--- Select which agent to follow
--- @param agent_id number Agent ID to follow
--- @return table Result {success: boolean, message: string}
function M.follow_agent(agent_id)
    if not agent_id then
        return {
            success = false,
            message = "Agent ID is required"
        }
    end
    
    -- Validate agent exists
    if not storage.agents or not storage.agents[agent_id] then
        return {
            success = false,
            message = "Agent " .. tostring(agent_id) .. " not found"
        }
    end
    
    local config = get_config()
    local was_enabled = config.enabled
    
    -- Enable spectator mode if not already enabled
    if not config.enabled then
        config.enabled = true
        make_all_players_spectators()
    end
    
    -- Set the agent to follow
    config.following_agent_id = agent_id
    
    -- Update all spectator players' positions immediately
    local target = get_follow_target()
    if target and target.valid then
        for _, player in pairs(game.connected_players) do
            if player and player.valid and player.controller_type == defines.controllers.spectator then
                player.position = target.position
            end
        end
    end
    
    local message = "Now following agent " .. tostring(agent_id)
    if not was_enabled then
        message = message .. " (spectator mode enabled)"
    end
    
    return {
        success = true,
        message = message
    }
end

--- Stop following (but keep spectator mode enabled)
--- @return table Result {success: boolean, message: string}
function M.stop_following()
    local config = get_config()
    config.following_agent_id = nil
    
    return {
        success = true,
        message = "Stopped following agent"
    }
end

-- ============================================================================
-- EVENT HANDLERS
-- ============================================================================

--- Get events (defined events and nth_tick)
--- @return table {defined_events = {}, nth_tick = {}}
function M.get_events()
    return {
        defined_events = {
            [defines.events.on_player_joined_game] = function(event)
                local player = game.get_player(event.player_index)
                if not player or not player.valid then
                    return
                end
                
                local config = get_config()
                
                -- If spectator mode is enabled, make new players spectators
                if config.enabled then
                    make_spectator(player)
                    
                    -- If following an agent, update position immediately
                    if config.following_agent_id then
                        local target = get_follow_target()
                        if target and target.valid then
                            player.position = target.position
                        end
                    end
                end
            end,
            
            [defines.events.on_tick] = function(event)
                local config = get_config()
                
                -- Early exit: Only process if spectator mode is enabled and we're following an agent
                if not config.enabled or not config.following_agent_id then
                    return
                end
                
                -- Early exit: Check if agents storage exists and has agents
                if not storage.agents then
                    return
                end
                
                -- Check if agents table has any entries (it's a dictionary, not array)
                local has_agents = false
                for _ in pairs(storage.agents) do
                    has_agents = true
                    break
                end
                if not has_agents then
                    return
                end
                
                -- Update camera positions
                update_camera_positions()
            end
        },
        nth_tick = {}
    }
end

-- ============================================================================
-- REMOTE INTERFACE REGISTRATION
-- ============================================================================

--- Register remote interface for spectator methods
--- @return table Remote interface table
function M.register_remote_interface()
    return {
        enable_spectator_mode = function(enabled, agent_id)
            return M.enable_spectator_mode(enabled, agent_id)
        end,
        follow_agent = function(agent_id)
            return M.follow_agent(agent_id)
        end,
        get_spectator_status = function()
            return M.get_spectator_status()
        end,
        stop_following = function()
            return M.stop_following()
        end
    }
end

-- ============================================================================
-- INITIALIZATION
-- ============================================================================

--- Initialize spectator storage (called from control.lua)
function M.initialize_storage()
    initialize_storage()
end

return M

