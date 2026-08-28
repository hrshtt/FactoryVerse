--- game_state/Spectator.lua — the observer policy.
---
--- A human who joins a world this mod runs in has no character and cannot
--- alter the world. That is the spectator controller ("can't change anything
--- in the world but can view anything"), not the god controller (no body, but
--- full ability to build and mine). The policy lives in the mod rather than
--- in a scenario so that a checkpoint-resumed world — whose scenario script
--- was baked at creation — is covered too, and so that it can be read back
--- from the running world (SCENARIO_BOOT_CONTRACT_DEFERRED.md §5).
---
--- Governed by the runtime-global setting `fv-observer-spectator` (default
--- true). Agents are script-created characters with no LuaPlayer, so
--- on_player_joined_game never fires for them; the `player.connected` guard
--- makes that intent explicit rather than incidental.
---
--- Camera-follow of an agent is kept as an opt-in remote (`follow_agent`);
--- it costs one position write per connected spectator per tick only while
--- a follow target is set.

local M = {}

local SETTING = "fv-observer-spectator"

local function policy_enabled()
    local setting = settings.global[SETTING]
    return setting ~= nil and setting.value == true
end

local function get_config()
    if not storage.spectator then
        storage.spectator = { following_agent_id = nil }
    end
    return storage.spectator
end

--- Switch a connected human to the spectator controller and destroy the
--- character the engine gave them. set_controller detaches; it does not
--- destroy — without the explicit destroy an orphaned body stands in the
--- world, minable and collidable.
local function make_spectator(player)
    if not (player and player.valid and player.connected) then
        return false
    end
    if player.controller_type == defines.controllers.spectator then
        return true
    end
    local character = player.character
    player.set_controller({ type = defines.controllers.spectator })
    if character and character.valid then
        character.destroy()
    end
    return true
end

local function get_follow_target()
    local config = get_config()
    if not config.following_agent_id or not storage.agents then
        return nil
    end
    local agent = storage.agents[config.following_agent_id]
    if not agent then
        return nil
    end
    if agent.character and agent.character.valid then
        return agent.character
    end
    if agent.entity and agent.entity.valid then
        return agent.entity
    end
    return nil
end

local function update_camera_positions()
    local target = get_follow_target()
    if not target then
        return
    end
    for _, player in pairs(game.connected_players) do
        if player.valid and player.controller_type == defines.controllers.spectator then
            player.position = target.position
        end
    end
end

-- ============================================================================
-- REMOTE API
-- ============================================================================

--- What the policy is and whether it is in force — the read a boot probe
--- uses to prove the observer policy from the running world.
function M.get_spectator_status()
    local players = {}
    for _, player in pairs(game.connected_players) do
        players[#players + 1] = {
            name = player.name,
            controller = player.controller_type,
            has_character = player.character ~= nil,
        }
    end
    return {
        setting = SETTING,
        enabled = policy_enabled(),
        following_agent_id = get_config().following_agent_id,
        connected_players = players,
    }
end

--- Apply the policy now to every connected human (used after the setting
--- is switched on mid-session).
function M.apply_to_connected_players()
    if not policy_enabled() then
        return { success = false, message = SETTING .. " is disabled" }
    end
    local count = 0
    for _, player in pairs(game.connected_players) do
        if make_spectator(player) then
            count = count + 1
        end
    end
    return { success = true, converted = count }
end

function M.follow_agent(agent_id)
    if not agent_id then
        return { success = false, message = "Agent ID is required" }
    end
    if not storage.agents or not storage.agents[agent_id] then
        return { success = false, message = "Agent " .. tostring(agent_id) .. " not found" }
    end
    get_config().following_agent_id = agent_id
    update_camera_positions()
    return { success = true, message = "Now following agent " .. tostring(agent_id) }
end

function M.stop_following()
    get_config().following_agent_id = nil
    return { success = true, message = "Stopped following agent" }
end

-- ============================================================================
-- EVENTS
-- ============================================================================

function M.get_events()
    return {
        defined_events = {
            [defines.events.on_player_joined_game] = function(event)
                if not policy_enabled() then
                    return
                end
                local player = game.get_player(event.player_index)
                if make_spectator(player) then
                    log("fv_embodied_agent: " .. player.name .. " joined as spectator (" .. SETTING .. ")")
                    update_camera_positions()
                end
            end,
            [defines.events.on_runtime_mod_setting_changed] = function(event)
                if event.setting == SETTING and policy_enabled() then
                    M.apply_to_connected_players()
                end
            end,
            [defines.events.on_tick] = function()
                if get_config().following_agent_id then
                    update_camera_positions()
                end
            end,
        },
        nth_tick = {},
    }
end

function M.register_remote_interface()
    return {
        get_spectator_status = M.get_spectator_status,
        apply_to_connected_players = M.apply_to_connected_players,
        follow_agent = M.follow_agent,
        stop_following = M.stop_following,
    }
end

function M.initialize_storage()
    get_config()
end

return M
