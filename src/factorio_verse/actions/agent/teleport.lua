local Action = require("types.Action")
local GameContext = require("types.GameContext")

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

--- @class TeleportContext
--- @field agent LuaEntity Agent character entity
--- @field position table Position to teleport to: {x: number, y: number}
--- @field fallback_to_safe_position boolean If true, try to find safe position nearby if target is blocked
--- @field params TeleportParams ParamSpec instance for _post_run

--- Override _pre_run to build context using GameContext
--- @param params TeleportParams|table|string
--- @return TeleportContext
function TeleportAction:_pre_run(params)
    -- Call parent to get validated ParamSpec
    local p = Action._pre_run(self, params)
    local params_table = p:get_values()
    
    -- Build context using GameContext
    local agent = GameContext.resolve_agent(params_table, self.game_state)
    
    -- Return context for run()
    return {
        agent = agent,
        position = params_table.position,
        fallback_to_safe_position = params_table.fallback_to_safe_position or false,
        params = p
    }
end

--- @param params TeleportParams|table|string
--- @return table result Data about the teleportation
function TeleportAction:run(params)
    --- @type TeleportContext
    local context = self:_pre_run(params)

    local surface = context.agent.surface or game.surfaces[1]
    if not surface then
        error("No surface available")
    end

    -- Validate position format (should be handled by ParamSpec, but double-check)
    if not context.position or type(context.position.x) ~= "number" or type(context.position.y) ~= "number" then
        error("Position must be a table with numeric x and y")
    end

    local target_position = { x = context.position.x, y = context.position.y }
    local teleport_position = target_position

    -- Handle position safety check
    if context.fallback_to_safe_position then
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
            force = context.agent.force
        }
        if not can_place then
            error("Target position is not safe for teleportation (blocked or invalid)")
        end
        -- Use exact target position since it's safe
        teleport_position = target_position
    end

    -- Stop any active activities before teleporting
    local agent_state = self.game_state.agent
    local params_table = context.params:get_values()
    agent_state:stop_walking(params_table.agent_id)
    agent_state:set_mining(params_table.agent_id, false)

    -- Store old position for result
    local old_position = { x = context.agent.position.x, y = context.agent.position.y }

    -- Perform teleportation
    local success = context.agent.teleport(teleport_position)
    if not success then
        error("Failed to teleport agent")
    end

    -- Read actual position from character entity after teleport
    local actual_position = { x = context.agent.position.x, y = context.agent.position.y }

    -- Note: Rendered name tags automatically follow the entity when it moves

    local result = {
        agent_id = params_table.agent_id,
        old_position = old_position,
        target_position = target_position,
        actual_position = actual_position,
        success = true
    }
    return self:_post_run(result, context.params)
end

return { action = TeleportAction, params = TeleportParams }

