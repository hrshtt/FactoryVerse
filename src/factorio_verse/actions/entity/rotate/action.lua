local Action = require("core.action.Action")
local ParamSpec = require("core.action.ParamSpec")
local GameState = require("core.game_state.GameState")

local gs = GameState:new()

--- @class RotateEntityParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field unit_number number Unique identifier for the target entity
--- @field direction string|number|nil Optional direction; accepts alias from GameState.aliases.direction or defines.direction value
local RotateEntityParams = ParamSpec:new({
    agent_id = { type = "number", required = true },
    unit_number = { type = "number", required = true },
    direction = { type = "any", required = false }
})

--- @class RotateEntityAction : Action
local RotateEntityAction = Action:new("entity.rotate", RotateEntityParams)

--- @param params RotateEntityParams
--- @return table result Data about the rotated entity
function RotateEntityAction:run(params)
    local p = self:_pre_run(gs, params)
    ---@cast p RotateEntityParams

    local entity = game.get_entity_by_unit_number(p.unit_number)
    if not entity or not entity.valid then
        error("Entity not found or invalid")
    end

    -- Check if entity supports rotation
    if not entity.supports_direction then
        error("Entity does not support rotation")
    end

    local original_direction = entity.direction
    local new_direction = original_direction

    if p.direction then
        -- Normalize direction parameter
        local function normalize_direction(dir)
            if type(dir) == "number" then return dir end
            if type(dir) == "string" then
                local key = string.lower(dir)
                if GameState.aliases and GameState.aliases.direction then
                    return GameState.aliases.direction[key]
                end
            end
            return nil
        end

        local target_direction = normalize_direction(p.direction)
        if target_direction == nil then
            error("Invalid direction value: " .. tostring(p.direction))
        end

        -- Check if already in target direction (no-op)
        if original_direction == target_direction then
            return self:_post_run({
                unit_number = entity.unit_number,
                direction = entity.direction,
                original_direction = original_direction,
                new_direction = new_direction,
                no_op = true,
                message = "Entity already in requested direction",
                affected_unit_numbers = { entity.unit_number }
            }, p)
        end

        -- Set specific direction
        entity.direction = target_direction
        new_direction = target_direction
    else
        -- Rotate 45 degrees clockwise (default behavior)
        entity.rotate()
        new_direction = entity.direction
    end

    local result = {
        unit_number = entity.unit_number,
        direction = entity.direction,
        original_direction = original_direction,
        new_direction = new_direction,
        affected_unit_numbers = { entity.unit_number }
    }
    
    return self:_post_run(result, p)
end

return RotateEntityAction
