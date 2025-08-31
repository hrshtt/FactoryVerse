local Snapshot = require "core.Snapshot"
local utils = require "utils"

--- EntitiesSnapshot: Detects and analyzes resource patches and water bodies
--- 
--- DESIGN DECISIONS:
--- 1. Resource patches = connected groups of same resource type using 4-neighbor connectivity
--- 2. Water patches = connected areas of water tiles using flood-fill  
--- 3. Cross-chunk processing in raster order enables efficient boundary reconciliation
--- 4. Uses scanline Connected Component Labeling (CCL) for resources
--- 5. Uses Factorio's get_connected_tiles() for water (more efficient than manual flood-fill)
---
--- OUTPUT: Structured data suitable for JSON export and SQL analysis
local EntitiesSnapshot = Snapshot:new()
EntitiesSnapshot.__index = EntitiesSnapshot

function EntitiesSnapshot:new()
    local instance = Snapshot:new()
    setmetatable(instance, self)
    return instance
end

return EntitiesSnapshot