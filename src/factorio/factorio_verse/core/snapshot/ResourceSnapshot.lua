local Snapshot = require "core.snapshot.Snapshot":new()

local ResourceSnapshot = {}
ResourceSnapshot.__index = ResourceSnapshot

function ResourceSnapshot:new()
    local instance = {}
    setmetatable(instance, self)
    return instance
end

return ResourceSnapshot