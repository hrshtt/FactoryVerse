local Action = require("types.Action")

--- @class SetFilterParams : ParamSpec
--- @field agent_id number Agent id executing the action
--- @field entity_name string Entity prototype name
--- @field position table|nil Optional position: { x = number, y = number }
--- @field inventory_type string Inventory type string (e.g., "chest", "input", "output")
--- @field filters table[] Array of filter specs: [{index: number, filter: string|nil}, ...]
local SetFilterParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    entity_name = { type = "entity_name", required = true },
    position = { type = "position", required = false },
    inventory_type = { type = "string", required = true },
    filters = { type = "table", required = true }
})

--- @class SetFilterAction : Action
local SetFilterAction = Action:new("entity.inventory.set_filter", SetFilterParams)

--- @param params SetFilterParams
--- @return table result Data about the filter changes
function SetFilterAction:run(params)
    local p = self:_pre_run(params)
    ---@cast p SetFilterParams

    -- Get agent (LuaEntity)
    local agent = self.game_state.agent:get_agent(p.agent_id)
    if not agent or not agent.valid then
        error("Agent not found or invalid")
    end

    -- Find entity within agent's build_distance
    local agent_pos = agent.position
    local build_distance = agent.build_distance or 10
    local surface = game.surfaces[1]
    local entity = nil
    
    if p.position and type(p.position.x) == "number" and type(p.position.y) == "number" then
        -- Try exact position first
        entity = surface.find_entity(p.entity_name, { x = p.position.x, y = p.position.y })
        if entity and entity.valid then
            -- Verify within build_distance
            local dx = entity.position.x - agent_pos.x
            local dy = entity.position.y - agent_pos.y
            local dist_sq = dx * dx + dy * dy
            if dist_sq > build_distance * build_distance then
                entity = nil
            end
        end
    end
    
    -- If not found at exact position, search within radius
    if not entity or not entity.valid then
        local entities = surface.find_entities_filtered({
            position = agent_pos,
            radius = build_distance,
            name = p.entity_name
        })
        
        -- Filter to valid entities
        local valid_entities = {}
        for _, e in ipairs(entities) do
            if e and e.valid then
                table.insert(valid_entities, e)
            end
        end
        
        if #valid_entities == 0 then
            error("Entity '" .. p.entity_name .. "' not found within build_distance of agent")
        elseif #valid_entities > 1 then
            error("Multiple entities '" .. p.entity_name .. "' found. Provide position parameter to specify which entity.")
        else
            entity = valid_entities[1]
        end
    end

    -- Map inventory type name to defines constant
    local inventory_type_map = {
        chest = defines.inventory.chest,
        fuel = defines.inventory.fuel,
        modules = defines.inventory.assembling_machine_modules,
        input = defines.inventory.assembling_machine_input,
        output = defines.inventory.assembling_machine_output,
        ammo = defines.inventory.turret_ammo,
    }
    
    local inventory_type = inventory_type_map[p.inventory_type]
    if not inventory_type then
        error("Invalid inventory_type: " .. p.inventory_type)
    end

    -- Get target inventory
    local target_inventory = entity.get_inventory(inventory_type)
    if not target_inventory or not target_inventory.valid then
        error("Entity does not have inventory type: " .. p.inventory_type)
    end

    -- Check if inventory supports filters
    if not target_inventory.supports_filters() then
        error("Inventory does not support filters")
    end

    -- Validate filters array
    if type(p.filters) ~= "table" or not p.filters[1] then
        error("filters must be a non-empty array")
    end

    local inventory_size = #target_inventory
    local processed_filters = {}

    -- Process each filter
    for i, filter_spec in ipairs(p.filters) do
        if type(filter_spec) ~= "table" then
            error("filters[" .. i .. "] must be a table with 'index' and 'filter' fields")
        end

        local index = filter_spec.index
        local filter = filter_spec.filter  -- string or nil

        -- Validate index
        if type(index) ~= "number" or math.floor(index) ~= index then
            error("filters[" .. i .. "].index must be an integer")
        end
        if index < 1 or index > inventory_size then
            error("filters[" .. i .. "].index must be between 1 and " .. inventory_size .. ", got: " .. index)
        end

        -- Validate filter (if provided, must be string)
        if filter ~= nil and type(filter) ~= "string" then
            error("filters[" .. i .. "].filter must be a string or nil, got: " .. type(filter))
        end

        -- Check if filter can be set
        if not target_inventory.can_set_filter(index, filter) then
            error("Cannot set filter for slot " .. index .. " to '" .. tostring(filter) .. "'")
        end

        -- Get current filter for result
        local previous_filter = target_inventory.get_filter(index)

        -- Set the filter
        local success = target_inventory.set_filter(index, filter)
        if not success then
            error("Failed to set filter for slot " .. index)
        end

        table.insert(processed_filters, {
            index = index,
            previous_filter = previous_filter,
            new_filter = filter
        })
    end

    local result = {
        position = { x = entity.position.x, y = entity.position.y },
        entity_name = entity.name,
        entity_type = entity.type,
        inventory_type = p.inventory_type,
        filters = processed_filters,
        affected_positions = { 
            { 
                position = { x = entity.position.x, y = entity.position.y },
                entity_name = p.entity_name,
                entity_type = entity.type
            } 
        }
    }
    
    return self:_post_run(result, p)
end

return { action = SetFilterAction, params = SetFilterParams }

