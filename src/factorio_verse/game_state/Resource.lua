--- factorio_verse/core/game_state/ResourceGameState.lua
--- ResourceGameState sub-module for managing resource-related functionality.

-- Module-level local references for global lookups (performance optimization)
local pairs = pairs

local GameStateError = require("types.Error")
local utils = require("utils")

--- @class ResourceGameState
--- @field game_state GameState
--- @field on_demand_snapshots table
--- @field admin_api table
local M = {}
M.__index = M

--- @param game_state GameState
--- @return ResourceGameState
function M:new(game_state)
    local instance = {
        game_state = game_state
    }

    setmetatable(instance, self)
    return instance
end

--- Serialize a single resource tile
--- @param entity LuaEntity - the resource entity
--- @param resource_name string - the resource name
--- @return table - serialized resource data
function M:serialize_resource_tile(entity, resource_name)
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
function M:serialize_rock(entity, chunk)
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
function M:serialize_tree(entity, chunk)
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



return M

