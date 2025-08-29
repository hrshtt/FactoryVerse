local GameState = require("core.game_state.GameState")

local M = {}
M.helpers = {}
M.commands = {}

M.helpers.create_agent_characters = function(num_agents, destroy_existing)
    return GameState:new():agent():create_agent_characters(num_agents, destroy_existing)
end

M.load_helpers = function()
    remote.add_interface("helpers", M.helpers)
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
        game.print("Speed: " .. game.speed)
        log("Speed: " .. game.speed)
    end)
end

M.load_commands = function()
    M.commands.pause()
    M.commands.resume()
    M.commands.set_speed()
    M.commands.print_speed()
end

return M