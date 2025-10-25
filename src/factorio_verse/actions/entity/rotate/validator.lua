local ValidatorRegistry = require("core.action.ValidatorRegistry")
local GameState = require("core.game_state.GameState")

local validator_registry = ValidatorRegistry:new()

--- Validate that entity supports rotation
--- @param params table
--- @return boolean, string|nil
local function validate_entity_rotatable(params)
    if not params.unit_number then
        return true -- Let other validators handle missing unit_number
    end
    
    local entity = game.get_entity_by_unit_number(params.unit_number)
    if not entity or not entity.valid then
        return true -- Let validate_entity_exists handle this
    end
    
    if not entity.supports_direction then
        return false, "Entity does not support rotation"
    end
    
    return true
end

--- Validate direction parameter if provided
--- @param params table
--- @return boolean, string|nil
local function validate_direction(params)
    if not params.direction then
        return true -- Direction is optional
    end
    
    -- Check if direction is valid
    local function is_valid_direction(dir)
        if type(dir) == "number" then
            -- Check if it's a valid defines.direction value
            return dir >= 0 and dir <= 7
        elseif type(dir) == "string" then
            -- Check if it's a valid alias
            if GameState.aliases and GameState.aliases.direction then
                local key = string.lower(dir)
                return GameState.aliases.direction[key] ~= nil
            end
        end
        return false
    end
    
    if not is_valid_direction(params.direction) then
        return false, "Invalid direction value: " .. tostring(params.direction)
    end
    
    return true
end

-- Register validators for entity.rotate
validator_registry:register("entity.rotate", validate_entity_rotatable)
validator_registry:register("entity.rotate", validate_direction)

return validator_registry
