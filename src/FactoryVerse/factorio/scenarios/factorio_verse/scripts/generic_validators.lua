---@type Validator
local Validator = require("scripts.validator")
local errors    = require("scripts.errors")

-- run on every action that has a .parameters.position
---@type ActionKind[]
local _position_actions = { "build", "mine", "move_to", "transfer" }

for _, action_type in ipairs(_position_actions) do
    Validator.register(action_type, function(ctx)
        local p   = ctx.action.parameters
        local pos = p.position
        local map = ctx.meta.map_settings

        if pos.x < map.min_x
            or pos.x > map.max_x
            or pos.y < map.min_y
            or pos.y > map.max_y
        then
            return errors.map({}, "Out of bounds", { entity = p.entity_name, position = pos })
        end
    end)
end

Validator.register("build", function(ctx)
    local player = ctx.gamestate.players[ctx.action.agent_index]
    local entity_name = ctx.action.parameters.entity_name
    local position = ctx.action.parameters.position
    local direction = ctx.action.parameters.direction

    local errors_list = {}

    local inventory = player.get_inventory(defines.inventory.character_main)
    if not inventory then
        table.insert(errors_list, errors.engine({}, "No inventory found for player", { player = player }))
    end

    local es = defines.prototypes["entity"]
    if not prototypes[entity_name] then
        table.insert(errors_list, errors.agent({}, "Invalid entity name", { entity_name = entity_name }))
    end

    if inventory.get_item_count(entity_name) == 0 then
        table.insert(errors_list, errors.agent({}, "No " .. entity_name .. " in inventory", { inventory = inventory }))
    end

    local can_place = player.surface.can_place_entity(entity_name, position, direction)

    if not can_place then
        table.insert(errors_list, errors.agent({}, "Cannot place " .. entity_name .. " at " .. position.x .. ", " .. position.y,
            { position = position }))
    end

    return errors_list
end)
