local Snapshot = require "core.snapshot.Snapshot"
local GameState = require "core.game_state.GameState"
local utils = require "utils"

--- AgentSnapshot: On-demand agent position + inventory snapshots
--- Captures agent position and inventory on-demand via remote call
--- @class AgentSnapshot : Snapshot
local AgentSnapshot = Snapshot:new()
AgentSnapshot.__index = AgentSnapshot

---@return AgentSnapshot
function AgentSnapshot:new()
    local instance = Snapshot:new()
    setmetatable(instance, self)
    ---@cast instance AgentSnapshot
    return instance
end

--- Take snapshot for a specific agent
--- @param agent_id number - agent ID
--- @return table - agent data as JSON
function AgentSnapshot:take(agent_id)
    log("Taking agent snapshot for agent " .. tostring(agent_id))

    local agent = self.game_state:agent_state():get_agent(agent_id)
    if not agent or not agent.valid then
        local error_result = {
            error = "Agent not found or invalid",
            agent_id = agent_id,
            tick = game and game.tick or 0
        }
        utils.triple_print(helpers.table_to_json(error_result))
        return error_result
    end

    -- Get agent position
    local position = agent.position
    if not position then
        local error_result = {
            error = "Agent has no position",
            agent_id = agent_id,
            tick = game and game.tick or 0
        }
        utils.triple_print(helpers.table_to_json(error_result))
        return error_result
    end

    -- Get agent inventory
    local inventory = {}
    local main_inventory = agent.get_main_inventory and agent:get_main_inventory()
    if main_inventory then
        local contents = main_inventory.get_contents()
        if contents and next(contents) ~= nil then
            inventory = contents
        end
    end

    local result = {
        agent_id = agent_id,
        tick = game and game.tick or 0,
        position_x = position.x,
        position_y = position.y,
        inventory = inventory
    }

    utils.triple_print(helpers.table_to_json(result))
    return result
end

return AgentSnapshot
