--- TickMutationLogger.lua
--- Skeleton implementation for autonomous entity mutation logging
--- Tracks mutations that happen without direct player actions (nth-tick events)

local MutationLogger = require("core.mutation.MutationLogger")

--- @class TickMutationLogger
--- @field mutation_logger MutationLogger
--- @field tick_interval number How often to check for mutations
--- @field last_state table Previous state for diff detection
local TickMutationLogger = {}
TickMutationLogger.__index = TickMutationLogger

--- Create new TickMutationLogger instance
--- @param tick_interval number|nil Tick interval for mutation detection (default: 60)
--- @return TickMutationLogger
function TickMutationLogger:new(tick_interval)
    local instance = {
        mutation_logger = MutationLogger.get_instance(),
        tick_interval = tick_interval or 60, -- Default: check every second
        last_state = {
            resources = {},    -- position -> {name, amount}
            entities = {},     -- unit_number -> {status, recipe, etc.}
            inventories = {}   -- entity_unit_number -> inventory_contents
        }
    }
    
    setmetatable(instance, self)
    return instance
end

--- Main tick handler for autonomous mutation detection
--- @param event table Factorio on_tick event
function TickMutationLogger:on_tick(event)
    if not self.mutation_logger.config.enabled or not self.mutation_logger.config.log_tick_events then
        return
    end
    
    -- Only process on our interval
    if event.tick % self.tick_interval ~= 0 then
        return
    end
    
    local mutations = {
        meta = {
            tick = event.tick,
            surface = self.mutation_logger.game_state:get_surface() and 
                     self.mutation_logger.game_state:get_surface().name or "unknown"
        },
        entities = {},
        resources = {},
        inventories = {}
    }
    
    -- SKELETON: Detect autonomous changes
    self:_detect_resource_changes(mutations)
    self:_detect_entity_status_changes(mutations)
    self:_detect_autonomous_inventory_changes(mutations)
    
    -- Log if any mutations were detected
    if #mutations.entities > 0 or #mutations.resources > 0 or #mutations.inventories > 0 then
        self.mutation_logger:_emit_mutation_log(mutations, "tick")
    end
end

--- SKELETON: Detect resource depletion by mining drills/pumpjacks
--- @param mutations table
function TickMutationLogger:_detect_resource_changes(mutations)
    -- TODO: Implementation for future development
    -- This would:
    -- 1. Scan all mining drills and pumpjacks
    -- 2. Check resource tiles they're operating on
    -- 3. Compare with last_state.resources to detect changes
    -- 4. Log resource depletion mutations
    
    --[[
    Example implementation outline:
    
    local surface = self.mutation_logger.game_state:get_surface()
    if not surface then return end
    
    local mining_entities = surface.find_entities_filtered{
        type = {"mining-drill", "offshore-pump"}
    }
    
    for _, entity in ipairs(mining_entities) do
        if entity.valid and entity.status == defines.entity_status.working then
            -- Check what resource it's mining
            local resource_pos = entity.mining_target and entity.mining_target.position
            if resource_pos then
                local key = string.format("%.2f,%.2f", resource_pos.x, resource_pos.y)
                local current_amount = entity.mining_target.amount or 0
                local last_amount = self.last_state.resources[key] and 
                                   self.last_state.resources[key].amount or current_amount
                
                if current_amount < last_amount then
                    table.insert(mutations.resources, {
                        mutation_type = "depleted",
                        action = "autonomous_mining",
                        resource_name = entity.mining_target.name,
                        position = resource_pos,
                        delta = current_amount - last_amount
                    })
                end
                
                -- Update state
                self.last_state.resources[key] = {
                    name = entity.mining_target.name,
                    amount = current_amount
                }
            end
        end
    end
    ]]--
end

--- SKELETON: Detect entity status changes (working/idle/no_power)
--- @param mutations table
function TickMutationLogger:_detect_entity_status_changes(mutations)
    -- TODO: Implementation for future development
    -- This would:
    -- 1. Scan relevant entity types (assemblers, furnaces, etc.)
    -- 2. Compare current status with last_state.entities
    -- 3. Log status change mutations
    
    --[[
    Example implementation outline:
    
    local surface = self.mutation_logger.game_state:get_surface()
    if not surface then return end
    
    local entities = surface.find_entities_filtered{
        type = {"assembling-machine", "furnace", "chemical-plant", "oil-refinery"}
    }
    
    for _, entity in ipairs(entities) do
        if entity.valid and entity.unit_number then
            local current_status = entity.status
            local last_status = self.last_state.entities[entity.unit_number] and
                               self.last_state.entities[entity.unit_number].status
            
            if current_status ~= last_status then
                local entity_data = self.mutation_logger.entities_snapshot:_serialize_entity(entity)
                if entity_data then
                    table.insert(mutations.entities, {
                        mutation_type = "status_changed",
                        unit_number = entity.unit_number,
                        action = "autonomous_status_change",
                        entity_data = entity_data,
                        old_status = last_status,
                        new_status = current_status
                    })
                end
            end
            
            -- Update state
            self.last_state.entities[entity.unit_number] = {
                status = current_status
            }
        end
    end
    ]]--
end

--- SKELETON: Detect autonomous inventory changes (inserters, belts)
--- @param mutations table
function TickMutationLogger:_detect_autonomous_inventory_changes(mutations)
    -- TODO: Implementation for future development
    -- This would:
    -- 1. Scan chest entities (containers, logistic-containers)
    -- 2. Compare inventory contents with last_state.inventories
    -- 3. Log inventory change mutations
    
    --[[
    Example implementation outline:
    
    local surface = self.mutation_logger.game_state:get_surface()
    if not surface then return end
    
    local chests = surface.find_entities_filtered{
        type = {"container", "logistic-container"}
    }
    
    for _, chest in ipairs(chests) do
        if chest.valid and chest.unit_number then
            local inv = chest.get_inventory(defines.inventory.chest)
            if inv then
                local current_contents = inv.get_contents()
                local last_contents = self.last_state.inventories[chest.unit_number] or {}
                
                -- Calculate changes
                local changes = {}
                local has_changes = false
                
                -- Check for items that increased or decreased
                for item_name, current_count in pairs(current_contents) do
                    local last_count = last_contents[item_name] or 0
                    if current_count ~= last_count then
                        changes[item_name] = current_count - last_count
                        has_changes = true
                    end
                end
                
                -- Check for items that were completely removed
                for item_name, last_count in pairs(last_contents) do
                    if not current_contents[item_name] and last_count > 0 then
                        changes[item_name] = -last_count
                        has_changes = true
                    end
                end
                
                if has_changes then
                    table.insert(mutations.inventories, {
                        mutation_type = "inventory_changed",
                        action = "autonomous_inventory_change",
                        owner_type = "entity",
                        owner_id = chest.unit_number,
                        inventory_type = "chest",
                        changes = changes
                    })
                end
                
                -- Update state
                self.last_state.inventories[chest.unit_number] = current_contents
            end
        end
    end
    ]]--
end

--- Register tick handler with Factorio event system
--- Call this from control.lua to enable tick-based mutation logging
function TickMutationLogger:register_events()
    script.on_nth_tick(self.tick_interval, function(event)
        self:on_tick(event)
    end)
end

return TickMutationLogger
