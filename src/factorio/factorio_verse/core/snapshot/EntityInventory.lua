local Snapshot = require "core.snapshot.Snapshot"
local GameState = require "core.game_state.GameState"
local utils = require "utils"

--- EntityInventory: On-demand entity inventory snapshots
--- Captures entity inventory on-demand via remote call
--- @class EntityInventory : Snapshot
local EntityInventory = Snapshot:new()
EntityInventory.__index = EntityInventory

---@return EntityInventory
function EntityInventory:new()
    local instance = Snapshot:new()
    setmetatable(instance, self)
    ---@cast instance EntityInventory
    return instance
end

--- Take inventory snapshot for a specific entity
--- @param unit_number number - entity unit number
--- @return table - inventory data as JSON
function EntityInventory:take(unit_number)
    log("Taking entity inventory snapshot for unit " .. tostring(unit_number))

    local surface = self.game_state:get_surface()
    if not surface then
        local error_result = {
            error = "No surface available",
            unit_number = unit_number,
            tick = game and game.tick or 0
        }
        utils.triple_print(helpers.table_to_json(error_result))
        return error_result
    end

    -- Find entity by unit_number
    local entity = nil
    for _, e in pairs(surface.find_entities_filtered{}) do
        if e.valid and e.unit_number == unit_number then
            entity = e
            break
        end
    end

    if not entity then
        local error_result = {
            error = "Entity not found",
            unit_number = unit_number,
            tick = game and game.tick or 0
        }
        utils.triple_print(helpers.table_to_json(error_result))
        return error_result
    end

    -- Collect all inventory types for this entity
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
        character_main = defines.inventory.character_main,
        character_guns = defines.inventory.character_guns,
        character_ammo = defines.inventory.character_ammo,
        character_armor = defines.inventory.character_armor,
        character_vehicle = defines.inventory.character_vehicle,
        character_trash = defines.inventory.character_trash
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

    local result = {
        unit_number = unit_number,
        tick = game and game.tick or 0,
        inventories = inventories
    }

    utils.triple_print(helpers.table_to_json(result))
    return result
end

return EntityInventory
