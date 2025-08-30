local GameState = require("core.game_state.GameState")


local triple_print = function(print_str)
    game.print(print_str)
    log(print_str)
    rcon.print(print_str)
end

local M = {}
M.helpers = {}
M.commands = {}

M.helpers.create_agent_characters = function(num_agents, destroy_existing)
    return GameState:new():agent():create_agent_characters(num_agents, destroy_existing)
end

M.load_helpers = function()
    if remote.interfaces["helpers"] then
        log("Removing helpers interface")
        remote.remove_interface("helpers")
    end
    log("Adding helpers interface")
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
        local print_str = helpers.table_to_json({speed = game.speed})
        triple_print(print_str)
    end)
end

M.commands.is_paused = function()
    commands.add_command("is_paused", "Print if the game is paused", function()
        local print_str = helpers.table_to_json({paused = game.tick_paused})
        triple_print(print_str)
    end)
end

M.commands.reload_scripts = function()
    commands.add_command("reload_scripts", "Reload the scripts", function()
        triple_print("Reloading scripts")
        game.reload_script()
    end)
end

M.load_commands = function()
    log("Commands:")
    log(helpers.table_to_json(commands.commands))
    log("Loading commands")
    for name, command in pairs(commands.commands) do
        log("Command: " .. name)
        if command then
            log("Removing command: " .. name)
            local ok = commands.remove_command(name)
            log("Removed command: " .. name .. " " .. tostring(ok))
        end
    end
    for name, command in pairs(M.commands) do
        if type(command) == "function" then
            local ok, err = pcall(command)
            if not ok then
                log("Error loading command: " .. name .. " " .. err)
            else
                log("Loaded command: " .. name)
            end
        end
    end
end

return M