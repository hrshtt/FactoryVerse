local GameState = require("core.game_state.GameState")
local EntitiesSnapshot = require("snapshots.EntitiesSnapshot")
local ResourceSnapshot = require("snapshots.ResourceSnapshot")


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

M.helpers.test = function()
    triple_print("Testing")
end

M.helpers.take_resources = function()
    ResourceSnapshot:new():take()
end

M.helpers.take_crude_oil = function()
    ResourceSnapshot:new():take_crude()
end

M.helpers.take_water = function()
    ResourceSnapshot:new():take_water()
end

M.helpers.take_entities = function()
    EntitiesSnapshot:new():take()
end

M.helpers.take_belts = function()
    EntitiesSnapshot:new():take_belts()
end

M.load_helpers = function()
    if remote.interfaces["helpers"] then
        log("Found: " .. helpers.table_to_json(remote.interfaces["helpers"]))
        remote.remove_interface("helpers")
        log("Removed stale 'helpers' interface")
    end
    remote.add_interface("helpers", M.helpers)
    log("Loaded: " .. helpers.table_to_json(remote.interfaces["helpers"]))
    log("Added fresh 'helpers' interface")
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
        local print_str = helpers.table_to_json({ speed = game.speed })
        triple_print(print_str)
    end)
end

M.commands.is_paused = function()
    commands.add_command("is_paused", "Print if the game is paused", function()
        local print_str = helpers.table_to_json({ paused = game.tick_paused })
        triple_print(print_str)
    end)
end

M.commands.reload_scripts = function()
    commands.add_command("reload_scripts", "Reload the scripts", function()
        triple_print("Reloading scripts")
        game.reload_script()
    end)
end

M.commands.remove_biters = function()
    commands.add_command("remove_biters", "Remove biters", function()
        game.forces["enemy"].kill_all_units()
        game.map_settings.enemy_expansion.enabled = false
        game.map_settings.enemy_evolution.enabled = false
        local surface = game.surfaces[1]
        for _, entity in pairs(surface.find_entities_filtered({ type = "unit-spawner" })) do
            entity.destroy()
        end
    end)
end

M.load_commands = function()
    for name, command in pairs(commands.commands) do
        if command then
            local ok = commands.remove_command(name)
            log("Removed command: " .. name .. " " .. tostring(ok))
        end
    end
    log("Loading commands")
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
