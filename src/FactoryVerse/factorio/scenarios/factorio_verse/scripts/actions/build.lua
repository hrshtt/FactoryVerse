-- scripts/actions/build.lua
local errors = require("scripts.errors")
-- local registry = require("scripts.core.registry")

local A = {}

A.params = {
    name      = { type = "string", required = true },
    position  = { type = "position", required = true },
    direction = { type = "uint", default = defines.direction.north }
}

---Action to build an entity on the map.
---@param agent_index number
---@param entity_name string “prototype name, e.g. 'stone-furnace'”
---@param position table {x:number, y:number}
---@param direction string (“north”|“east”|“south”|“west”)
---@return string json
---@action: build
function A.run(agent_index, entity_name, position, direction)
    local player = game.players[agent_index]
    if not player then
        return errors.agent({}, "Player not found", { agent_index = agent_index })
    end

    local entity = player.surface.create_entity{
        name = entity_name,
        position = position,
        direction = defines.direction[direction],
        raise_built = true
    }

    local inventory = player.get_inventory(defines.inventory.character_main)

    if entity and inventory then
        inventory.remove({name = entity_name, count = 1})
        return helpers.table_to_json({ entity_id = entity.unit_number })
    end

    return errors.engine({}, "Entity creation failed", { entity_name = entity_name, position = position, direction = direction })
end

-- Add the action to the remote interface
-- TODO: Add the action to the remote interface
remote.add_interface("actions", {
    build = A.run,
})

A.recorder = {}

-- add the event handler to the event dispatcher
-- @param event_dispatcher EventDispatcher
function A.recorder.register_events(event_dispatcher)
    event_dispatcher.register_handler(defines.events.on_built_entity, function(e)
        local rec = {
            action_type = "build",
            parameters = {
                entity_name = e.entity.name,
                position = e.entity.position,
                direction = e.entity.direction
            },
            agent_index = e.player_index
        }
        return rec
    end)
end

return A
