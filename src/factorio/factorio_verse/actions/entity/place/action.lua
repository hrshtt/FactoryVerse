local Action = require("core.action.Action")
local ParamSpec = require("core.action.ParamSpec")
local GameState = require("core.game_state.GameState")
local walk = require("core.actions.agent.walk.helper")

local gs = GameState:new()

--- @class PlaceEntityParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field entity_name string Prototype name of the entity to place (e.g., "assembling-machine-1")
--- @field position table Position to place at: { x = number, y = number }
--- @field direction string|number|nil Optional direction; accepts alias from GameState.aliases.direction or defines.direction value
--- @field orient_towards table|nil Optional orientation hint: { entity_name = string|nil, position = {x:number,y:number}|nil }
--- @field walk_if_unreachable boolean|nil Optional walk_if_unreachable hint
local PlaceEntityParams = ParamSpec:new({
    agent_id = { type = "number", required = true },
    entity_name = { type = "string", required = true },
    position = { type = "table", required = true },
    direction = { type = "any", required = false },
    orient_towards = { type = "table", required = false },
    walk_if_unreachable = { type = "boolean", required = false, default = false }
})

--- @class PlaceEntityAction : Action
local PlaceEntityAction = Action:new("entity.place", PlaceEntityParams)

--- @param params PlaceEntityParams
--- @return table result Data about the placed entity
function PlaceEntityAction:run(params)
    local p = self:_pre_run(gs, params)
    ---@cast p PlaceEntityParams

    local agent = gs:agent_state():get_agent(p.agent_id)
    local surface = gs:get_surface()

    local placement = {
        name = p.entity_name,
        position = p.position,
        force = agent.force,
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

    -- If direction not provided, but orient_towards is provided, derive direction
    if (not placement.direction) and p.orient_towards then
        local target_pos = nil
        -- Prefer explicit entity lookup when both name and position are provided
        if p.orient_towards.entity_name and p.orient_towards.position then
            local ok, ent = pcall(function()
                return surface.find_entity(p.orient_towards.entity_name, p.orient_towards.position)
            end)
            if ok and ent and ent.valid then
                target_pos = ent.position
            end
        end
        -- Fallback: use provided position directly
        if (not target_pos) and p.orient_towards.position then
            target_pos = p.orient_towards.position
        end
        if target_pos then
            local dx = target_pos.x - placement.position.x
            local dy = target_pos.y - placement.position.y
            if not (dx == 0 and dy == 0) then
                local a
                do
                    local ok, angle = pcall(function() return math.atan2(dy, dx) end)
                    if ok and type(angle) == "number" then
                        a = angle
                    else
                        local denom = (dx == 0) and ((dy >= 0) and 1e-9 or -1e-9) or dx
                        a = math.atan(dy / denom)
                        if dx < 0 then
                            if dy >= 0 then a = a + math.pi else a = a - math.pi end
                        end
                        if a < 0 then a = a + 2*math.pi end
                    end
                end
                local oct = math.floor(((a + math.pi/8) % (2*math.pi)) / (math.pi/4))
                local DIR_IDX_TO_ENUM = {
                    [0]=defines.direction.east, [1]=defines.direction.southeast,
                    [2]=defines.direction.south,[3]=defines.direction.southwest,
                    [4]=defines.direction.west, [5]=defines.direction.northwest,
                    [6]=defines.direction.north,[7]=defines.direction.northeast
                }
                placement.direction = DIR_IDX_TO_ENUM[oct]
            end
        end
    end

    -- Handle walk_if_unreachable logic
    if p.walk_if_unreachable then
        local placement_reachable = walk:is_reachable(agent, p.position)
        if not placement_reachable then
            local walk_success = walk:start_walk_to({
                agent_id = p.agent_id,
                target_position = p.position,
                walk_if_unreachable = true,
                arrive_radius = 1.0, -- Close enough to place
                prefer_cardinal = true
            })
            if walk_success then
                error("Agent is walking to position. Try placing again when closer.")
            else
                error("Cannot reach position and failed to start walking")
            end
        end
    end

    -- Validate placement
    local can_place = surface.can_place_entity{
        name = placement.name,
        position = placement.position,
        direction = placement.direction,
        force = placement.force
    }
    if not can_place then
        error("Cannot place entity at the specified position")
    end

    -- Ensure agent has the item; we assume item name matches entity prototype name
    local inv = agent.get_inventory(defines.inventory.character_main) or nil
    if not inv or inv.get_item_count(p.entity_name) <= 0 then
        error("Agent does not have item in inventory: " .. tostring(p.entity_name))
    end

    local entity = surface.create_entity(placement)
    if not entity then
        error("Failed to place entity: " .. p.entity_name)
    end

    -- Consume one item on successful placement
    inv.remove({ name = p.entity_name, count = 1 })

    local result = {
        name = entity.name,
        position = entity.position,
        direction = entity.direction,
        unit_number = entity.unit_number,
        type = entity.type,
        force = entity.force and entity.force.name or nil,
        -- Initial entity status for first snapshot
        entity_status = {
            status = entity.status,
            status_name = utils.status_to_name(entity.status),
            health = entity.health
        },
        -- Mutation contract fields
        affected_unit_numbers = { entity.unit_number },
        affected_inventories = {
            {
                owner_type = "agent",
                owner_id = p.agent_id,
                inventory_type = "character_main",
                changes = { [p.entity_name] = -1 } -- Consumed one item
            }
        }
    }
    return self:_post_run(result, p)
end

return PlaceEntityAction


