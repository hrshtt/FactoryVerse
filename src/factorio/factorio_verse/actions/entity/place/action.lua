local Action = require("core.action.Action")
local ParamSpec = require("core.action.ParamSpec")
local validator_registry = require("core.action.ValidatorRegistry"):new()
local GameState = require("core.game_state.GameState")

local validators = validator_registry:get_validations("entity.place")

local gs = GameState:new()

--- @class PlaceEntityParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field name string Prototype name of the entity to place (e.g., "assembling-machine-1")
--- @field position table Position to place at: { x = number, y = number }
--- @field direction string|number Optional direction; accepts alias from GameState.aliases.direction or defines.direction value
--- @field force string|nil Optional force name; defaults to agent force
--- @field fast_replace boolean|nil Whether to allow fast replace when supported
--- @field raise_built boolean|nil Raise on_built event
--- @field create_build_effect_smoke boolean|nil Show build effect smoke when applicable
--- @field move_stuck_players boolean|nil Move players if stuck in entity placement
--- @field spawn_decorations boolean|nil Spawn decorations for entity placement
local PlaceEntityParams = ParamSpec:new({
    agent_id = { type = "number", required = true },
    name = { type = "string", required = true },
    position = { type = "table", required = true },
    direction = { type = "any", required = false },
    force = { type = "string", required = false },
    fast_replace = { type = "boolean", required = false },
    raise_built = { type = "boolean", required = false },
    create_build_effect_smoke = { type = "boolean", required = false },
    move_stuck_players = { type = "boolean", required = false },
    spawn_decorations = { type = "boolean", required = false }
})

--- @class PlaceEntityAction : Action
local PlaceEntityAction = Action:new("entity.place", PlaceEntityParams, validators)

--- @param params PlaceEntityParams
--- @return table result Data about the placed entity
function PlaceEntityAction:run(params)
    local p = self:_pre_run(gs, params)
    ---@cast p PlaceEntityParams

    local agent = gs:agent_state():get_agent(p.agent_id)
    if not agent then
        error("Agent not found for id " .. tostring(params.agent_id))
    end

    local surface = gs.surface
    if not surface then
        error("No surface available to place entity")
    end

    local placement = {
        name = p.name,
        position = p.position,
        force = p.force or agent.force,
    }

    local function normalize_direction(dir)
        if dir == nil then return nil end
        if type(dir) == "number" then return dir end
        if type(dir) == "string" then
            local key = string.lower(dir)
            if GameState.aliases and GameState.aliases.direction then
                return GameState.aliases.direction[key]
            end
        end
        return nil
    end

    local dir = normalize_direction(p.direction)
    if type(dir) == "number" then
        placement.direction = dir
    end

    if p.fast_replace ~= nil then
        placement.fast_replace = p.fast_replace
    end
    if p.raise_built ~= nil then
        placement.raise_built = p.raise_built
    end
    if p.create_build_effect_smoke ~= nil then
        placement.create_build_effect_smoke = p.create_build_effect_smoke
    end
    if p.move_stuck_players ~= nil then
        placement.move_stuck_players = p.move_stuck_players
    end
    if p.spawn_decorations ~= nil then
        placement.spawn_decorations = p.spawn_decorations
    end

    local entity = surface.create_entity(placement)
    if not entity then
        error("Failed to place entity: " .. p.name)
    end

    local result = {
        name = entity.name,
        position = entity.position,
        direction = entity.direction,
        unit_number = entity.unit_number,
        type = entity.type,
        force = entity.force and entity.force.name or nil
    }
    return self:_post_run(result, p)
end

return PlaceEntityAction


