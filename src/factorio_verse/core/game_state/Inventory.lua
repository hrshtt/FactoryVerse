--- factorio_verse/core/game_state/InventoryGameState.lua
--- InventoryGameState sub-module for managing inventory-related functionality.

local GameStateError = require("core.Error")

--- @class InventoryGameState
--- @field game_state GameState
local InventoryGameState = {}
InventoryGameState.__index = InventoryGameState

--- @param game_state GameState
--- @return InventoryGameState
function InventoryGameState:new(game_state)
    local instance = {
        game_state = game_state,
    }

    setmetatable(instance, self)
    return instance
end

--- Get the contents of an inventory for any entity supporting inventories.
--- @param entity LuaEntity|LuaPlayer|LuaControl The entity or player to get inventory from
--- @param inventory_type defines.inventory (optional) The inventory type (default: character_main)
--- @return table|GameStateError
function InventoryGameState:get_inventory_contents(entity, inventory_type)
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
function InventoryGameState:check_item_in_inventory(entity, item_name, inventory_type)
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
function InventoryGameState:serialize_entity_inventories(entity)
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

return InventoryGameState
