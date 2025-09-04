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

return InventoryGameState