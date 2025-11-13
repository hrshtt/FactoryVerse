local Action = require("types.Action")
local AsyncAction = require("types.AsyncAction")
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

--- @class PlaceInLineParams : ParamSpec
--- @field agent_id number
--- @field start_position table Position to start placing: { x = number, y = number }
--- @field end_position table Position to end placing: { x = number, y = number }
--- @field entity_name string|nil Single entity name (mutually exclusive with entities)
--- @field entities table|nil Array of entity specs to cycle through
--- @field spacing number|nil Distance between entities (default: 0.0)
--- @field skip_invalid_positions boolean|nil Continue if placement fails (default: true)
--- @field max_entities number|nil Maximum number of entities to place
--- @field dry_run boolean|nil Return validation without executing (default: false)
--- @field arrive_radius number|nil Radius for reaching end position (default: 0.5)
local PlaceInLineParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    start_position = { type = "position", required = true },
    end_position = { type = "position", required = true },
    entity_name = { type = "entity_name", required = false },
    entities = { type = "table", required = false },
    spacing = { type = "number", required = false, default = 0.0 },
    skip_invalid_positions = { type = "boolean", required = false, default = true },
    max_entities = { type = "number", required = false },
    dry_run = { type = "boolean", required = false, default = false },
    arrive_radius = { type = "number", required = false, default = 0.5 },
})

--- @class PlaceInLineCancelParams : ParamSpec
--- @field agent_id number
local PlaceInLineCancelParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
})

--- @class PlaceInLineAction : AsyncAction
local PlaceInLineAction = AsyncAction:new("agent.place_in_line", PlaceInLineParams, {
    cancel_params = PlaceInLineCancelParams,
    cancel_storage_key = "place_in_line_in_progress",
    cancel_tracking_key_fn = function(cancel_params)
        return cancel_params.agent_id
    end,
})

--- Validate and normalize entities parameter
--- @param params_table table
--- @return table|nil Normalized entities array or nil if single entity
local function normalize_entities(params_table)
    if params_table.entities then
        -- Validate entities array
        if type(params_table.entities) ~= "table" then
            error("Parameter 'entities' must be an array")
        end
        if not params_table.entities[1] and next(params_table.entities) then
            error("Parameter 'entities' must be an array, not a map")
        end
        
        local normalized = {}
        local has_non_space = false
        
        for i, entity_spec in ipairs(params_table.entities) do
            if type(entity_spec) ~= "table" then
                error(string.format("Parameter 'entities[%d]' must be a table", i))
            end
            
            if entity_spec.name == "space" then
                -- Special gap entry
                if type(entity_spec.tile_count) ~= "number" or entity_spec.tile_count < 1 then
                    error(string.format("Parameter 'entities[%d].tile_count' must be a number >= 1", i))
                end
                table.insert(normalized, {
                    name = "space",
                    tile_count = entity_spec.tile_count
                })
            else
                -- Regular entity entry
                if not entity_spec.name or type(entity_spec.name) ~= "string" then
                    error(string.format("Parameter 'entities[%d].name' must be a string", i))
                end
                
                -- Validate entity name exists
                if not utils.validate_entity_name(entity_spec.name) then
                    error(string.format("Parameter 'entities[%d].name' must be a valid entity prototype: %s", i, entity_spec.name))
                end
                
                has_non_space = true
                
                local normalized_spec = {
                    name = entity_spec.name,
                    direction = entity_spec.direction,  -- Will be validated by ParamSpec if provided
                    orient_towards = entity_spec.orient_towards
                }
                
                -- Normalize direction if provided
                if normalized_spec.direction then
                    local dir = utils.validate_direction(normalized_spec.direction)
                    if dir == nil then
                        error(string.format("Parameter 'entities[%d].direction' must be a valid direction", i))
                    end
                    normalized_spec.direction = dir
                end
                
                table.insert(normalized, normalized_spec)
            end
        end
        
        if not has_non_space then
            error("Parameter 'entities' must contain at least one non-space entity")
        end
        
        return normalized
    elseif params_table.entity_name then
        -- Single entity mode
        return nil
    else
        error("Either 'entity_name' or 'entities' must be provided")
    end
end

--- Calculate placement positions along a line
--- @param start table {x, y}
--- @param end_pos table {x, y}
--- @param spacing number
--- @param entities table|nil Normalized entities array (nil for single entity)
--- @param entity_name string|nil Single entity name (nil if using entities array)
--- @return table Array of {position, entity_name, direction, orient_towards}
local function calculate_placement_plan(start, end_pos, spacing, entities, entity_name)
    local plan = {}
    local dx = end_pos.x - start.x
    local dy = end_pos.y - start.y
    local length = math.sqrt(dx*dx + dy*dy)
    
    if length < 0.01 then
        return plan  -- Start and end are same position
    end
    
    local unit_x = dx / length
    local unit_y = dy / length
    
    local current_distance = 0
    local entity_index = 1  -- For cycling through entities array
    
    while current_distance <= length do
        local entity_spec
        
        if entities then
            -- Cycle through entities array
            entity_spec = entities[entity_index]
            entity_index = (entity_index % #entities) + 1
        else
            -- Single entity mode
            entity_spec = { name = entity_name }
        end
        
        if entity_spec.name == "space" then
            -- Skip: advance by tile_count * spacing
            current_distance = current_distance + (entity_spec.tile_count or 1) * spacing
        else
            -- Place entity at current_distance
            local pos = {
                x = start.x + unit_x * current_distance,
                y = start.y + unit_y * current_distance
            }
            
            table.insert(plan, {
                position = pos,
                entity_name = entity_spec.name,
                direction = entity_spec.direction,
                orient_towards = entity_spec.orient_towards,
                placed = false
            })
            
            -- Advance by spacing for next entity
            current_distance = current_distance + spacing
        end
    end
    
    return plan
end

--- @class PlaceInLineContext
--- @field agent LuaEntity Agent character entity
--- @field start_position table
--- @field end_position table
--- @field entities table|nil Normalized entities array
--- @field entity_name string|nil Single entity name
--- @field spacing number
--- @field skip_invalid boolean
--- @field max_entities number|nil
--- @field dry_run boolean
--- @field arrive_radius number
--- @field placement_plan table Pre-calculated placement plan
--- @field params PlaceInLineParams ParamSpec instance for _post_run

--- Override _pre_run to build context using GameContext
--- @param params PlaceInLineParams|table|string
--- @return PlaceInLineContext
function PlaceInLineAction:_pre_run(params)
    -- Call parent to get validated ParamSpec
    local p = AsyncAction._pre_run(self, params)
    local params_table = p:get_values()
    
    -- Build context using GameContext
    local agent = GameContext.resolve_agent(params_table, self.game_state)
    
    -- Validate and normalize entities
    local entities = normalize_entities(params_table)
    local entity_name = params_table.entity_name
    
    -- Calculate placement plan
    local placement_plan = calculate_placement_plan(
        params_table.start_position,
        params_table.end_position,
        params_table.spacing or 0.0,
        entities,
        entity_name
    )
    
    -- Apply max_entities limit if specified
    if params_table.max_entities and #placement_plan > params_table.max_entities then
        -- Truncate plan
        for i = params_table.max_entities + 1, #placement_plan do
            placement_plan[i] = nil
        end
    end
    
    -- Return context for run()
    return {
        agent = agent,
        start_position = params_table.start_position,
        end_position = params_table.end_position,
        entities = entities,
        entity_name = entity_name,
        spacing = params_table.spacing or 0.0,
        skip_invalid = params_table.skip_invalid_positions ~= false,
        max_entities = params_table.max_entities,
        dry_run = params_table.dry_run == true,
        arrive_radius = params_table.arrive_radius or 0.5,
        placement_plan = placement_plan,
        params = p
    }
end

--- @param params PlaceInLineParams|table|string
--- @return table Result with async contract or dry_run validation
function PlaceInLineAction:run(params)
    --- @type PlaceInLineContext
    local context = self:_pre_run(params)
    
    local params_table = context.params:get_values()
    local agent_id = params_table.agent_id
    
    -- Delegate to AgentGameState for centralized state management
    local agent_state = self.game_state.agent
    
    -- If dry_run, perform validation and return immediately
    if context.dry_run then
        local validation = agent_state.placing_in_line:validate_placement_path(
            agent_id,
            context.placement_plan,
            context.start_position,
            context.end_position
        )
        
        return self:_post_run({
            success = true,
            dry_run = true,
            validation = validation
        }, context.params)
    end
    
    -- Check for concurrent place_in_line
    if storage.place_in_line_in_progress and storage.place_in_line_in_progress[agent_id] then
        return self:_post_run({
            success = false,
            error = "concurrent_place_in_line",
            message = "Agent already has a place_in_line action in progress"
        }, context.params)
    end
    
    -- Check for concurrent walk_to
    if storage.walk_in_progress and storage.walk_in_progress[agent_id] then
        return self:_post_run({
            success = false,
            error = "concurrent_walk",
            message = "Agent already has a walk_to action in progress"
        }, context.params)
    end
    
    -- Start the place_in_line job
    local job_id = agent_state.placing_in_line:start_place_in_line_job(
        agent_id,
        context.start_position,
        context.end_position,
        context.placement_plan,
        context.spacing,
        context.skip_invalid,
        context.max_entities,
        context.arrive_radius
    )
    
    if job_id then
        -- Generate unique action_id and rcon_tick using AsyncAction helper
        local action_id, rcon_tick = self:generate_action_id(agent_id)
        
        -- Store tracking using AsyncAction helper
        self:store_tracking("place_in_line_in_progress", agent_id, action_id, rcon_tick, {
            agent_id = agent_id,
            job_id = job_id
        })
        
        game.print(string.format("[place_in_line_action] Queued place_in_line for agent %d at tick %d: %s", agent_id, rcon_tick, action_id))
        
        -- Return async result using AsyncAction helper
        return self:_post_run(
            self:create_async_result(action_id, rcon_tick, {
                agent_id = agent_id,
                start_position = context.start_position,
                end_position = context.end_position,
                planned_placements = #context.placement_plan,
                entity_pattern = context.entities or context.entity_name
            }),
            context.params
        )
    else
        game.print(string.format("[place_in_line_action] Failed to start job for agent %d", agent_id))
        return self:_post_run({ success = false }, context.params)
    end
end

--- Cancel place_in_line action
--- @param cancel_params PlaceInLineCancelParams
--- @param tracking table|nil
--- @return table
function PlaceInLineAction:_do_cancel(cancel_params, tracking)
    local agent_id = cancel_params.agent_id
    local agent_state = self.game_state.agent
    
    if not agent_state then
        return self:create_cancel_result(false, false, tracking and tracking.action_id, { error = "Game state not available" })
    end
    
    -- Cancel the place_in_line job
    agent_state.placing_in_line:cancel_place_in_line(agent_id)
    
    return self:create_cancel_result(true, true, tracking and tracking.action_id, {
        agent_id = agent_id
    })
end

return { PlaceInLineAction }

