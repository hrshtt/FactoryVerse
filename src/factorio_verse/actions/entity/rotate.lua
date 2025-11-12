local Action = require("types.Action")
local GameStateAliases = require("game_state.GameStateAliases")

--- @class RotateEntityParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field position table Position of the target entity: { x = number, y = number }
--- @field entity_name string Entity prototype name
--- @field direction string|number Direction to rotate to (required) - accepts alias from GameState.aliases.direction or defines.direction value (0-7)
local RotateEntityParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    position = { type = "position", required = true },
    entity_name = { type = "entity_name", required = true },
    direction = { type = "direction", required = true }
})

--- @class RotateEntityAction : Action
local RotateEntityAction = Action:new("entity.rotate", RotateEntityParams)

--- @param params RotateEntityParams
--- @return table result Data about the rotated entity
function RotateEntityAction:run(params)
    log("DEBUG ROTATE: run() called with params")
    local p = self:_pre_run(params)
    ---@cast p RotateEntityParams
    
    log("DEBUG ROTATE: After _pre_run")

    local position = { x = p.position.x, y = p.position.y }
    local entity = game.surfaces[1].find_entity(p.entity_name, position)
    if not entity or not entity.valid then
        error("Entity not found or invalid")
    end

    -- Check if entity supports rotation
    if not entity.supports_direction then
        error("Entity does not support rotation")
    end

    local original_direction = entity.direction
    local new_direction = original_direction

    -- Direction is already normalized by ParamSpec (string aliases converted to enum numbers)
    -- Cast to number since ParamSpec normalizes string aliases to enum numbers (0-7)
    local target_direction = tonumber(p.direction) or p.direction

    -- Check if already in target direction (no-op)
    if original_direction == target_direction then
        return self:_post_run({
            position = position,
            entity_name = p.entity_name,
            direction = entity.direction,
            original_direction = original_direction,
            new_direction = new_direction,
            no_op = true,
            message = "Entity already in requested direction",
            affected_positions = { { position = position, entity_name = p.entity_name } }
        }, p)
    end

    -- Set the requested direction
    entity.direction = target_direction
    new_direction = target_direction
    log("DEBUG ROTATE: Set entity direction from " .. original_direction .. " to " .. new_direction)

    local result = {
        position = position,
        entity_name = p.entity_name,
        direction = entity.direction,
        original_direction = original_direction,
        new_direction = new_direction,
        affected_positions = { { position = position, entity_name = p.entity_name, entity_type = entity.type } }
    }
    
    return self:_post_run(result, p)
end

return { action = RotateEntityAction, params = RotateEntityParams }
