local GameState = require("core.game_state.GameState")
local EntitiesSnapshot = require("core.snapshot.EntitiesSnapshot")
local ResourceSnapshot = require("core.snapshot.ResourceSnapshot")
local EntityInventory = require("core.snapshot.EntityInventory")
local AgentSnapshot = require("core.snapshot.AgentSnapshot")
local utils = require("utils")


local M = {}
M.helpers = {}
M.commands = {}

M.helpers.create_agent_characters = function(num_agents, destroy_existing)
    return GameState:new():agent_state():create_agent_characters(num_agents, destroy_existing)
end

M.helpers.force_clear_agents = function()
    utils.players_to_spectators()
    return GameState:new():agent_state():force_destroy_agents()
end

M.helpers.test = function()
    utils.triple_print("Testing say hiii")
end

M.helpers.print_agent_inventory = function(agent_index)
    local agent = GameState:new():agent_state():get_agent(agent_index)
    if not agent or not agent.valid then
        utils.triple_print('{"error": "Agent character not found or invalid"}')
        return
    end
    local inv = agent.get_main_inventory and agent:get_main_inventory()
    if not inv then
        utils.triple_print('{"error": "No main inventory for agent"}')
        return
    end
    local items = {}
    for i = 1, #inv do
        local stack = inv[i]
        if stack and stack.valid_for_read then
            table.insert(items, {
                name = stack.name,
                count = stack.count
            })
        end
    end
    utils.triple_print(helpers.table_to_json({ inventory = items }))
end


M.helpers.take_resources = function()
    ResourceSnapshot:new():take()
end

M.helpers.take_entities = function()
    EntitiesSnapshot:new():take()
end

M.helpers.take_belts = function()
    EntitiesSnapshot:new():take_belts()
end

M.helpers.get_entity_inventory = function(unit_number)
    return EntityInventory:new():take(unit_number)
end

M.helpers.get_agent_snapshot = function(agent_id)
    return AgentSnapshot:new():take(agent_id)
end

M.helpers.clear_script_output = function()
    local success, _ = pcall(helpers.remove_path, "script-output/factoryverse")
    if success then
        utils.triple_print("[helpers.clear_script_output] Successfully cleared script-output/factoryverse directory")
    else
        utils.triple_print(
        "[helpers.clear_script_output] Failed to clear script-output/factoryverse directory (may not exist)")
    end
end

-- Forcefully stop all agent activities and flush pending intents/jobs
M.helpers.reset_agents_state = function()
    local gs = GameState:new()
    local agent_state = gs:agent_state()

    -- Stop walking/mining on all agent characters
    if storage.agent_characters then
        for id, agent in pairs(storage.agent_characters) do
            if agent and agent.valid then
                local current_dir = (agent.walking_state and agent.walking_state.direction) or defines.direction.north
                agent.walking_state = { walking = false, direction = current_dir }
                agent.mining_state = { mining = false }
            end
        end
    end

    -- Flush intents and jobs
    storage.walk_intents = nil
    storage.walk_to_jobs = nil
    storage.mine_resource_jobs = nil
    storage.agent_selection = nil

    utils.triple_print("[helpers.reset_agents_state] Stopped all agent walking/mining and cleared pending jobs/intents.")
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
        utils.triple_print(print_str)
    end)
end

M.commands.is_paused = function()
    commands.add_command("is_paused", "Print if the game is paused", function()
        local print_str = helpers.table_to_json({ paused = game.tick_paused })
        utils.triple_print(print_str)
    end)
end

M.commands.reload_scripts = function()
    commands.add_command("reload_scripts", "Reload the scripts", function()
        utils.triple_print("Reloading scripts")
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
