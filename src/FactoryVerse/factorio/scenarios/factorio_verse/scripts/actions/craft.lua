--@craft.lua
--@description Craft action
--@author Harshit Sharma
--@version 1.0.0
--@date 2025-08-05

local A = {
    recorder = {}
}

local shared_utils = require("scripts.shared-utils")

A.run = function(ctx, P)
    local player = ctx.player or game.players[P.player_index]
    local recipe_id = ctx.recipe_id
    -- local recipe_name = P.name
    -- local count = P.count
    -- LuaPlayer.craft(player, recipe_name, count)

    local result = player.begin_crafting(recipe_id) -- TODO: check if this is correct
end


-- Storage for tracking crafting sessions
local crafting_sessions = {}

-- Helper function to generate session key
local function get_session_key(player_index, recipe_name)
    return player_index .. ":" .. recipe_name
end

-- Helper function to create a collated record
local function create_collated_record(player, recipe_name, start_tick, end_tick, total_queued, total_crafted,
                                      total_cancelled, craft_timings)
    local rec = shared_utils.create_base_record("craft_item", {
        tick = end_tick,
        player_index = player.index,
    }, player)

    rec.timing = {
        start_tick = start_tick,
        end_tick = end_tick,
        duration_ticks = end_tick - start_tick,
    }
    rec.crafting = {
        recipe = recipe_name,
        total_queued = total_queued,
        total_crafted = total_crafted,
        total_cancelled = total_cancelled,
        craft_timings = craft_timings or {},
    }

    return rec
end

-- Helper function to finalize a crafting session
local function finalize_session(session_key, end_tick)
    local session = crafting_sessions[session_key]
    if not session then return end

    local player = game.players[session.player_index]
    if not player or not player.valid then
        crafting_sessions[session_key] = nil
        return
    end

    -- Create the collated record
    local rec = create_collated_record(
        player,
        session.recipe_name,
        session.start_tick,
        end_tick,
        session.total_queued,
        session.total_crafted,
        session.total_cancelled,
        session.craft_timings
    )

    local clean_rec = shared_utils.clean_record(rec)
    local line = helpers.table_to_json(clean_rec)
    shared_utils.buffer_event("craft_item_collated", line)

    -- Clean up the session
    crafting_sessions[session_key] = nil
end

-- Handler for when crafting is queued
local function on_pre_player_crafted_item(event)
    if not shared_utils.is_player_event(event) then return end

    local player = game.players[event.player_index]
    local recipe_name = event.recipe and event.recipe.name or "unknown"
    local session_key = get_session_key(event.player_index, recipe_name)

    -- NOTE: We no longer automatically finalise other sessions when a new recipe is queued.
    -- A session will be finalised only when **all** of its queued crafts have either
    -- completed or been cancelled. This prevents premature finalisation that previously
    -- caused late completions to be dropped.

    local session = crafting_sessions[session_key]
    if not session then
        -- Start a new crafting session
        session = {
            player_index = event.player_index,
            recipe_name = recipe_name,
            start_tick = event.tick,
            last_activity_tick = event.tick,
            total_queued = event.queued_count or 0,
            total_crafted = 0,
            total_cancelled = 0,
            craft_timings = {} -- Initialize craft_timings for new session
        }
        crafting_sessions[session_key] = session

        -- Add timing entries for each queued craft
        local queued_count = event.queued_count or 0
        for i = 1, queued_count do
            table.insert(session.craft_timings, {
                queue_tick = event.tick,
                completion_tick = nil,
                cancelled_tick = nil,
                status = "queued" -- "queued", "completed", "cancelled"
            })
        end
    else
        -- Update existing session (same recipe being queued again)
        session.last_activity_tick = event.tick
        session.total_queued = session.total_queued + (event.queued_count or 0)

        -- Add timing entries for the newly queued crafts
        local queued_count = event.queued_count or 0
        for i = 1, queued_count do
            table.insert(session.craft_timings, {
                queue_tick = event.tick,
                completion_tick = nil,
                cancelled_tick = nil,
                status = "queued"
            })
        end
    end

    -- Helper to determine if a session is complete (all queued crafts resolved)
    local function try_finalize(session_key, tick)
        local s = crafting_sessions[session_key]
        if not s then return end
        if (s.total_crafted + s.total_cancelled) >= s.total_queued then
            finalize_session(session_key, tick)
        end
    end

    -- Immediately check if the session (or any other for this player) became complete
    try_finalize(session_key, event.tick)
end

-- Handler for when crafting completes
local function on_player_crafted_item(event)
    if not shared_utils.is_player_event(event) then return end

    local recipe_name = event.recipe and event.recipe.name or "unknown"
    local session_key = get_session_key(event.player_index, recipe_name)

    local session = crafting_sessions[session_key]
    if session then
        session.last_activity_tick = event.tick

        -- Factorio may return an `item_stack` table for crafted items. We count one
        -- craft per event. For recipes that yield multiple items, `item_stack.count`
        -- would not represent additional crafts but items produced, so we still
        -- increment by one here.
        session.total_crafted = session.total_crafted + 1

        -- Mark the first queued craft as completed
        for i, timing in ipairs(session.craft_timings) do
            if timing.status == "queued" then
                timing.completion_tick = event.tick
                timing.status = "completed"
                break
            end
        end

        -- Attempt to finalise if the session has resolved all queued crafts
        if (session.total_crafted + session.total_cancelled) >= session.total_queued then
            finalize_session(session_key, event.tick)
        end
    end
end

-- Handler for when crafting is cancelled
local function on_player_cancelled_crafting(event)
    if not shared_utils.is_player_event(event) then return end

    local recipe_name = event.recipe and event.recipe.name or "unknown"
    local session_key = get_session_key(event.player_index, recipe_name)

    local session = crafting_sessions[session_key]
    if session then
        session.last_activity_tick = event.tick
        session.total_cancelled = session.total_cancelled + (event.cancel_count or 0)

        -- Mark the appropriate number of queued crafts as cancelled
        local cancel_count = event.cancel_count or 0
        local cancelled_so_far = 0
        for i, timing in ipairs(session.craft_timings) do
            if timing.status == "queued" and cancelled_so_far < cancel_count then
                timing.cancelled_tick = event.tick
                timing.status = "cancelled"
                cancelled_so_far = cancelled_so_far + 1
            end
        end

        -- Attempt to finalise if the session has resolved all queued crafts
        if (session.total_crafted + session.total_cancelled) >= session.total_queued then
            finalize_session(session_key, event.tick)
        end
    end
end

-- Clean up sessions for disconnected players
local function on_player_left_game(event)
    local player_index = event.player_index

    -- Finalize any active sessions for this player
    for session_key, session in pairs(crafting_sessions) do
        if session.player_index == player_index then
            finalize_session(session_key, event.tick)
        end
    end
end

-- Clean up sessions periodically to prevent memory leaks
local function cleanup_old_sessions()
    local current_tick = game.tick
    -- Extended timeout: 10 minutes. This is a safety-net for sessions that, for
    -- whatever reason, never reached a resolved state (e.g. mod interference).
    local timeout_ticks = 36000

    for session_key, session in pairs(crafting_sessions) do
        -- First, attempt normal resolution based on counts
        if (session.total_crafted + session.total_cancelled) >= session.total_queued then
            finalize_session(session_key, session.last_activity_tick)
        elseif (current_tick - session.last_activity_tick) >= timeout_ticks then
            -- Fallback: give up waiting and finalise with current numbers
            finalize_session(session_key, session.last_activity_tick)
        end
    end
end

function A.recorder.register_events(event_dispatcher)
    -- Register the three-phase crafting events
    event_dispatcher.register_handler(defines.events.on_pre_player_crafted_item, on_pre_player_crafted_item)
    event_dispatcher.register_handler(defines.events.on_player_crafted_item, on_player_crafted_item)
    event_dispatcher.register_handler(defines.events.on_player_cancelled_crafting, on_player_cancelled_crafting)

    -- Register cleanup events
    event_dispatcher.register_handler(defines.events.on_player_left_game, on_player_left_game)

    -- Register periodic cleanup (every 5 minutes)
    event_dispatcher.register_nth_tick_handler(18000, cleanup_old_sessions)
end

-- Initialize storage on script load
function A.on_init()
    if not storage.craft_item_collated then
        storage.craft_item_collated = {
            crafting_sessions = {}
        }
    end
    crafting_sessions = storage.craft_item_collated.crafting_sessions
end

function A.on_load()
    if storage.craft_item_collated then
        crafting_sessions = storage.craft_item_collated.crafting_sessions
    end
end

return A
