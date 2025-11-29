--[[
Test Grid Module - Deterministic Test Layout

This module provides coordinates for the 3x3 grid layout used in test_scenario.
The map is 1024x1024 tiles with a centered 600x600 test block.

Grid Structure:
- 9 sections of 192x192 tiles each
- 6-tile gaps between sections and at edges
- Total: (192*3) + (6*4) = 600x600 block
- Block centered at (0,0), extending from -300 to +300 in both axes

Semantic Test Categories:
- top_left: Entities (placement, removal, rotation, etc.)
- top_middle: Resources (mining operations)
- top_right: Inventories (transfer, limits, etc.)
- middle_left: Crafting (recipe setting, enqueue/dequeue)
- middle_middle: Movements (maze navigation)
- middle_right: Observability (snapshot generation, multi-chunk testing, Python verification)
- bottom_left: (reserved)
- bottom_middle: (reserved)
- bottom_right: (reserved)
--]]

local TestGrid = {}

-- Grid section dimensions
TestGrid.SECTION_SIZE = 192  -- tiles
TestGrid.GAP_SIZE = 6        -- tiles
TestGrid.BLOCK_SIZE = 600    -- tiles (3 sections + 4 gaps)
TestGrid.MAP_SIZE = 1024     -- tiles

-- The centered 600x600 test block boundaries
TestGrid.BLOCK_BOUNDS = {
    left = -300,
    right = 300,
    top = 300,
    bottom = -300
}

-- 3x3 Grid Areas
TestGrid.AREAS = {
    -- Top row
    top_left = {
        name = "top_left",
        category = "entities",
        description = "Entities: placement, removal, rotation, pick up",
        bounds = {left = -294, right = -102, top = 96, bottom = 288},
        center = {x = -198, y = 192}
    },
    top_middle = {
        name = "top_middle",
        category = "resources",
        description = "Resources: mining operations and resource handling",
        bounds = {left = -96, right = 96, top = 96, bottom = 288},
        center = {x = 0, y = 192}
    },
    top_right = {
        name = "top_right",
        category = "inventories",
        description = "Inventories: transfer operations, limits, item management",
        bounds = {left = 102, right = 294, top = 96, bottom = 288},
        center = {x = 198, y = 192}
    },
    
    -- Middle row
    middle_left = {
        name = "middle_left",
        category = "crafting",
        description = "Crafting: recipe setting, enqueue, dequeue, sync",
        bounds = {left = -294, right = -102, top = -96, bottom = 96},
        center = {x = -198, y = 0}
    },
    middle_middle = {
        name = "middle_middle",
        category = "movements",
        description = "Movements: navigation, maze traversal, teleport",
        bounds = {left = -96, right = 96, top = -96, bottom = 96},
        center = {x = 0, y = 0}
    },
    middle_right = {
        name = "middle_right",
        category = "observability",
        description = "Observability: snapshot generation spanning multiple chunks, disk writes, Python verification",
        bounds = {left = 102, right = 294, top = -96, bottom = 96},
        center = {x = 198, y = 0}
    },
    
    -- Bottom row
    bottom_left = {
        name = "bottom_left",
        category = "reserved",
        description = "Reserved for future test categories",
        bounds = {left = -294, right = -102, top = -294, bottom = -102},
        center = {x = -198, y = -198}
    },
    bottom_middle = {
        name = "bottom_middle",
        category = "reserved",
        description = "Reserved for future test categories",
        bounds = {left = -96, right = 96, top = -294, bottom = -102},
        center = {x = 0, y = -198}
    },
    bottom_right = {
        name = "bottom_right",
        category = "reserved",
        description = "Reserved for future test categories",
        bounds = {left = 102, right = 294, top = -294, bottom = -102},
        center = {x = 198, y = -198}
    }
}

-- Helper functions

--- Get area by name
--- @param area_name string
--- @return table|nil
function TestGrid.get_area(area_name)
    return TestGrid.AREAS[area_name]
end

--- Get all areas for a specific category
--- @param category string
--- @return table
function TestGrid.get_areas_by_category(category)
    local areas = {}
    for name, area in pairs(TestGrid.AREAS) do
        if area.category == category then
            table.insert(areas, area)
        end
    end
    return areas
end

--- Get a position within a grid area with optional offset
--- @param area_name string
--- @param offset_x number|nil
--- @param offset_y number|nil
--- @return table
function TestGrid.get_position_in_area(area_name, offset_x, offset_y)
    local area = TestGrid.get_area(area_name)
    if not area then
        error("Invalid area name: " .. tostring(area_name))
    end
    
    local x = (offset_x or 0) + area.center.x
    local y = (offset_y or 0) + area.center.y
    
    return {x = x, y = y}
end

--- Validate a position is within the specified area bounds
--- @param area_name string
--- @param position table
--- @return boolean
function TestGrid.is_position_in_area(area_name, position)
    local area = TestGrid.get_area(area_name)
    if not area then
        return false
    end
    
    local bounds = area.bounds
    return position.x >= bounds.left 
       and position.x <= bounds.right
       and position.y >= bounds.bottom
       and position.y <= bounds.top
end

return TestGrid

