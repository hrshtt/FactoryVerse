local Snapshot = require "core.Snapshot"
local utils = require "utils"

--- ResourceSnapshot: Schema-driven resource and tile data extraction
---
--- DESIGN DECISIONS:
--- 1. Schema-driven component system for maintainable data extraction
--- 2. Declarative flattening configuration for consistent output
--- 3. Automatic header generation from data structure
--- 4. Chunked processing for memory efficiency
---
--- OUTPUT: Resource data with schema-driven CSV generation
--- @class ResourceSnapshot : Snapshot
local ResourceSnapshot = Snapshot:new()
ResourceSnapshot.__index = ResourceSnapshot

-- COMPONENT DEFINITIONS: Schema-driven with declarative flattening configuration
local COMPONENTS = {
    resource_tiles = {
        name = "resource_tiles",
        flatten_config = {
            position = "coordinates",  -- position -> position_x, position_y
            chunk = "coordinates",     -- chunk -> chunk_x, chunk_y
        },
        extract = function(row)
            return {
                kind = row.kind,
                position = row.position,
                amount = row.amount,
                chunk = row.chunk
            }
        end,
        should_include = function(row) 
            return row.kind ~= nil -- Only include actual resource tiles
        end
    },

    resource_rocks = {
        name = "resource_rocks", 
        flatten_config = {
            position = "coordinates",  -- position -> position_x, position_y
            chunk = "coordinates",     -- chunk -> chunk_x, chunk_y
        },
        extract = function(row)
            return {
                name = row.name,
                position = row.position,
                size_hint = row.size_hint,
                chunk = row.chunk
            }
        end,
        should_include = function(row) 
            return row.name ~= nil -- Only include actual rocks
        end
    }
}

---@return ResourceSnapshot
function ResourceSnapshot:new()
    local instance = Snapshot:new()
    setmetatable(instance, self)
    ---@cast instance ResourceSnapshot
    return instance
end

function ResourceSnapshot:take()
    log("Taking resource snapshot")

    local surface = self.game_state:get_surface()
    if not surface then
        return self:_create_empty_output()
    end

    -- Process all resource data using parent class chunk processing
    local all_resource_data = self:process_charted_chunks(function(chunk)
        return self:_extract_resources_from_chunk(surface, chunk)
    end)
    
    -- Separate tiles and rocks into different arrays
    local all_tiles = {}
    local all_rocks = {}
    
    for _, chunk_resources in ipairs(all_resource_data) do
        for _, resource in ipairs(chunk_resources) do
            if resource.kind then
                -- This is a resource tile
                table.insert(all_tiles, resource)
            elseif resource.name then
                -- This is a rock entity
                table.insert(all_rocks, resource)
            end
        end
    end

    -- Generate component data and emit CSVs using schema-driven approach
    local component_counts = {}
    
    -- Process resource tiles
    local tiles_result = self:process_component_schema_driven(all_tiles, COMPONENTS.resource_tiles)
    component_counts.resource_tiles_rows = #tiles_result.data
    self:_emit_component_csv_schema_driven(tiles_result, COMPONENTS.resource_tiles)
    
    -- Process rocks
    local rocks_result = self:process_component_schema_driven(all_rocks, COMPONENTS.resource_rocks)
    component_counts.resource_rocks_rows = #rocks_result.data
    self:_emit_component_csv_schema_driven(rocks_result, COMPONENTS.resource_rocks)

    local output = self:create_output("snapshot.resources", "v2", component_counts)
    self:print_summary(output, function(out)
        return {
            surface = out.surface,
            tick = out.timestamp,
            resources = out.data
        }
    end)

    return output
end

-- PRIVATE METHODS --------------------------------------------------------

--- Create empty output structure
function ResourceSnapshot:_create_empty_output()
    local empty_data = {}
    for comp_key, _ in pairs(COMPONENTS) do
        empty_data[comp_key .. "_rows"] = 0
    end
    
    return self:create_output("snapshot.resources", "v2", empty_data)
end

--- Extract resource data from a single chunk
--- @param surface table - game surface
--- @param chunk table - chunk with x, y, area properties
--- @return table - array of serialized resources from this chunk
function ResourceSnapshot:_extract_resources_from_chunk(surface, chunk)
    local chunk_resources = {}
    local chunk_field = { x = chunk.x, y = chunk.y }
    
    -- Process resource tiles in this chunk
    local resources_in_chunk = self.game_state:get_resources_in_chunks({ chunk })
    if resources_in_chunk then
        for resource_name, entities in pairs(resources_in_chunk) do
            for _, entity in ipairs(entities) do
                local x = utils.floor(entity.position.x)
                local y = utils.floor(entity.position.y)
                local amount = entity.amount or 0
                
                table.insert(chunk_resources, {
                    kind = resource_name,
                    position = { x = x, y = y },
                    amount = amount,
                    chunk = chunk_field
                })
            end
        end
    end
    
    -- Process water tiles in this chunk
    local water_data = self.game_state:get_water_tiles_in_chunks({ chunk })
    if water_data and water_data.tiles then
        for _, tile in ipairs(water_data.tiles) do
            local x, y = utils.extract_position(tile)
            if x and y then
                table.insert(chunk_resources, {
                    kind = "water",
                    position = { x = x, y = y },
                    amount = 0, -- Water has no yield
                    chunk = chunk_field
                })
            end
        end
    end
    
    -- Process rocks in this chunk
    local rocks = self:_extract_rocks_from_chunk(surface, chunk)
    for _, rock in ipairs(rocks) do
        table.insert(chunk_resources, rock)
    end
    
    return chunk_resources
end

--- Extract rocks from a specific chunk
--- @param surface table - game surface
--- @param chunk table - chunk with x, y coordinates
--- @return table - array of rock data
function ResourceSnapshot:_extract_rocks_from_chunk(surface, chunk)
    local rocks = {}
    local chunk_field = { x = chunk.x, y = chunk.y }
    
    -- Calculate chunk boundaries (32x32 tiles per chunk)
    local x0 = chunk.x * 32
    local y0 = chunk.y * 32
    local x1 = (chunk.x + 1) * 32
    local y1 = (chunk.y + 1) * 32
    
    -- Find all simple-entity types in this chunk area
    local entities = surface.find_entities_filtered({
        area = {{x0, y0}, {x1, y1}},
        type = "simple-entity",
        force = "neutral"
    })
    
    for _, entity in ipairs(entities) do
        -- Use the rock-specific filter to ensure we only get actual rocks
        if entity.prototype.count_as_rock_for_filtered_deconstruction then
            local x = utils.floor(entity.position.x)
            local y = utils.floor(entity.position.y)
            local name = entity.name
            
            -- Calculate size hint from collision box
            local collision_box = entity.prototype.collision_box
            local width = collision_box.right_bottom.x - collision_box.left_top.x
            local height = collision_box.right_bottom.y - collision_box.left_top.y
            local size_hint = math.max(math.floor(width), math.floor(height))
            
            table.insert(rocks, {
                name = name,
                position = { x = x, y = y },
                size_hint = size_hint,
                chunk = chunk_field
            })
        end
    end
    
    return rocks
end

--- Emit CSV for a specific component using schema-driven approach
function ResourceSnapshot:_emit_component_csv_schema_driven(result, component_def)
    local schema_version = "snapshot.resources.v2"
    
    -- Data is already flattened by schema-driven processing
    local flatten_fn = function(row)
        return row
    end
    
    self:emit_csv_by_chunks(result.data, component_def.name, result.headers, schema_version, flatten_fn)
end

return ResourceSnapshot
