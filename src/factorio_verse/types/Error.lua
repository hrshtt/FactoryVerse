local Error = {}
Error.__index = Error

--- @class Error
--- @field code string
--- @field message string
--- @field context table
--- @field timestamp number
function Error:new(code, message, context)
    local instance = {
        code = code or "UNKNOWN_ERROR",
        message = message or "An unknown error occurred",
        context = context or {},
        timestamp = game and game.tick or 0
    }
    setmetatable(instance, self)
    return instance
end

function Error:to_json()
    return {
        error = true,
        code = self.code,
        message = self.message,
        context = self.context,
        timestamp = self.timestamp
    }
end

function Error:__tostring()
    return string.format("[%s] %s", self.code, self.message)
end

-- Common Error Types
--- @class ValidationError
--- @field field string
--- @field value any
local ValidationError = {}
ValidationError.__index = ValidationError
setmetatable(ValidationError, Error)

---@return ValidationError
function ValidationError:new(message, field, value)
    local instance = Error.new(self, "VALIDATION_ERROR", message, {
        field = field,
        value = value
    })
    setmetatable(instance, self)
    return instance
end

--- @class GameStateError
--- @field entity_type string
--- @field position table
local GameStateError = {}
GameStateError.__index = GameStateError
setmetatable(GameStateError, Error)

function GameStateError:new(message, entity_type, position)
    local instance = Error.new(self, "GAMESTATE_ERROR", message, {
        entity_type = entity_type,
        position = position
    })
    setmetatable(instance, self)
    return instance
end
