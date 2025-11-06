local GameState = require("GameState")
local Snapshot = require("core.snapshot.Snapshot")
local utils = require("core.utils")


local M = {}
M.helpers = {}
M.commands = {}

M.helpers.create_agent_characters = function(num_agents, destroy_existing)
    return GameState:new():agent():create_agent_characters(num_agents, destroy_existing)
end

M.helpers.force_clear_agents = function()
    utils.players_to_spectators()
    return GameState:new():agent():force_destroy_agents()
end

M.helpers.test = function()
    utils.triple_print("Testing say hiii")
end

M.helpers.print_agent_inventory = function(agent_index)
    local agent = GameState:new():agent():get_agent(agent_index)
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
    local snapshot = Snapshot:get_instance()
    local result = snapshot:take_map_snapshot({components = {"resources"}, async = false})
    rcon.print(helpers.table_to_json(result))
    return result
end

M.helpers.take_entities = function()
    local snapshot = Snapshot:get_instance()
    local result = snapshot:take_map_snapshot({components = {"entities"}, async = false})
    rcon.print(helpers.table_to_json(result))
    return result
end

M.helpers.get_entity_inventory = function(unit_number)
    local snapshot = Snapshot:get_instance()
    local result_json = snapshot:take_entity_inventory({unit_number})
    rcon.print(result_json)
    return result_json
end

M.helpers.get_entities_inventory = function(unit_numbers)
    local snapshot = Snapshot:get_instance()
    local result_json = snapshot:take_entity_inventory(unit_numbers)
    rcon.print(result_json)
    return result_json
end

M.helpers.get_agent_snapshot = function(agent_id)
    local snapshot = Snapshot:get_instance()
    local result_json = snapshot:take_agent_snapshot(agent_id)
    rcon.print(result_json)
    return result_json
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

-- UDP Test Helpers (temporary POC - safe to remove)
M.helpers.udp_test_start = function(target_host, target_port, payload_size_kb, frequency_ticks)
    local success, UdpTest = pcall(require, "core.UdpTest")
    if not success then
        utils.triple_print(helpers.table_to_json({ 
            error = "Failed to load UdpTest module", 
            details = tostring(UdpTest)
        }))
        return
    end
    UdpTest.start_test(target_host, target_port, payload_size_kb, frequency_ticks)
    utils.triple_print(helpers.table_to_json({ 
        message = "UDP test started", 
        target = target_host .. ":" .. target_port,
        payload_size_kb = payload_size_kb,
        frequency_ticks = frequency_ticks
    }))
end

M.helpers.udp_test_stop = function()
    local success, UdpTest = pcall(require, "core.UdpTest")
    if not success then
        utils.triple_print(helpers.table_to_json({ 
            error = "Failed to load UdpTest module", 
            details = tostring(UdpTest)
        }))
        return
    end
    UdpTest.stop_test()
    utils.triple_print(helpers.table_to_json({ message = "UDP test stopped" }))
end

M.helpers.udp_test_stats = function()
    local success, UdpTest = pcall(require, "core.UdpTest")
    if not success then
        utils.triple_print(helpers.table_to_json({ 
            error = "Failed to load UdpTest module", 
            details = tostring(UdpTest)
        }))
        return
    end
    local stats = UdpTest.get_stats()
    utils.triple_print(helpers.table_to_json(stats))
end

-- Forcefully stop all agent activities and flush pending intents/jobs
M.helpers.reset_agents_state = function()
    local gs = GameState:new()
    local agent_state = gs:agent()

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

M.helpers.take_map_snapshot = function(options_json)
    local snapshot = Snapshot:get_instance()
    local options = {}
    
    if options_json and type(options_json) == "string" then
        local ok, decoded = pcall(helpers.json_to_table, options_json)
        if ok and type(decoded) == "table" then 
            options = decoded 
        end
    end
    
    -- Default: SYNCHRONOUS with both components (entities will be written immediately)
    -- Pass {async: true} to use async mode
    if options.async == nil then
        options.async = false  -- Default to synchronous for RCON calls
    end
    options.components = options.components or {"entities", "resources"}
    options.chunks_per_tick = options.chunks_per_tick or 2
    
    log(string.format("[admin_api.take_map_snapshot] Starting snapshot: async=%s, components=%s", 
        tostring(options.async), table.concat(options.components, ",")))
    
    local result = snapshot:take_map_snapshot(options)
    
    log(string.format("[admin_api.take_map_snapshot] Snapshot result: %s", helpers.table_to_json(result)))
    rcon.print(helpers.table_to_json(result))
    return result
end

M.helpers.take_chunk_snapshot = function(chunk_x, chunk_y, options_json)
    local snapshot = Snapshot:get_instance()
    local options = {}
    
    if options_json and type(options_json) == "string" then
        local ok, decoded = pcall(helpers.json_to_table, options_json)
        if ok and type(decoded) == "table" then 
            options = decoded 
        end
    end
    
    options.components = options.components or {"entities", "resources"}
    
    local result = snapshot:take_chunk_snapshot(chunk_x, chunk_y, options)
    rcon.print(helpers.table_to_json(result))
    return result
end

M.helpers.take_entity_inventory = function(unit_numbers_json)
    local snapshot = Snapshot:get_instance()
    local unit_numbers = {}
    
    if unit_numbers_json and type(unit_numbers_json) == "string" then
        local ok, decoded = pcall(helpers.json_to_table, unit_numbers_json)
        if ok and type(decoded) == "table" then
            unit_numbers = decoded
        end
    end
    
    local result_json = snapshot:take_entity_inventory(unit_numbers)
    rcon.print(result_json)
    return result_json
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

M.commands.take_map_snapshot = function()
    commands.add_command("take_map_snapshot", "Take a map snapshot", function()
        local snapshot = Snapshot:get_instance()
        local result = snapshot:take_map_snapshot({async = false})
        utils.triple_print("Map snapshot completed: " .. helpers.table_to_json(result))
    end)
end

M.commands.snapshot_entity = function()
    commands.add_command("snapshot_entity", "Snapshot a single entity", function(command)
        local success, unit_number = pcall(tonumber, command.parameter)
        if not success or not unit_number then
            utils.triple_print('{"error": "Invalid unit number parameter"}')
            return
        end
        
        local snapshot = Snapshot:get_instance()
        local success = snapshot:update_entity_from_action(unit_number, nil)
        if success then
            utils.triple_print('{"success": true, "unit_number": ' .. unit_number .. '}')
        else
            utils.triple_print('{"error": "Entity not found or invalid", "unit_number": ' .. unit_number .. '}')
        end
    end)
end

M.commands.snapshot_chunk = function()
    commands.add_command("snapshot_chunk", "Snapshot all entities in a chunk", function(command)
        local params = command.parameter:match("(%d+),?(%d*)")
        if not params then
            utils.triple_print('{"error": "Invalid parameters. Use: /snapshot_chunk <chunk_x>,<chunk_y>"}')
            return
        end
        
        local chunk_x, chunk_y = params:match("(%d+),?(%d*)")
        chunk_x = tonumber(chunk_x) or 0
        chunk_y = tonumber(chunk_y) or 0
        
        local snapshot = Snapshot:get_instance()
        local result = snapshot:take_chunk_snapshot(chunk_x, chunk_y, {components = {"entities"}})
        if result and result.entities_written then
            utils.triple_print('{"success": true, "chunk_x": ' .. chunk_x .. ', "chunk_y": ' .. chunk_y .. ', "entities_written": ' .. result.entities_written .. '}')
        else
            utils.triple_print('{"error": "Failed to snapshot chunk", "chunk_x": ' .. chunk_x .. ', "chunk_y": ' .. chunk_y .. '}')
        end
    end)
end

M.commands.rebuild_manifests = function()
    commands.add_command("rebuild_manifests", "Rebuild all chunk manifests", function()
        utils.triple_print("Rebuilding all chunk manifests...")
        local snapshot = Snapshot:get_instance()
        local result = snapshot:take_map_snapshot({components = {"entities"}, async = false})
        
        if result and result.stats then
            utils.triple_print('{"success": true, "chunks_processed": ' .. result.stats.chunks .. '}')
        else
            utils.triple_print('{"error": "Failed to rebuild manifests"}')
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

M.load_commands()

return M
