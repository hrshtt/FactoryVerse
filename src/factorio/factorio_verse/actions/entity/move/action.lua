local Action = require("core.action.Action")
local ParamSpec = require("core.action.ParamSpec")
local GameState = require("core.game_state.GameState")

local gs = GameState:new()

--- @class MoveEntityParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field unit_number number Unit number of entity to move
--- @field new_position table New position: { x = number, y = number }
local MoveEntityParams = ParamSpec:new({
    agent_id = { type = "number", required = true },
    unit_number = { type = "number", required = true },
    new_position = { type = "table", required = true }
})

--- @class MoveEntityAction : Action
local MoveEntityAction = Action:new("entity.move", MoveEntityParams)

--- @param params MoveEntityParams
--- @return table result Data about the moved entity
function MoveEntityAction:run(params)
    local p = self:_pre_run(gs, params)
    ---@cast p MoveEntityParams

    local agent = gs:agent_state():get_agent(p.agent_id)
    local surface = gs:get_surface()

    -- Find the entity to move
    local entity = game.get_entity_by_unit_number(p.unit_number)
    if not entity or not entity.valid then
        error("Entity not found: " .. tostring(p.unit_number))
    end

    -- Check if agent can reach the entity
    local agent_position = agent.position
    local entity_position = entity.position
    local distance = math.sqrt((agent_position.x - entity_position.x)^2 + (agent_position.y - entity_position.y)^2)
    
    if distance > 10 then -- Reasonable reach distance
        error("Entity too far away to move")
    end

    -- Check if new position is valid
    local can_place = surface.can_place_entity{
        name = entity.name,
        position = p.new_position,
        direction = entity.direction,
        force = entity.force
    }
    if not can_place then
        error("Cannot place entity at the new position")
    end

    -- Capture old position for chunk boundary checking
    local old_position = entity.position
    local old_chunk_x = math.floor(old_position.x / 32)
    local old_chunk_y = math.floor(old_position.y / 32)
    
    -- Move the entity
    entity.teleport(p.new_position)

    local new_chunk_x = math.floor(p.new_position.x / 32)
    local new_chunk_y = math.floor(p.new_position.y / 32)
    
    -- Check if entity moved across chunk boundaries
    local crossed_chunk_boundary = (old_chunk_x ~= new_chunk_x) or (old_chunk_y ~= new_chunk_y)

    local result = {
        -- Entity data after move
        moved_entity = {
            name = entity.name,
            position = entity.position,
            direction = entity.direction,
            unit_number = entity.unit_number,
            type = entity.type,
            force = entity.force and entity.force.name or nil
        },
        old_position = old_position,
        new_position = p.new_position,
        crossed_chunk_boundary = crossed_chunk_boundary,
        -- Mutation contract fields
        affected_unit_numbers = { p.unit_number },
        -- If crossed chunk boundary, we need to remove from old chunk and add to new chunk
        -- The mutation tracker will handle this based on the entity's current position
    }
    
    return self:_post_run(result, p)
end

return MoveEntityAction
