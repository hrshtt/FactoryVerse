local M = {}

function M.render_player_floating_text(text, position, nth_tick)
    local nth_tick = nth_tick or 60
    if game.players[1] and game.tick % nth_tick == 0 then
        local player = game.players[1]
        player.create_local_flying_text({
            text = text,
            surface = player.surface,
            create_at_cursor = false,
            position = position,
        })
    end
end

return M