local Action = require("types.Action")
local GameContext = require("types.GameContext")
local utils = require("utils.utils")

local DIR_IDX_TO_ENUM = {
    [0] = defines.direction.east,
    [1] = defines.direction.southeast,
    [2] = defines.direction.south,
    [3] = defines.direction.southwest,
    [4] = defines.direction.west,
    [5] = defines.direction.northwest,
    [6] = defines.direction.north,
    [7] = defines.direction.northeast
}

--- Diagnose entity-specific placement requirements
--- @param entity_name string Entity prototype name
--- @param position table Position to check: {x: number, y: number}
--- @param surface LuaSurface Surface to check on
--- @return table|nil Diagnostic information or nil if no specific requirements
local function diagnose_placement_requirements(entity_name, position, surface)
    local diagnostics = {}
    local proto = prototypes and prototypes.entity and prototypes.entity[entity_name]
    if not proto then
        return nil
    end

    -- Pump jack: must be on crude oil tile
    if entity_name == "pumpjack" then
        -- Check if there's a crude oil resource at this position
        local crude_oil_resources = surface.find_entities_filtered({
            position = position,
            radius = 0.5, -- Check immediate tile
            type = "resource",
            name = "crude-oil"
        })
        if #crude_oil_resources == 0 then
            diagnostics.error = "Pump jack must be placed on a crude oil resource tile"
            diagnostics.requirement = "crude_oil_tile"
            diagnostics.found = false
        else
            diagnostics.found = true
            diagnostics.crude_oil_tile = {
                position = crude_oil_resources[1].position,
                amount = crude_oil_resources[1].amount
            }
        end
        return diagnostics
    end

    -- Electric mining drill: check resources in mining area
    if entity_name == "electric-mining-drill" or entity_name == "burner-mining-drill" then
        -- Estimate mining area based on entity type
        -- Electric mining drill typically has 2x2 mining area, burner has 1x1
        -- We use a conservative estimate: electric = 2 tiles radius, burner = 1 tile radius
        local radius = (entity_name == "electric-mining-drill") and 2.0 or 1.0
        local mining_area = {
            left_top = { x = position.x - radius, y = position.y - radius },
            right_bottom = { x = position.x + radius, y = position.y + radius }
        }
        
        -- Count resources in the estimated mining area
        local resources = surface.find_entities_filtered({
            area = mining_area,
            type = "resource"
        })
        
        local resource_count = 0
        local resource_details = {}
        for _, resource in ipairs(resources) do
            if resource and resource.valid then
                resource_count = resource_count + 1
                table.insert(resource_details, {
                    name = resource.name,
                    position = { x = resource.position.x, y = resource.position.y },
                    amount = resource.amount
                })
            end
        end
        
        diagnostics.estimated_mining_area = {
            left_top = { x = mining_area.left_top.x, y = mining_area.left_top.y },
            right_bottom = { x = mining_area.right_bottom.x, y = mining_area.right_bottom.y }
        }
        diagnostics.resource_count = resource_count
        diagnostics.resources = resource_details
        if resource_count == 0 then
            diagnostics.error = "Electric mining drill must be placed on tiles containing minable resources"
            diagnostics.requirement = "minable_resources"
        end
        return diagnostics
    end

    -- Offshore pump: requires adjacent 3x2 continuous water tiles
    -- TODO: Offshore pump validation should use snapshot method to find valid tiles across all chunks
    -- Human players are privy to visual cues on where to place the pump, so validation is not the
    -- way we'd want to teach the agent to fix its placement for this entity.
    -- Instead, use snapshot data to provide valid placement locations.
    if entity_name == "offshore-pump" then
        diagnostics.requirement = "water_tiles_3x2"
        diagnostics.note = "Offshore pump requires adjacent 3x2 continuous water tiles. Use snapshot method to find valid locations."
        -- Note: We don't validate here as per TODO above
        return diagnostics
    end

    return nil
end

--- Get diagnostic information for placed entity (inserters, mining drills, poles)
--- @param entity LuaEntity The placed entity
--- @param surface LuaSurface Surface the entity is on
--- @return table|nil Diagnostic information
local function get_entity_diagnostics(entity, surface)
    if not entity or not entity.valid then
        return nil
    end

    local diagnostics = {}

    -- Inserters: pickup and drop positions/targets
    if entity.type == "inserter" then
        local ok_pickup, pickup_pos = pcall(function() return entity.pickup_position end)
        local ok_drop, drop_pos = pcall(function() return entity.drop_position end)
        
        if ok_pickup and pickup_pos then
            diagnostics.pickup_position = { x = pickup_pos.x, y = pickup_pos.y }
            -- Find entity at pickup position
            local pickup_entities = surface.find_entities_filtered({
                position = pickup_pos,
                radius = 0.5
            })
            if #pickup_entities > 0 then
                local pickup_targets = {}
                for _, ent in ipairs(pickup_entities) do
                    if ent and ent.valid and ent.unit_number ~= entity.unit_number then
                        table.insert(pickup_targets, {
                            unit_number = ent.unit_number,
                            name = ent.name,
                            type = ent.type,
                            position = { x = ent.position.x, y = ent.position.y }
                        })
                    end
                end
                if #pickup_targets > 0 then
                    diagnostics.pickup_targets = pickup_targets
                end
            end
        end
        
        if ok_drop and drop_pos then
            diagnostics.drop_position = { x = drop_pos.x, y = drop_pos.y }
            -- Find entity at drop position
            local drop_entities = surface.find_entities_filtered({
                position = drop_pos,
                radius = 0.5
            })
            if #drop_entities > 0 then
                local drop_targets = {}
                for _, ent in ipairs(drop_entities) do
                    if ent and ent.valid and ent.unit_number ~= entity.unit_number then
                        table.insert(drop_targets, {
                            unit_number = ent.unit_number,
                            name = ent.name,
                            type = ent.type,
                            position = { x = ent.position.x, y = ent.position.y }
                        })
                    end
                end
                if #drop_targets > 0 then
                    diagnostics.drop_targets = drop_targets
                end
            end
        end
        
        return diagnostics
    end

    -- Mining drills: resource coverage in mining area
    if entity.type == "mining-drill" then
        local ok, mining_area = pcall(function() return entity.mining_area end)
        if ok and mining_area then
            local resources = surface.find_entities_filtered({
                area = mining_area,
                type = "resource"
            })
            local resource_count = 0
            local resource_details = {}
            for _, resource in ipairs(resources) do
                if resource and resource.valid then
                    resource_count = resource_count + 1
                    table.insert(resource_details, {
                        name = resource.name,
                        position = { x = resource.position.x, y = resource.position.y },
                        amount = resource.amount
                    })
                end
            end
            diagnostics.mining_area = {
                left_top = { x = mining_area.left_top.x, y = mining_area.left_top.y },
                right_bottom = { x = mining_area.right_bottom.x, y = mining_area.right_bottom.y }
            }
            diagnostics.resource_count = resource_count
            diagnostics.resources = resource_details
        end
        return diagnostics
    end

    -- Electric poles and beacons: supply area
    if entity.type == "electric-pole" or entity.type == "beacon" then
        local ok, supply_distance = pcall(function()
            return entity.prototype.get_supply_area_distance()
        end)
        if ok and supply_distance then
            diagnostics.supply_area_distance = supply_distance
            diagnostics.supply_area = {
                center = { x = entity.position.x, y = entity.position.y },
                radius = supply_distance
            }
        end
        return diagnostics
    end

    return nil
end

--- @class PlaceEntityParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field entity_name string Prototype name of the entity to place (e.g., "assembling-machine-1")
--- @field position table Position to place at: { x = number, y = number }
--- @field direction string|number|nil Optional direction; accepts alias from defines.direction value (0-7)
--- @field orient_towards table|nil Optional orientation hint: { entity_name = string|nil, position = {x:number,y:number}|nil }
local PlaceEntityParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    entity_name = { type = "entity_name", required = true },
    position = { type = "position", required = true },
    direction = { type = "direction", required = false },
    orient_towards = { type = "table", required = false },
})

--- @class PlaceEntityAction : Action
local PlaceEntityAction = Action:new("agent.place_entity", PlaceEntityParams)

--- @class PlaceEntityContext
--- @field agent LuaEntity Agent character entity
--- @field entity_name string Entity prototype name
--- @field position table Position to place at: {x: number, y: number}
--- @field direction number|nil Direction (normalized)
--- @field orient_towards table|nil Optional orientation hint
--- @field params PlaceEntityParams ParamSpec instance for _post_run

--- Override _pre_run to build context using GameContext
--- @param params PlaceEntityParams|table|string
--- @return PlaceEntityContext
function PlaceEntityAction:_pre_run(params)
    -- Call parent to get validated ParamSpec
    local p = Action._pre_run(self, params)
    local params_table = p:get_values()

    -- Build context using GameContext
    local agent = GameContext.resolve_agent(params_table, self.game_state)

    -- Return context for run()
    return {
        agent = agent,
        entity_name = params_table.entity_name,
        position = params_table.position,
        direction = params_table.direction,
        orient_towards = params_table.orient_towards,
        params = p
    }
end

--- @param params PlaceEntityParams|table|string
--- @return table result Data about the placed entity
function PlaceEntityAction:run(params)
    --- @type PlaceEntityContext
    local context = self:_pre_run(params)

    local surface = game.surfaces[1]

    local placement = {
        name = context.entity_name,
        position = context.position,
        force = context.agent.force,
        source = context.agent,
        fast_replace = true,
        raise_built = true,
        move_stuck_players = true,
    }

    -- Direction is already normalized by ParamSpec (string aliases converted to enum numbers)
    if context.direction ~= nil then
        placement.direction = context.direction
    end

    -- If direction not provided, but orient_towards is provided, derive direction
    if (not placement.direction) and context.orient_towards then
        local target_pos = nil
        -- Prefer explicit entity lookup when both name and position are provided
        if context.orient_towards.entity_name and context.orient_towards.position then
            local ok, ent = pcall(function()
                return surface.find_entity(context.orient_towards.entity_name, context.orient_towards.position)
            end)
            if ok and ent and ent.valid then
                target_pos = ent.position
            end
        end
        -- Fallback: use provided position directly
        if (not target_pos) and context.orient_towards.position then
            target_pos = context.orient_towards.position
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
                        if a < 0 then a = a + 2 * math.pi end
                    end
                end
                local oct = math.floor(((a + math.pi / 8) % (2 * math.pi)) / (math.pi / 4))
                placement.direction = DIR_IDX_TO_ENUM[oct]
            end
        end
    end

    -- Diagnose entity-specific placement requirements before checking can_place
    local placement_diagnostics = diagnose_placement_requirements(
        context.entity_name,
        placement.position,
        surface
    )
    
    -- Logical validation: Check if placement is valid
    local can_place = surface.can_place_entity {
        name = placement.name,
        position = placement.position,
        direction = placement.direction,
        force = placement.force,
        build_check_type = defines.build_check_type.manual -- exteremely important to use manual here
    }
    if not can_place then
        -- Build detailed error message with diagnostics
        local error_msg = "Cannot place entity at the specified position"
        if placement_diagnostics and placement_diagnostics.error then
            error_msg = error_msg .. ": " .. placement_diagnostics.error
        elseif placement_diagnostics and placement_diagnostics.requirement then
            -- Provide generic error based on requirement type
            if placement_diagnostics.requirement == "crude_oil_tile" then
                error_msg = error_msg .. ": Pump jack must be placed on a crude oil resource tile"
            elseif placement_diagnostics.requirement == "minable_resources" then
                error_msg = error_msg .. ": No minable resources detected in mining area"
            end
        end
        error(error_msg)
    end
    
    -- If placement would succeed but has specific requirements, check them
    if placement_diagnostics then
        -- For pump jack: ensure crude oil tile is present
        if context.entity_name == "pumpjack" and not placement_diagnostics.found then
            error("Cannot place pump jack: " .. (placement_diagnostics.error or "Target tile does not contain crude oil"))
        end
        -- For mining drill: warn if no resources (but still allow placement if can_place says yes)
        -- This is informational, not blocking, as can_place_entity is the authoritative check
    end

    -- Logical validation: Ensure agent has the item
    local inv = context.agent.get_inventory(defines.inventory.character_main) or nil
    if not inv or inv.get_item_count(context.entity_name) <= 0 then
        error("Agent does not have item in inventory: " .. tostring(context.entity_name))
    end


    local entity = surface.create_entity(placement)
    if not entity then
        error("Failed to place entity: " .. context.entity_name)
    end   

    -- Consume one item on successful placement
    inv.remove({ name = context.entity_name, count = 1 })

    -- Get diagnostic information for placed entity (inserters, mining drills, poles)
    local entity_diagnostics = get_entity_diagnostics(entity, surface)
    
    local params_table = context.params:get_values()
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
        -- TBD: remove this and use affected_positions instead
        affected_unit_numbers = { entity.unit_number },
        affected_inventories = {
            {
                owner_type = "agent",
                owner_id = params_table.agent_id,
                inventory_type = "character_main",
                changes = { [context.entity_name] = -1 } -- Consumed one item
            }
        }
    }
    
    -- Add diagnostic information if available
    if entity_diagnostics then
        result.diagnostics = entity_diagnostics
    end
    
    -- Also include placement diagnostics if available (for informational purposes)
    if placement_diagnostics then
        result.placement_diagnostics = placement_diagnostics
    end
    
    return self:_post_run(result, context.params)
end

return { action = PlaceEntityAction, params = PlaceEntityParams }
