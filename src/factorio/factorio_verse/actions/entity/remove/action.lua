local Action = require("core.action.Action")
local ParamSpec = require("core.action.ParamSpec")
local GameState = require("core.game_state.GameState")

local gs = GameState:new()

--- @class RemoveEntityParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field unit_number number Unit number of entity to remove
local RemoveEntityParams = ParamSpec:new({
    agent_id = { type = "number", required = true },
    unit_number = { type = "number", required = true }
})

--- @class RemoveEntityAction : Action
local RemoveEntityAction = Action:new("entity.remove", RemoveEntityParams)

--- @param params RemoveEntityParams
--- @return table result Data about the removed entity
function RemoveEntityAction:run(params)
    local p = self:_pre_run(gs, params)
    ---@cast p RemoveEntityParams

    local agent = gs:agent_state():get_agent(p.agent_id)
    local surface = gs:get_surface()

    -- Find the entity to remove
    local entity = game.get_entity_by_unit_number(p.unit_number)
    if not entity or not entity.valid then
        error("Entity not found: " .. tostring(p.unit_number))
    end

    -- Check if agent can reach the entity
    local agent_position = agent.position
    local entity_position = entity.position
    local distance = math.sqrt((agent_position.x - entity_position.x)^2 + (agent_position.y - entity_position.y)^2)
    
    if distance > 10 then -- Reasonable reach distance
        error("Entity too far away to remove")
    end

    -- Capture entity data before removal
    local entity_data = {
        name = entity.name,
        position = entity.position,
        direction = entity.direction,
        unit_number = entity.unit_number,
        type = entity.type,
        force = entity.force and entity.force.name or nil
    }

    -- Remove the entity
    entity.destroy()

    local result = {
        -- Entity data before removal
        removed_entity = entity_data,
        -- Mutation contract fields
        removed_unit_numbers = { p.unit_number },
        affected_inventories = {
            {
                owner_type = "agent",
                owner_id = p.agent_id,
                inventory_type = "character_main",
                changes = { [entity.name] = 1 } -- Gained one item (if any)
            }
        }
    }
    
    return self:_post_run(result, p)
end

return RemoveEntityAction
