local Action = require("core.action.Action")
local ParamSpec = require("core.action.ParamSpec")
local game_state = require("core.game_state.GameState")

--- @class WalkParams : ParamSpec
--- @field agent_id number
--- @field direction string|number
--- @field walking boolean|nil
--- @field ticks number|nil
local WalkParams = ParamSpec:new({
    agent_id = { type = "number", required = true },
    direction = { type = "string", required = true },
    walking = { type = "boolean", required = false },
    ticks = { type = "number", required = false },
})

--- Map common direction strings to defines.direction

local function normalize_direction(dir)
    if type(dir) == "number" then
        return dir
    end
    if type(dir) == "string" then
        local key = string.lower(dir)
        return game_state.aliases.direction[key]
    end
    return nil
end

--- @class WalkAction : Action
--- @field validators table<function>
local WalkAction = Action:new("agent.walk", WalkParams)

--- @param params WalkParams
--- @return boolean
function WalkAction:run(params)
    local p = self:_pre_run(game_state, params)
    ---@cast p WalkParams
    local agent_id = p.agent_id
    local direction = normalize_direction(p.direction)
    local should_walk = p.walking

    if direction == nil then
        return false
    end

    local agent = game_state.agent:get_agent(agent_id)

    -- If ticks specified, register an intent to sustain walking each tick
    if p.ticks and p.ticks > 0 then
        storage.walk_intents = storage.walk_intents or {}
        storage.walk_intents[agent_id] = {
            direction = direction,
            end_tick = game.tick + p.ticks,
            walking = (should_walk ~= false)
        }
        -- Apply immediately this tick as well
        agent.walking_state = { walking = (should_walk ~= false), direction = direction }
        return true
    end

    -- One-shot set for this tick
    if should_walk == false then
        -- Stop walking and clear any intent
        if storage.walk_intents then
            storage.walk_intents[agent_id] = nil
        end
        local current_dir = (agent.walking_state and agent.walking_state.direction) or direction
        agent.walking_state = { walking = false, direction = current_dir }
    else
        agent.walking_state = { walking = true, direction = direction }
    end

    return self:_post_run(true, p)
end

-- Event handlers defined in the action so control.lua can register them later
local function on_tick(event)
    if not storage.walk_intents then return end

    local current_tick = game.tick
    for agent_id, intent in pairs(storage.walk_intents) do
        -- Expire intents
        if intent.end_tick and current_tick >= intent.end_tick then
            storage.walk_intents[agent_id] = nil
        else
            local player = (game and game.players) and game.players[agent_id] or nil
            local control = nil
            if player and player.valid then
                control = player
            else
                local agent = storage.agent_characters and storage.agent_characters[agent_id] or nil
                if agent and agent.valid and agent.walking_state ~= nil then
                    control = agent
                end
            end

            if control and control.walking_state ~= nil then
                control.walking_state = {
                    walking = (intent.walking ~= false),
                    direction = intent.direction
                }
            end
        end
    end
end

WalkAction.events = {
    [defines.events.on_tick] = on_tick
}

return WalkAction


