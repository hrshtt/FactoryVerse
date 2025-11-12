--- factorio_verse/core/game_state/InventoryGameState.lua
--- InventoryGameState sub-module for managing inventory-related functionality.

-- Module-level local references for global lookups (performance optimization)
local pairs = pairs

local GameStateError = require("types.Error")

--- @class InventoryGameState
--- @field game_state GameState
--- @field on_demand_snapshots table
--- @field admin_api table
local M = {}
M.__index = M

--- @param game_state GameState
--- @return InventoryGameState
function M:new(game_state)
    local instance = {
        game_state = game_state,
        -- Cache frequently-used sibling modules (constructor-level caching for performance)
        entities = game_state.entities,
    }

    setmetatable(instance, self)
    return instance
end

--- Get the contents of an inventory for any entity supporting inventories.
--- @param entity LuaEntity|LuaPlayer|LuaControl The entity or player to get inventory from
--- @param inventory_type defines.inventory (optional) The inventory type (default: character_main)
--- @return table|GameStateError
function M:get_inventory_contents(entity, inventory_type)
    if not (entity and entity.valid) then
        return GameStateError:new("Invalid entity")
    end

    inventory_type = inventory_type or defines.inventory.character_main
    local inventory = entity.get_inventory and entity.get_inventory(inventory_type) or nil
    if not inventory then
        return GameStateError:new("Inventory not found")
    end

    return inventory.get_contents()
end

--- Check if an item exists in an inventory for any entity supporting inventories.
--- @param entity LuaEntity|LuaPlayer|LuaControl The entity or player to check
--- @param item_name string The item name to check for
--- @param inventory_type defines.inventory (optional) The inventory type (default: character_main)
--- @return boolean, GameStateError|nil
function M:check_item_in_inventory(entity, item_name, inventory_type)
    if not (entity and entity.valid) then
        return false, GameStateError:new("Invalid entity")
    end
    local contents, err = self:get_inventory_contents(entity, inventory_type)
    if not contents or type(contents) ~= "table" or contents.message then
        -- contents might be a GameStateError object
        local error_msg = (contents and contents.message) or (err and err.message) or "unknown error"
        return false, err or contents
    end

    -- Factorio's get_contents() returns an array of {name, count, quality} objects
    -- We need to iterate through the array to find the item
    for _, item in pairs(contents) do
        if item.name == item_name and item.count > 0 then
            return true
        end
    end

    return false
end

--- Serialize all inventories for an entity (snapshot helper).
--- Collects contents from all inventory types the entity supports.
--- @param entity LuaEntity|LuaPlayer|LuaControl The entity to serialize inventories for
--- @return table|GameStateError - inventory contents by type name (e.g., {chest = {...}, input = {...}}) or error
function M:serialize_entity_inventories(entity)
    if not (entity and entity.valid) then
        return GameStateError:new("Invalid entity")
    end

    local inventories = {}
    local inventory_types = {
        chest = defines.inventory.chest,
        fuel = defines.inventory.fuel,
        burnt_result = defines.inventory.burnt_result,
        input = defines.inventory.assembling_machine_input,
        output = defines.inventory.assembling_machine_output,
        modules = defines.inventory.assembling_machine_modules,
        ammo = defines.inventory.turret_ammo,
        trunk = defines.inventory.car_trunk,
        cargo = defines.inventory.cargo_wagon,
    }

    for inventory_name, inventory_type in pairs(inventory_types) do
        local success, inventory = pcall(function()
            return entity.get_inventory(inventory_type)
        end)

        if success and inventory and inventory.valid then
            local contents = inventory.get_contents()
            if contents and next(contents) ~= nil then
                inventories[inventory_name] = contents
            end
        end
    end

    return inventories
end

function M:clear_inventory(input)
    local entity = self.entities:get_entity(input)
    if not (entity and entity.valid) then
        return GameStateError:new("Invalid entity")
    end
    local inventories = self:serialize_entity_inventories(entity)
    if not inventories or type(inventories) ~= "table" or inventories.message then
        return GameStateError:new("Failed to serialize inventories")
    end
    for inventory_name, inventory_contents in pairs(inventories) do
        for item_name, item_count in pairs(inventory_contents) do
            entity.get_inventory(inventory_name).remove({ name = item_name, count = item_count })
        end
    end
    return true
end

function M:inspect_inventory(input)
    local entity = self.entities:get_entity(input)
    if not (entity and entity.valid) then
        return GameStateError:new("Invalid entity")
    end
    local inventories = self:serialize_entity_inventories(entity)
    if not inventories or type(inventories) ~= "table" or inventories.message then
        return GameStateError:new("Failed to serialize inventories")
    end
    local json_string = helpers.table_to_json(inventories)
    rcon.print(json_string)
end

M.on_demand_snapshots= { inspect_inventory = M.inspect_inventory }

M.admin_api = {
    clear_inventory = M.clear_inventory,
    inspect_inventory = M.inspect_inventory,
}

return M
