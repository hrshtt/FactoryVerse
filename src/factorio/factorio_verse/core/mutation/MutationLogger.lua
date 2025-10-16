--- MutationLogger.lua
--- Centralized mutation logging system for tracking game state changes
--- Integrates with action post_run hooks and provides extensible tick-based logging
--- Outputs JSONL format for efficient downstream processing

local GameState = require("core.game_state.GameState")
local EntitiesSnapshot = require("core.snapshot.EntitiesSnapshot")

--- @class MutationLogger
--- @field game_state GameState
--- @field entities_snapshot EntitiesSnapshot
--- @field config table Configuration flags
local MutationLogger = {}
MutationLogger.__index = MutationLogger

--- Configuration defaults
local DEFAULT_CONFIG = {
    enabled = true,              -- Master switch for all mutation logging
    log_actions = true,          -- Log mutations from action post_run hooks
    log_tick_events = false,     -- Log mutations from nth-tick events (future)
    output_dir = "script-output/factoryverse/mutations",
    buffer_size = 100,           -- Future: batch writes for performance
    debug = false                -- Additional debug logging
}

--- Create new MutationLogger instance
--- @param config table|nil Optional configuration overrides
--- @return MutationLogger
function MutationLogger:new(config)
    local instance = {
        game_state = GameState:new(),
        entities_snapshot = EntitiesSnapshot:new(),
        config = {}
    }
    
    -- Merge config with defaults
    for key, default_value in pairs(DEFAULT_CONFIG) do
        instance.config[key] = (config and config[key] ~= nil) and config[key] or default_value
    end
    
    setmetatable(instance, self)
    return instance
end

--- Main entry point for action-based mutation logging
--- Called from Action:_post_run() hook
--- @param action_name string Name of the action that was executed
--- @param params table Action parameters
--- @param result table Action result containing mutation hints
function MutationLogger:log_action_mutations(action_name, params, result)
    if not self.config.enabled or not self.config.log_actions then
        return
    end
    
    local mutations = self:_extract_mutations_from_action(action_name, params, result)
    if mutations and (#mutations.entities > 0 or #mutations.resources > 0 or #mutations.inventories > 0) then
        self:_emit_mutation_log(mutations, "action")
    end
end

--- Extract mutations from action result
--- @param action_name string
--- @param params table
--- @param result table
--- @return table|nil mutations
function MutationLogger:_extract_mutations_from_action(action_name, params, result)
    if not result then return nil end
    
    local mutations = {
        meta = {
            tick = game and game.tick or 0,
            action = action_name,
            surface = self.game_state:get_surface() and self.game_state:get_surface().name or "unknown"
        },
        entities = {},
        resources = {},
        inventories = {}
    }
    
    -- Extract entity mutations
    if result.affected_unit_numbers and type(result.affected_unit_numbers) == "table" then
        for _, unit_number in ipairs(result.affected_unit_numbers) do
            local entity_mutation = self:_extract_entity_mutation(unit_number, action_name)
            if entity_mutation then
                table.insert(mutations.entities, entity_mutation)
            end
        end
    end
    
    -- Extract resource mutations
    if result.affected_resources and type(result.affected_resources) == "table" then
        for _, resource_data in ipairs(result.affected_resources) do
            local resource_mutation = self:_extract_resource_mutation(resource_data, action_name)
            if resource_mutation then
                table.insert(mutations.resources, resource_mutation)
            end
        end
    end
    
    -- Extract inventory mutations
    if result.affected_inventories and type(result.affected_inventories) == "table" then
        for _, inventory_data in ipairs(result.affected_inventories) do
            local inventory_mutation = self:_extract_inventory_mutation(inventory_data, action_name)
            if inventory_mutation then
                table.insert(mutations.inventories, inventory_mutation)
            end
        end
    end
    
    return mutations
end

--- Extract entity mutation data using existing snapshot serializers
--- @param unit_number number
--- @param action_name string
--- @return table|nil
function MutationLogger:_extract_entity_mutation(unit_number, action_name)
    local surface = self.game_state:get_surface()
    if not surface then return nil end
    
    -- Find entity by unit_number
    local entity = nil
    for _, e in pairs(surface.find_entities_filtered{}) do
        if e.valid and e.unit_number == unit_number then
            entity = e
            break
        end
    end
    
    if not entity then
        -- Entity was removed - log removal mutation
        return {
            mutation_type = "removed",
            unit_number = unit_number,
            action = action_name
        }
    end
    
    -- Use existing snapshot serializer for consistent format
    local serialized = self.entities_snapshot:_serialize_entity(entity)
    if not serialized then return nil end
    
    -- Determine mutation type based on action
    local mutation_type = self:_infer_mutation_type(action_name, entity)
    
    return {
        mutation_type = mutation_type,
        unit_number = unit_number,
        action = action_name,
        entity_data = serialized
    }
end

--- Extract resource mutation data
--- @param resource_data table {name, position, delta}
--- @param action_name string
--- @return table|nil
function MutationLogger:_extract_resource_mutation(resource_data, action_name)
    if not (resource_data.name and resource_data.position and resource_data.delta) then
        return nil
    end
    
    return {
        mutation_type = "depleted",
        action = action_name,
        resource_name = resource_data.name,
        position = resource_data.position,
        delta = resource_data.delta
    }
end

--- Extract inventory mutation data
--- @param inventory_data table {owner_type, owner_id, inventory_type, changes}
--- @param action_name string
--- @return table|nil
function MutationLogger:_extract_inventory_mutation(inventory_data, action_name)
    if not (inventory_data.owner_type and inventory_data.owner_id) then
        return nil
    end
    
    local mutation = {
        mutation_type = "inventory_changed",
        action = action_name,
        owner_type = inventory_data.owner_type, -- "agent" or "entity"
        owner_id = inventory_data.owner_id
    }
    
    -- Add inventory type for entities (chest, assembler input/output, etc.)
    if inventory_data.inventory_type then
        mutation.inventory_type = inventory_data.inventory_type
    end
    
    -- Add item changes if provided
    if inventory_data.changes and type(inventory_data.changes) == "table" then
        mutation.item_changes = inventory_data.changes
    end
    
    return mutation
end

--- Infer mutation type from action name and entity state
--- @param action_name string
--- @param entity LuaEntity
--- @return string
function MutationLogger:_infer_mutation_type(action_name, entity)
    if string.find(action_name, "place") then
        return "created"
    elseif string.find(action_name, "remove") then
        return "removed"
    elseif string.find(action_name, "recipe") then
        return "recipe_changed"
    else
        return "modified"
    end
end

--- Emit mutation log as JSONL
--- @param mutations table
--- @param source_type string "action" or "tick" to determine subdirectory
function MutationLogger:_emit_mutation_log(mutations, source_type)
    if not mutations then return end
    
    local tick = mutations.meta.tick
    local surface = mutations.meta.surface
    local action = mutations.meta.action
    
    -- Write entity mutations to {source_type}/entities.jsonl
    if #mutations.entities > 0 then
        local entity_lines = {}
        for _, entity_mutation in ipairs(mutations.entities) do
            local entry = {
                tick = tick,
                surface = surface,
                action = action,
                data = entity_mutation
            }
            table.insert(entity_lines, helpers.table_to_json(entry))
        end
        self:_append_to_file(source_type, "entities.jsonl", entity_lines)
    end
    
    -- Write resource mutations to {source_type}/resources.jsonl
    if #mutations.resources > 0 then
        local resource_lines = {}
        for _, resource_mutation in ipairs(mutations.resources) do
            local entry = {
                tick = tick,
                surface = surface,
                action = action,
                data = resource_mutation
            }
            table.insert(resource_lines, helpers.table_to_json(entry))
        end
        self:_append_to_file(source_type, "resources.jsonl", resource_lines)
    end
    
    -- Write inventory mutations to {source_type}/inventories.jsonl
    if #mutations.inventories > 0 then
        local inventory_lines = {}
        for _, inventory_mutation in ipairs(mutations.inventories) do
            local entry = {
                tick = tick,
                surface = surface,
                action = action,
                data = inventory_mutation
            }
            table.insert(inventory_lines, helpers.table_to_json(entry))
        end
        self:_append_to_file(source_type, "inventories.jsonl", inventory_lines)
    end
end

--- Append JSONL lines to a specific mutation type file in the appropriate subdirectory
--- @param source_type string "action" or "tick" subdirectory
--- @param filename string The mutation type file (e.g., "entities.jsonl")
--- @param jsonl_lines table Array of JSON strings
function MutationLogger:_append_to_file(source_type, filename, jsonl_lines)
    if not jsonl_lines or #jsonl_lines == 0 then return end
    
    local filepath = string.format("%s/%s/%s", self.config.output_dir, source_type, filename)
    local content = table.concat(jsonl_lines, "\n") .. "\n"
    
    -- Append to file (true = append mode)
    if helpers and helpers.write_file then
        helpers.write_file(filepath, content, true) -- true = append
        
        if self.config.debug then
            log(string.format("[MutationLogger] Appended %d mutations to %s", #jsonl_lines, filepath))
        end
    end
end

--- SKELETON: Future tick-based mutation logging
--- This provides the structure for autonomous entity mutation tracking
--- @param event table Factorio event data
function MutationLogger:log_tick_mutations(event)
    if not self.config.enabled or not self.config.log_tick_events then
        return
    end
    
    -- TODO: Implement tick-based mutation detection
    -- This would track:
    -- - Resource depletion by mining drills/pumpjacks
    -- - Entity status changes (working -> idle, etc.)
    -- - Autonomous inventory changes (inserters, belts)
    
    -- Skeleton implementation:
    local mutations = {
        meta = {
            tick = event.tick,
            surface = self.game_state:get_surface() and self.game_state:get_surface().name or "unknown"
        },
        entities = {},
        resources = {},
        inventories = {}
    }
    
    -- Future: Detect and log autonomous changes
    -- self:_detect_autonomous_entity_changes(mutations)
    -- self:_detect_autonomous_resource_changes(mutations)
    -- self:_detect_autonomous_inventory_changes(mutations)
    
    -- if #mutations.entities > 0 or #mutations.resources > 0 or #mutations.inventories > 0 then
    --     self:_emit_mutation_log(mutations)
    -- end
end

--- Global instance for easy access
local global_mutation_logger = nil

--- Get or create global MutationLogger instance
--- @param config table|nil
--- @return MutationLogger
function MutationLogger.get_instance(config)
    if not global_mutation_logger then
        global_mutation_logger = MutationLogger:new(config)
    end
    return global_mutation_logger
end

--- Configure global instance
--- @param config table
function MutationLogger.configure(config)
    local instance = MutationLogger.get_instance()
    for key, value in pairs(config or {}) do
        instance.config[key] = value
    end
end

return MutationLogger
