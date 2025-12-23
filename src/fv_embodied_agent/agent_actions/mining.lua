--- Agent mining action methods
--- Methods operate directly on Agent instances (self)
--- State is stored in self.mining
--- These methods are mixed into the Agent class at module level
---
--- Mining Modes:
---   INCREMENTAL: Resource ores - mine N items using cycle detection, then stop
---   DEPLETE: Trees, rocks, huge-rock - mine until entity invalid, report products at end
---
--- Only huge-rock (stochastic products) blocks crafting due to inventory diff requirement.

local debug_render = require("utils.debug_render")
local custom_events = require("utils.custom_events")

local MiningActions = {}

-- DEBUG FLAG
local DEBUG = false

-- ============================================================================
-- CONSTANTS
-- ============================================================================

local MINING_MODE = {
    INCREMENTAL = "incremental",  -- ores: count cycles to target
    DEPLETE = "deplete",          -- trees/rocks: wait for entity.valid == false
}

--- Entities with stochastic (random/probability-based) products
local STOCHASTIC_ENTITIES = {
    ["huge-rock"] = true,
}

--- Resource type mappings for search (user says "tree" or "rock", we search by type)
local RESOURCE_TYPE_MAPPING = {
    ["tree"] = "tree",
    ["rock"] = "simple-entity",
}

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

--- Determine mining mode based on entity type
--- @param entity LuaEntity The entity being mined
--- @return string Mining mode constant
local function get_mining_mode(entity)
    if entity.type == "resource" then
        return MINING_MODE.INCREMENTAL
    else
        return MINING_MODE.DEPLETE
    end
end

--- Check if entity has stochastic products
--- @param entity LuaEntity
--- @return boolean
local function is_stochastic(entity)
    return STOCHASTIC_ENTITIES[entity.name] == true
end

--- Calculate effective mining speed for character
--- @param character LuaEntity Character entity
--- @return number Effective mining speed
local function get_effective_mining_speed(character)
    local base_speed = character.prototype.mining_speed
    local modifier = character.character_mining_speed_modifier or 0
    return base_speed * (1 + modifier)
end

--- Calculate the completion threshold for mining progress (incremental mode only)
--- The last progress value before 1.0 is (1.0 - progress_per_tick)
--- @param character LuaEntity Character entity
--- @param entity LuaEntity Entity being mined
--- @return number Threshold value (progress > threshold means cycle about to complete)
local function get_completion_threshold(character, entity)
    local mining_time = entity.prototype.mineable_properties.mining_time
    local mining_speed = get_effective_mining_speed(character)
    local progress_per_tick = mining_speed / (mining_time * 60)
    return 1.0 - progress_per_tick - 0.0001
end

--- Get expected products for a mineable entity (deterministic only)
--- @param entity LuaEntity Entity being mined
--- @return table {item_name = amount, ...}
local function get_expected_products(entity)
    local proto = entity.prototype
    local mineable_props = proto.mineable_properties
    
    if not mineable_props or not mineable_props.products then
        return {}
    end
    
    local products = {}
    for _, product in pairs(mineable_props.products) do
        -- Products can have probability < 1.0 (skip those) or amount/amount_min/amount_max
        if not product.probability or product.probability >= 1.0 then
            local amount = product.amount or product.amount_min or 1
            products[product.name] = (products[product.name] or 0) + amount
        end
    end
    
    return products
end

--- Snapshot current inventory counts for common mining products
--- @param character LuaEntity Character entity
--- @return table {item_name = count, ...}
local function snapshot_inventory(character)
    local snapshot = {}
    local inventory = character.get_main_inventory()
    if not inventory then return snapshot end
    
    local common_products = {"stone", "coal", "iron-ore", "copper-ore", "wood"}
    for _, name in ipairs(common_products) do
        snapshot[name] = inventory.get_item_count(name)
    end
    return snapshot
end

--- Calculate inventory diff between current and snapshot
--- @param character LuaEntity Character entity
--- @param start_snapshot table {item_name = count, ...}
--- @return table {item_name = delta, ...} Only positive deltas
local function get_inventory_diff(character, start_snapshot)
    local diff = {}
    local inventory = character.get_main_inventory()
    if not inventory then return diff end
    
    for item_name, start_count in pairs(start_snapshot) do
        local current_count = inventory.get_item_count(item_name)
        local delta = current_count - start_count
        if delta > 0 then
            diff[item_name] = delta
        end
    end
    return diff
end

--- Calculate estimated mining time in ticks
--- @param character LuaEntity Character entity
--- @param entity LuaEntity Entity to mine
--- @param count number|nil Number of mining cycles (for incremental mode)
--- @return number|nil Estimated ticks
local function calculate_mining_time_ticks(character, entity, count)
    local proto = entity.prototype
    if not proto or not proto.mineable_properties then
        return nil
    end
    
    local mining_time = proto.mineable_properties.mining_time
    if not mining_time or mining_time <= 0 then
        return nil
    end
    
    local mining_speed = get_effective_mining_speed(character)
    local ticks_per_cycle = (mining_time / mining_speed) * 60
    
    if count and count > 1 then
        return math.ceil(ticks_per_cycle * count)
    end
    return math.ceil(ticks_per_cycle)
end

-- ============================================================================
-- PUBLIC API
-- ============================================================================

--- Check if mining state should block crafting
--- Only stochastic mining (huge-rock) blocks crafting because we need inventory diff
--- @param self Agent
--- @return boolean
function MiningActions.is_mining_blocking_crafting(self)
    if not self.character.mining_state.mining then
        return false
    end
    return self.mining.is_stochastic == true
end

--- Start mining a resource (async)
--- @param self Agent
--- @param resource_name string Resource name (e.g., "iron-ore", "tree", "rock")
--- @param max_count number|nil Maximum count to mine (only for ores, ignored for trees/rocks)
--- @return table Result with {success, queued, action_id, tick, estimated_ticks, expected_products}
function MiningActions.mine_resource(self, resource_name, max_count)
    -- Validate input
    if not resource_name or type(resource_name) ~= "string" then
        error("Agent: resource_name (string) is required")
    end
    
    if string.find(resource_name:lower(), "oil") then
        error("Agent: Cannot mine oil resources (use pumpjack)")
    end
    
    if self.character.mining_state.mining then
        error("Agent: Already mining, call stop_mining first")
    end
    
    -- Find entity to mine
    local agent_pos = self.character.position
    local radius = self.character.resource_reach_distance or 2.5
    local surface = self.character.surface
    
    local search_args = {
        position = { x = agent_pos.x, y = agent_pos.y },
        radius = radius,
    }
    
    if RESOURCE_TYPE_MAPPING[resource_name] then
        search_args.type = RESOURCE_TYPE_MAPPING[resource_name]
    else
        search_args.name = resource_name
    end
    
    local entities = surface.find_entities_filtered(search_args)
    if not entities or #entities == 0 then
        error("Agent: Resource not found within reach")
    end
    
    local entity = entities[1]
    if not entity or not entity.valid then
        error("Game: Resource entity is invalid")
    end
    
    -- Determine mining mode and properties
    local mode = get_mining_mode(entity)
    local stochastic = is_stochastic(entity)
    
    -- Store entity info (survives entity destruction)
    local entity_name = entity.name
    local entity_type = entity.type
    local entity_position = { x = entity.position.x, y = entity.position.y }
    
    -- Mode-specific setup
    local target_count = nil
    local completion_threshold = nil
    local start_inventory = nil
    local expected_products = nil
    
    if mode == MINING_MODE.INCREMENTAL then
        target_count = max_count or 10
        completion_threshold = get_completion_threshold(self.character, entity)
        expected_products = { [entity_name] = target_count }
    else
        -- DEPLETE mode
        if stochastic then
            -- Need inventory snapshot for huge-rock
            start_inventory = snapshot_inventory(self.character)
        else
            -- Deterministic - we know what we'll get
            expected_products = get_expected_products(entity)
        end
    end
    
    -- Generate action ID
    local action_id = string.format("mine_%d_%d", game.tick, self.agent_id)
    
    -- Initialize mining state (minimal)
    self.mining = {
        mode = mode,
        action_id = action_id,
        start_tick = game.tick,
        entity_name = entity_name,
        entity_type = entity_type,
        entity_position = entity_position,
        -- Incremental mode only
        target_count = target_count,
        count_progress = 0,
        completion_threshold = completion_threshold,
        last_progress = 0,
        -- Stochastic deplete only
        is_stochastic = stochastic,
        start_inventory = start_inventory,
        -- For completion message
        expected_products = expected_products,
    }
    
    -- Start mining
    self.character.update_selected_entity(entity.position)
    self.character.mining_state = { mining = true, position = entity.position }
    
    -- Calculate estimated time
    local estimated_ticks = calculate_mining_time_ticks(self.character, entity, target_count)
    
    -- Enqueue queued message
    self:enqueue_message({
        action = "mine_resource",
        agent_id = self.agent_id,
        success = true,
        status = "queued",
        queued = true,
        action_id = action_id,
        tick = game.tick,
        resource_name = resource_name,
        entity_name = entity_name,
        position = entity_position,
        mode = mode,
        target_count = target_count,
        estimated_ticks = estimated_ticks,
        expected_products = expected_products,
    }, "mining")
    
    return {
        success = true,
        queued = true,
        action_id = action_id,
        tick = game.tick,
        mode = mode,
        estimated_ticks = estimated_ticks,
        expected_products = expected_products,
    }
end

--- Finalize mining and report results
--- @param self Agent
--- @param reason string Reason: "cancelled", "completed", "depleted"
--- @return table Result
function MiningActions.finalize_mining(self, reason)
    reason = reason or "cancelled"
    local mining_state = self.mining
    
    -- Calculate actual products based on mode
    -- For cancelled: still report what was mined so far (incremental) or use inventory diff (stochastic)
    local actual_products = nil
    local count = mining_state.count_progress or 0
    
    if mining_state.mode == MINING_MODE.INCREMENTAL then
        -- We know exactly what we got (even if cancelled partway through)
        if count > 0 then
            actual_products = { [mining_state.entity_name] = count }
        end
    elseif mining_state.is_stochastic and mining_state.start_inventory then
        -- Stochastic deplete: use inventory diff (works for cancelled too)
        actual_products = get_inventory_diff(self.character, mining_state.start_inventory)
        if not next(actual_products) then
            actual_products = nil  -- Empty table -> nil
        end
    elseif reason ~= "cancelled" then
        -- Deterministic deplete completed: use expected products
        actual_products = mining_state.expected_products
    end
    
    -- Render completion text for deplete modes using localized string format
    -- Format: +<amount> <icon> <localised name> (<total>)
    -- Multiple products (e.g. huge-rock) are separated by newlines
    if reason == "depleted" and actual_products and next(actual_products) then
        local inventory = self.character.get_main_inventory()
        local text_parts = {""}
        local first = true
        for item_name, amount in pairs(actual_products) do
            if not first then
                table.insert(text_parts, "\n")
            end
            local total_count = inventory and inventory.get_item_count(item_name) or 0
            table.insert(text_parts, "+")
            table.insert(text_parts, amount)
            table.insert(text_parts, " ")
            table.insert(text_parts, "[item=" .. item_name .. "]")
            table.insert(text_parts, {"item-name." .. item_name})
            table.insert(text_parts, " (")
            table.insert(text_parts, total_count)
            table.insert(text_parts, ")")
            first = false
        end
        debug_render.render_player_floating_text(text_parts, mining_state.entity_position, 1)
    end
    
    -- Calculate actual time
    local actual_ticks = nil
    if mining_state.start_tick then
        actual_ticks = game.tick - mining_state.start_tick
    end
    
    -- Build completion message
    local message = {
        action = "mine_resource",
        agent_id = self.agent_id,
        success = reason ~= "cancelled",
        status = reason == "cancelled" and "cancelled" or "completed",
        action_id = mining_state.action_id,
        tick = game.tick,
        reason = reason,
        entity_name = mining_state.entity_name,
        position = mining_state.entity_position,
        mode = mining_state.mode,
        count = count,
        actual_products = actual_products,
        actual_ticks = actual_ticks,
    }
    
    if reason == "cancelled" then
        message.cancelled = true
    end
    
    self:enqueue_message(message, "mining")
    
    -- Raise custom event for entity destruction (for trees/rocks that get depleted)
    -- This ensures FVSnapshot mod can track the entity destruction
    -- Only raise for depleted entities (not cancelled or incremental completed)
    if DEBUG then
        game.print(string.format("[DEBUG mining.finalize_mining] Tick %d: reason=%s, entity_name=%s, entity_position=%s, entity_type=%s", 
            game.tick, reason or "nil", tostring(mining_state and mining_state.entity_name), 
            mining_state and mining_state.entity_position and string.format("{%f,%f}", mining_state.entity_position.x, mining_state.entity_position.y) or "nil",
            tostring(mining_state and mining_state.entity_type)))
    end
    
    if reason == "depleted" and mining_state and mining_state.entity_name and mining_state.entity_position then
        -- Check if it's a resource entity (tree or rock)
        local is_resource_entity = false
        if mining_state.entity_type == "tree" then
            is_resource_entity = true
            if DEBUG then
                game.print(string.format("[DEBUG mining.finalize_mining] Tick %d: Detected tree entity", game.tick))
            end
        elseif mining_state.entity_type == "simple-entity" and mining_state.entity_name then
            if mining_state.entity_name:match("rock") or mining_state.entity_name:match("stone") then
                is_resource_entity = true
                if DEBUG then
                    game.print(string.format("[DEBUG mining.finalize_mining] Tick %d: Detected rock entity: %s", game.tick, mining_state.entity_name))
                end
            end
        end
        
        if DEBUG then
            game.print(string.format("[DEBUG mining.finalize_mining] Tick %d: is_resource_entity=%s", game.tick, tostring(is_resource_entity)))
        end
        
        -- Raise event for resource entities (trees/rocks)
        if is_resource_entity then
            if DEBUG then
                game.print(string.format("[DEBUG mining.finalize_mining] Tick %d: About to raise on_agent_entity_destroyed event, event_id=%s", 
                    game.tick, tostring(custom_events.on_agent_entity_destroyed)))
            end
            script.raise_event(custom_events.on_agent_entity_destroyed, {
                entity = nil,  -- Entity is already destroyed, pass nil
                agent_id = self.agent_id,
                entity_name = mining_state.entity_name,
                entity_type = mining_state.entity_type,
                position = mining_state.entity_position,
            })
            if DEBUG then
                game.print(string.format("[DEBUG mining.finalize_mining] Tick %d: Successfully raised on_agent_entity_destroyed event", game.tick))
            end
        else
            if DEBUG then
                game.print(string.format("[DEBUG mining.finalize_mining] Tick %d: NOT raising event - not a resource entity", game.tick))
            end
        end
    else
        if DEBUG then
            game.print(string.format("[DEBUG mining.finalize_mining] Tick %d: NOT raising event - reason=%s, has_name=%s, has_position=%s", 
                game.tick, reason or "nil", tostring(mining_state and mining_state.entity_name ~= nil), 
                tostring(mining_state and mining_state.entity_position ~= nil)))
        end
    end
    
    -- Clear mining state
    self.mining = {}
    self.character.clear_selected_entity()
    self.character.mining_state = { mining = false }
    
    return {
        success = reason ~= "cancelled",
        reason = reason,
        count = count,
        actual_products = actual_products,
        actual_ticks = actual_ticks,
    }
end

--- Cancel active mining (convenience wrapper)
--- @param self Agent
--- @return table Result
function MiningActions.stop_mining(self)
    return self:finalize_mining("cancelled")
end

--- Process mining state (called from Agent:process())
--- @param self Agent
function MiningActions.process_mining(self)
    local mining_state = self.mining
    
    -- Check if we WERE mining (have mining state) but Factorio stopped it
    -- This happens when entity is depleted - Factorio auto-clears mining_state
    if mining_state and mining_state.mode and not self.character.mining_state.mining then
        -- Factorio stopped mining for us - entity was depleted
        local reason = mining_state.mode == MINING_MODE.INCREMENTAL and "completed" or "depleted"
        if DEBUG then
            game.print(string.format("[DEBUG mining.process_mining] Tick %d: Factorio stopped mining, calling finalize_mining with reason=%s", 
                game.tick, reason))
        end
        self:finalize_mining(reason)
        return
    end
    
    -- Not mining at all
    if not self.character.mining_state.mining then
        return
    end
    
    local entity = self.character.selected
    
    -- Check entity validity (depleted) - backup check
    if not entity or not entity.valid then
        local reason = mining_state and mining_state.mode == MINING_MODE.INCREMENTAL and "completed" or "depleted"
        if DEBUG then
            game.print(string.format("[DEBUG mining.process_mining] Tick %d: Entity invalid, calling finalize_mining with reason=%s", 
                game.tick, reason))
        end
        self:finalize_mining(reason)
        return
    end
    
    -- Only incremental mode needs per-tick processing
    if mining_state.mode == MINING_MODE.INCREMENTAL then
        local current_progress = self.character.character_mining_progress or 0
        local last_progress = mining_state.last_progress or 0
        local threshold = mining_state.completion_threshold or 0.99
        
        -- Detect cycle completion: was at threshold, now dropped (reset)
        if last_progress > threshold and current_progress < last_progress then
            mining_state.count_progress = mining_state.count_progress + 1
            
            -- Render floating text using localized string format
            -- Format: +<amount> <icon> <localised name> (<total>)
            local total_count = self.character.get_main_inventory().get_item_count(entity.name)
            local text = {
                "",
                "+1 ",
                "[item=" .. entity.name .. "]",
                {"item-name." .. entity.name},
                " (", total_count, ")"
            }
            debug_render.render_player_floating_text(text, entity.position, 1)
            
            -- Check if target reached
            if mining_state.target_count and mining_state.count_progress >= mining_state.target_count then
                self:finalize_mining("completed")
                return
            end
        end
        
        mining_state.last_progress = current_progress
    end
    -- DEPLETE mode: nothing to do, just wait for entity.valid == false
end

return MiningActions
