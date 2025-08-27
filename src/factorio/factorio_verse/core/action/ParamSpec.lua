--- factorio_verse/core/action/ParamSpec.lua
--- ParamSpec class for defining action parameters.

--- @class ParamSpec
--- @field spec table
local ParamSpec = {}
ParamSpec.__index = ParamSpec

function ParamSpec:new(spec)
    local instance = {
        spec = spec
    }
    setmetatable(instance, self)
    return instance
end

--- @class ParamSpec.to_json
--- @field spec table
--- @return table
function ParamSpec:to_json()
    return self.spec
end

--- @class ParamSpec.from_json
--- @field spec table
--- @return ParamSpec
function ParamSpec:from_json(spec)
    return ParamSpec:new(spec)
end

return ParamSpec