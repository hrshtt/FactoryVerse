local Action = require("types.Action")

--- @class TeleportParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field position table Position to teleport to: { x = number, y = number }
--- @field fallback_to_safe_position boolean|nil If true, try to find safe position nearby if target is blocked (default false)
local TeleportParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    position = { type = "position", required = true },
    fallback_to_safe_position = { type = "boolean", required = false, default = false }
})

--- @class TeleportAction : Action
local TeleportAction = Action:new("agent.teleport", TeleportParams)

--- @param params TeleportParams
--- @return table result Data about the teleportation
function TeleportAction:run(params)
    local p = self:_pre_run(params)
    ---@cast p TeleportParams

    local agent = self.game_state.agent:get_agent(p.agent_id)
    if not agent or not agent.valid then
        error("Agent not found or invalid")
    end

    local surface = agent.surface or game.surfaces[1]
    if not surface then
        error("No surface available")
    end

    -- Validate position format (should be handled by ParamSpec, but double-check)
    if not p.position or type(p.position.x) ~= "number" or type(p.position.y) ~= "number" then
        error("Position must be a table with numeric x and y")
    end

    local target_position = { x = p.position.x, y = p.position.y }
    local teleport_position = target_position

    -- Handle position safety check
    if p.fallback_to_safe_position then
        -- Fallback mode: try to find safe position nearby, but fallback to target if needed
        local safe_position = surface.find_non_colliding_position("character", target_position, 10, 2)
        if safe_position then
            teleport_position = safe_position
        else
            -- Fallback to target position even if not perfectly safe
            teleport_position = target_position
        end
    else
        -- Default strict mode: check if the EXACT target position is safe
        -- If not, fail with an error
        local can_place = surface.can_place_entity{
            name = "character",
            position = target_position,
            force = agent.force
        }
        if not can_place then
            error("Target position is not safe for teleportation (blocked or invalid)")
        end
        -- Use exact target position since it's safe
        teleport_position = target_position
    end

    -- Stop any active activities before teleporting
    local agent_state = self.game_state.agent
    agent_state:stop_walking(p.agent_id)
    agent_state:set_mining(p.agent_id, false)

    -- Store old position for result
    local old_position = { x = agent.position.x, y = agent.position.y }

    -- Perform teleportation
    local success = agent.teleport(teleport_position)
    if not success then
        error("Failed to teleport agent")
    end

    -- Read actual position from character entity after teleport
    local actual_position = { x = agent.position.x, y = agent.position.y }

    -- Note: Rendered name tags automatically follow the entity when it moves

    local result = {
        agent_id = p.agent_id,
        old_position = old_position,
        target_position = target_position,
        actual_position = actual_position,
        success = true
    }
    return self:_post_run(result, p)
end

return { action = TeleportAction, params = TeleportParams }

