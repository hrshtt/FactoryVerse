local Action = require("types.Action")
local GameContext = require("game_state.GameContext")

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
local SetFilterAction = Action:new("entity.inventory_set_filter", SetFilterParams)

--- @class SetFilterContext
--- @field agent LuaEntity Agent character entity
--- @field entity LuaEntity Target entity
--- @field entity_proto table Entity prototype
--- @field inventory_type string Inventory type string
--- @field filters table[] Array of filter specs
--- @field params SetFilterParams ParamSpec instance for _post_run

--- Override _pre_run to build context using GameContext
--- @param params SetFilterParams|table|string
--- @return SetFilterContext
function SetFilterAction:_pre_run(params)
    -- Call parent to get validated ParamSpec
    local p = Action._pre_run(self, params)
    local params_table = p:get_values()
    
    -- Build context using GameContext
    local agent = GameContext.resolve_agent(params_table, self.game_state)
    local entity, entity_proto = GameContext.resolve_entity(params_table, agent)
    
    -- Return context for run()
    return {
        agent = agent,
        entity = entity,
        entity_proto = entity_proto,
        inventory_type = params_table.inventory_type,
        filters = params_table.filters,
        params = p
    }
end

--- @param params SetFilterParams|table|string
--- @return table result Data about the filter changes
function SetFilterAction:run(params)
    --- @type SetFilterContext
    local context = self:_pre_run(params)

    -- Map inventory type name to defines constant
    local inventory_type_map = {
        chest = defines.inventory.chest,
        fuel = defines.inventory.fuel,
        modules = defines.inventory.assembling_machine_modules,
        input = defines.inventory.assembling_machine_input,
        output = defines.inventory.assembling_machine_output,
        ammo = defines.inventory.turret_ammo,
    }
    
    local inventory_type = inventory_type_map[context.inventory_type]
    if not inventory_type then
        error("Invalid inventory_type: " .. context.inventory_type)
    end

    -- Get target inventory
    local target_inventory = context.entity.get_inventory(inventory_type)
    if not target_inventory or not target_inventory.valid then
        error("Entity does not have inventory type: " .. context.inventory_type)
    end

    -- Logical validation: Check if inventory supports filters
    if not target_inventory.supports_filters() then
        error("Inventory does not support filters")
    end

    -- Logical validation: Validate filters array
    if type(context.filters) ~= "table" or not context.filters[1] then
        error("filters must be a non-empty array")
    end

    local inventory_size = #target_inventory
    local processed_filters = {}

    -- Process each filter
    for i, filter_spec in ipairs(context.filters) do
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

    local params_table = context.params:get_values()
    local result = {
        position = { x = context.entity.position.x, y = context.entity.position.y },
        entity_name = context.entity.name,
        entity_type = context.entity.type,
        inventory_type = context.inventory_type,
        filters = processed_filters,
        affected_positions = { 
            { 
                position = { x = context.entity.position.x, y = context.entity.position.y },
                entity_name = params_table.entity_name,
                entity_type = context.entity.type
            } 
        }
    }
    
    return self:_post_run(result, context.params)
end

return { action = SetFilterAction, params = SetFilterParams }

