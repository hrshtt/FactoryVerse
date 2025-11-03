local GameState = require "core.game_state.GameState"
local utils = require "utils"

--- Component Schema Definition for ResourceSnapshot
local ComponentSchema = {
    -- Resources component
    resources = {
        fields = {
            kind = "string",
            x = "number",
            y = "number",
            amount = "number"
        },
        flatten_rules = {}
    },

    -- Rocks component
    rocks = {
        fields = {
            name = "string",
            type = "string",
            resource_json = "json",
            size = "number",
            position_x = "number",
            position_y = "number",
            chunk_x = "number",
            chunk_y = "number"
        },
        flatten_rules = {
            position = { x = "position_x", y = "position_y" },
            chunk = { x = "chunk_x", y = "chunk_y" },
            resources = "resource_json" -- Map to _json suffixed field
        }
    },

    -- Trees component
    trees = {
        fields = {
            name = "string",
            position_x = "number",
            position_y = "number",
            bounding_box_min_x = "number",
            bounding_box_min_y = "number",
            bounding_box_max_x = "number",
            bounding_box_max_y = "number",
            chunk_x = "number",
            chunk_y = "number",
        },
        flatten_rules = {
            position = { x = "position_x", y = "position_y" },
            chunk = { x = "chunk_x", y = "chunk_y" },
            bounding_box = {
                min_x = "bounding_box_min_x",
                min_y = "bounding_box_min_y",
                max_x = "bounding_box_max_x",
                max_y = "bounding_box_max_y"
            }
        }
    },

    -- Resource yields component (for recurring snapshots)
    resource_yields = {
        fields = {
            x = "number",
            y = "number",
            kind = "string",
            amount = "number",
            tick = "number"
        },
        flatten_rules = {}
    }
}

--- ResourceSnapshot: View module for resource data
--- @class ResourceSnapshot
local ResourceSnapshot = {}

--- Get headers for a component type
--- @param component_type string - component type
--- @return table - array of header strings
function ResourceSnapshot:_get_headers(component_type)
    local schema = ComponentSchema[component_type]
    if not schema then
        error("Unknown component type: " .. tostring(component_type))
    end

    local headers = {}
    for field, _ in pairs(schema.fields) do
        table.insert(headers, field)
    end
    return headers
end

--- Flatten data according to component schema
--- @param component_type string - component type
--- @param data table - data to flatten
--- @return table - flattened data
function ResourceSnapshot:_flatten_data(component_type, data)
    local schema = ComponentSchema[component_type]
    if not schema then
        error("Unknown component type: " .. tostring(component_type))
    end

    local flattened = {}
    local rules = schema.flatten_rules or {}

    -- Apply flattening rules
    for field, rule in pairs(rules) do
        if data[field] then
            if type(rule) == "table" then
                -- Nested object flattening
                for subfield, target_field in pairs(rule) do
                    if data[field][subfield] ~= nil then
                        flattened[target_field] = data[field][subfield]
                    end
                end
            elseif type(rule) == "string" then
                -- Direct field mapping
                flattened[rule] = data[field]
            end
        end
    end

    -- Copy remaining fields
    for field, _ in pairs(schema.fields) do
        if data[field] ~= nil and not flattened[field] then
            flattened[field] = data[field]
        end
    end

    return flattened
end

-- ============================================================================
-- VIEW METHODS (called by Snapshot orchestrator)
-- ============================================================================

--- Serialize a single resource tile
--- @param entity LuaEntity - the resource entity
--- @param resource_name string - the resource name
--- @return table - serialized resource data
function ResourceSnapshot.serialize_resource_tile(entity, resource_name)
    return {
        kind = resource_name,
        x = utils.floor(entity.position.x),
        y = utils.floor(entity.position.y),
        amount = entity.amount or 0
    }
end

--- Serialize a rock entity
--- @param entity LuaEntity - the rock entity
--- @param chunk table - {x, y, area}
--- @return table - serialized rock data
function ResourceSnapshot.serialize_rock(entity, chunk)
    local size = 1
    if entity.name:match("huge") then
        size = 3
    elseif entity.name:match("big") then
        size = 2
    end

    local resources = {}
    if entity.prototype and entity.prototype.mineable_properties and entity.prototype.mineable_properties.products then
        for _, product in pairs(entity.prototype.mineable_properties.products) do
            table.insert(resources, {
                name = product.name,
                amount = product.amount or product.amount_min or 1,
                probability = product.probability or 1
            })
        end
    end

    return {
        name = entity.name,
        type = entity.type,
        position = entity.position,
        size = size,
        resources = resources,
        chunk = { x = chunk.x, y = chunk.y }
    }
end

--- Serialize a tree entity
--- @param entity LuaEntity - the tree entity
--- @param chunk table - {x, y, area}
--- @return table - serialized tree data
function ResourceSnapshot.serialize_tree(entity, chunk)
    return {
        name = entity.name,
        position = entity.position,
        bounding_box = {
            min_x = entity.bounding_box.left_top.x,
            min_y = entity.bounding_box.left_top.y,
            max_x = entity.bounding_box.right_bottom.x,
            max_y = entity.bounding_box.right_bottom.y
        },
        chunk = { x = chunk.x, y = chunk.y }
    }
end

--- Convert array of tables to CSV
--- @param data table - array of data rows
--- @param headers table - column headers
--- @return string - CSV content
function ResourceSnapshot._array_to_csv(data, headers)
    if #data == 0 then
        return table.concat(headers, ",") .. "\n"
    end

    local csv_lines = { table.concat(headers, ",") }
    for _, row in ipairs(data) do
        table.insert(csv_lines, ResourceSnapshot._table_to_csv_row(row, headers))
    end
    return table.concat(csv_lines, "\n") .. "\n"
end

--- Convert a single data row to CSV
--- @param data table - data row
--- @param headers table - column headers
--- @return string - CSV row
function ResourceSnapshot._table_to_csv_row(data, headers)
    local values = {}
    for _, header in ipairs(headers) do
        local value = data[header] or ""
        if type(value) == "table" then
            value = helpers.table_to_json(value)
        end
        table.insert(values, tostring(value))
    end
    return table.concat(values, ",")
end

return ResourceSnapshot
