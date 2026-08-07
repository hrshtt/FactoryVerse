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

-- RCON can arm character mining between simulation ticks.  At accelerated
-- game speeds Factorio may expose one stopped tick before the scripted mining
-- state survives.  Never translate that transport/tick boundary directly to
-- depletion: re-arm the exact LuaEntity a bounded number of times, then report
-- an explicit reconciliation failure with the observed facts.
local MAX_DEPLETION_RESTARTS = 3

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
--- @return number Threshold value (progress >= threshold means cycle about to complete)
local function get_completion_threshold(character, entity)
    local mining_time = entity.prototype.mineable_properties.mining_time
    local mining_speed = get_effective_mining_speed(character)
    local progress_per_tick = mining_speed / (mining_time * 60)
    -- Use a larger margin (1.5x progress_per_tick) to ensure we catch the cycle
    -- even with floating-point imprecision. The cycle detection checks
    -- last_progress >= threshold AND current_progress < last_progress,
    -- so a lower threshold is more permissive and safer.
    return 1.0 - (progress_per_tick * 1.5) - 0.001
end

--- Get the product contract declared by a mineable entity.
--- @param entity LuaEntity Entity being mined
--- @return table expected fixed counts
--- @return table product names to inventory-snapshot
--- @return boolean whether every product amount/probability is deterministic
local function get_product_contract(entity)
    local proto = entity.prototype
    local mineable_props = proto.mineable_properties
    
    if not mineable_props or not mineable_props.products then
        return {}, {}, true
    end
    
    local expected = {}
    local product_names = {}
    local deterministic = true
    for _, product in pairs(mineable_props.products) do
        if product.type and product.type ~= "item" then
            deterministic = false
        else
            product_names[product.name] = true
            local probability = product.probability or 1
            local fixed_amount = product.amount
            if not fixed_amount and product.amount_min and product.amount_max and
               product.amount_min == product.amount_max then
                fixed_amount = product.amount_min
            end
            if probability ~= 1 or not fixed_amount then
                deterministic = false
            else
                expected[product.name] =
                    (expected[product.name] or 0) + fixed_amount
            end
        end
    end
    
    return expected, product_names, deterministic
end

--- Snapshot current inventory counts for common mining products
--- @param character LuaEntity Character entity
--- @return table {item_name = count, ...}
local function snapshot_inventory(character, product_names)
    local snapshot = {}
    local inventory = character.get_main_inventory()
    if not inventory then return snapshot end

    for name, _ in pairs(product_names or {}) do
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

local function entity_identity(entity, fallback)
    if entity and entity.valid then
        return {
            name = entity.name,
            type = entity.type,
            position = {x = entity.position.x, y = entity.position.y},
            unit_number = entity.unit_number,
        }
    end
    return fallback
end

local function identities_match(left, right)
    if not left or not right then return false end
    if left.name ~= right.name or left.type ~= right.type then return false end
    if left.unit_number and right.unit_number then
        return left.unit_number == right.unit_number
    end
    return left.position and right.position and
        math.abs(left.position.x - right.position.x) < 0.01 and
        math.abs(left.position.y - right.position.y) < 0.01
end

--- Resolve a cursor/mining point that makes Factorio select this exact entity.
--- Tree selection boxes can overlap even when their anchors are distinct, so
--- ``update_selected_entity(entity.position)`` is not an identity-preserving
--- operation.  Sampling within the target prototype's selection box lets the
--- engine choose the requested LuaEntity rather than a neighbouring tree.
local function select_exact_entity(character, entity)
    if not (entity and entity.valid) then return nil end

    local relative_box = entity.prototype and entity.prototype.selection_box
    local fractions = {0.5, 0.2, 0.8, 0.05, 0.95}
    local candidates = {{x = entity.position.x, y = entity.position.y}}
    if relative_box and relative_box.left_top and relative_box.right_bottom then
        local left = entity.position.x + relative_box.left_top.x
        local top = entity.position.y + relative_box.left_top.y
        local width = relative_box.right_bottom.x - relative_box.left_top.x
        local height = relative_box.right_bottom.y - relative_box.left_top.y
        for _, y_fraction in ipairs(fractions) do
            for _, x_fraction in ipairs(fractions) do
                table.insert(candidates, {
                    x = left + width * x_fraction,
                    y = top + height * y_fraction,
                })
            end
        end
    end

    local expected = entity_identity(entity)
    for _, candidate in ipairs(candidates) do
        character.update_selected_entity(candidate)
        if identities_match(expected, entity_identity(character.selected)) then
            return candidate
        end
    end
    return nil
end

local function append_causal_trace(mining_state, phase, facts)
    mining_state.causal_trace = mining_state.causal_trace or {}
    local entry = facts or {}
    entry.phase = phase
    entry.tick = game.tick
    table.insert(mining_state.causal_trace, entry)
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
function MiningActions.mine_resource(self, resource_name, max_count, position)
    -- Validate input
    if not resource_name or type(resource_name) ~= "string" then
        error("Agent: resource_name (string) is required")
    end

    position = position or nil
    
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
    
    local search_args = {}
    if position ~= nil then
        search_args.position = position
    else
        search_args.position = { x = agent_pos.x, y = agent_pos.y }
        search_args.radius = radius
    end

    if RESOURCE_TYPE_MAPPING[resource_name] then
        search_args.type = RESOURCE_TYPE_MAPPING[resource_name]
    else
        search_args.name = resource_name
    end
    
    local entities = surface.find_entities_filtered(search_args)
    if position ~= nil and entities and #entities > 0 then
        -- A Factorio position filter matches collision boxes, not exact
        -- entity anchors. Dense/overlapping trees can therefore return a
        -- neighbouring tree first. The DB route supplies the anchor identity;
        -- preserve it exactly so the selected row is the entity we mine.
        local exact_entity = nil
        for _, candidate in pairs(entities) do
            if candidate and candidate.valid and
               math.abs(candidate.position.x - position.x) < 0.01 and
               math.abs(candidate.position.y - position.y) < 0.01 then
                exact_entity = candidate
                break
            end
        end
        entities = exact_entity and {exact_entity} or {}
    end
    if not entities or #entities == 0 then
        if position ~= nil then
            error("Agent: Resource not found at position " .. position.x .. ", " .. position.y)
        else
            error("Agent: Resource not found within reach")
        end
    end
    
    local entity = entities[1]
    if not entity or not entity.valid then
        error("Game: Resource entity is invalid")
    end
    
    -- Determine mining mode and properties
    local mode = get_mining_mode(entity)
    local prototype_expected, product_names, deterministic_products =
        get_product_contract(entity)
    local stochastic = STOCHASTIC_ENTITIES[entity.name] == true or
        not deterministic_products
    
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
        -- Inventory delta is a causal fact for every depleting entity.  The
        -- previous deterministic path returned prototype products even when
        -- the character received nothing.
        expected_products = prototype_expected
        start_inventory = snapshot_inventory(self.character, product_names)
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
        entity = entity,
        entity_identity = entity_identity(entity),
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
        armed = false,
        depletion_restarts = 0,
        causal_trace = {},
    }

    append_causal_trace(self.mining, "started", {
        identity = self.mining.entity_identity,
        inventory_before = start_inventory,
    })
    
    -- ``mine_resource`` is entered through an RCON command, outside the
    -- regular on_tick state-machine phase.  Queue the intent here and arm the
    -- character from ``process_mining`` on the next tick; directly setting
    -- mining_state at this boundary can be cleared before Factorio simulates a
    -- mining tick, especially when the game is accelerated.
    
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
    elseif mining_state.mode == MINING_MODE.DEPLETE and mining_state.start_inventory then
        -- Depleting actions report only products observed in the character's
        -- inventory, never prototype-derived expected products.
        actual_products = get_inventory_diff(self.character, mining_state.start_inventory)
        if not next(actual_products) then
            actual_products = nil  -- Empty table -> nil
        end
    end

    local exact_entity_exists = mining_state.entity and mining_state.entity.valid or false
    local current_identity = entity_identity(mining_state.entity, mining_state.entity_identity)
    local inventory_after = {}
    local inventory = self.character.get_main_inventory()
    for item_name, _ in pairs(mining_state.start_inventory or {}) do
        inventory_after[item_name] = inventory and inventory.get_item_count(item_name) or 0
    end

    local products_agree = true
    if mining_state.mode == MINING_MODE.DEPLETE then
        if mining_state.is_stochastic then
            -- Zero products is a valid outcome for probabilistic prototypes;
            -- the observed inventory delta (including empty) is authoritative.
            products_agree = true
        elseif not actual_products or not next(actual_products) then
            products_agree = false
        else
            for item_name, expected_count in pairs(mining_state.expected_products or {}) do
                if actual_products[item_name] ~= expected_count then
                    products_agree = false
                end
            end
            for item_name, actual_count in pairs(actual_products) do
                if (mining_state.expected_products or {})[item_name] ~= actual_count then
                    products_agree = false
                end
            end
        end
        if reason == "depleted" and (exact_entity_exists or not products_agree) then
            reason = "reconciliation_failed"
        end
    end

    append_causal_trace(mining_state, "finalized", {
        identity = current_identity,
        engine_exists = exact_entity_exists,
        inventory_after = inventory_after,
        inventory_delta = actual_products or {},
        expected_products = mining_state.expected_products or {},
        products_agree = products_agree,
        outcome = reason,
    })

    -- Raise mining completed event for fv_snapshot to log
    -- Only raise when there are actual products (not for cancelled with 0 products)
    if reason ~= "reconciliation_failed" and actual_products and next(actual_products) then
        script.raise_event(custom_events.on_agent_mining_completed, {
            agent_id = self.agent_id,
            tick = game.tick,
            entity_name = mining_state.entity_name,
            entity_type = mining_state.entity_type,
            position = mining_state.entity_position,
            mode = mining_state.mode,
            reason = reason,
            products = actual_products,
        })
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
        success = reason ~= "cancelled" and reason ~= "reconciliation_failed",
        status = reason == "cancelled" and "cancelled" or
            (reason == "reconciliation_failed" and "failed" or "completed"),
        action_id = mining_state.action_id,
        tick = game.tick,
        reason = reason,
        entity_name = mining_state.entity_name,
        position = mining_state.entity_position,
        mode = mining_state.mode,
        count = count,
        actual_products = actual_products,
        actual_ticks = actual_ticks,
        causal_facts = {
            identity = mining_state.entity_identity,
            engine_exists = exact_entity_exists,
            inventory_before = mining_state.start_inventory or {},
            inventory_after = inventory_after,
            inventory_delta = actual_products or {},
            expected_products = mining_state.expected_products or {},
            products_agree = products_agree,
            destroy_event_tick = reason == "depleted" and game.tick or nil,
            depletion_restarts = mining_state.depletion_restarts or 0,
            trace = mining_state.causal_trace or {},
        },
    }
    
    if reason == "cancelled" then
        message.cancelled = true
    end
    
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
        -- This custom event is necessary because character mining doesn't raise Factorio's player events
        if is_resource_entity then
            if DEBUG then
                game.print(string.format("[DEBUG mining.finalize_mining] Tick %d: About to raise on_agent_resource_mined event, event_id=%s", 
                    game.tick, tostring(custom_events.on_agent_resource_mined)))
            end
            script.raise_event(custom_events.on_agent_resource_mined, {
                entity = nil,  -- Entity is already destroyed by Factorio engine
                agent_id = self.agent_id,
                action_id = mining_state.action_id,
                entity_name = mining_state.entity_name,
                entity_type = mining_state.entity_type,
                position = mining_state.entity_position,
                tick = game.tick,
            })
            if DEBUG then
                game.print(string.format("[DEBUG mining.finalize_mining] Tick %d: Successfully raised on_agent_resource_mined event", game.tick))
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


    -- Queue completion only after the same-tick destroy event has been raised.
    -- The Python side still waits for DuckDB because the two UDP transports are
    -- independent, but this preserves causal order at the game source.
    self:enqueue_message(message, "mining")
    
    -- Clear mining state
    self.mining = {}
    self.character.clear_selected_entity()
    self.character.mining_state = { mining = false }
    
    return {
        success = reason ~= "cancelled" and reason ~= "reconciliation_failed",
        reason = reason,
        count = count,
        actual_products = actual_products,
        actual_ticks = actual_ticks,
        causal_facts = message.causal_facts,
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

    -- Early exit if no mining state
    if not mining_state or not mining_state.mode then
        return
    end

    if not mining_state.armed then
        if not (mining_state.entity and mining_state.entity.valid) then
            append_causal_trace(mining_state, "arm_failed", {
                identity = mining_state.entity_identity,
                engine_exists = false,
            })
            self:finalize_mining("reconciliation_failed")
            return
        end
        local can_reach = self.character.can_reach_entity(mining_state.entity)
        local mining_position = can_reach and
            select_exact_entity(self.character, mining_state.entity) or nil
        append_causal_trace(mining_state, "armed", {
            identity = entity_identity(mining_state.entity),
            selected_identity = entity_identity(self.character.selected),
            engine_exists = true,
            can_reach = can_reach,
            mining_position = mining_position,
        })
        if not can_reach or not mining_position then
            self:finalize_mining("reconciliation_failed")
            return
        end
        mining_state.mining_position = mining_position
        self.character.mining_state = {
            mining = true,
            position = mining_position,
        }
        mining_state.armed = true
        return
    end

    -- CRITICAL: Process cycle detection FIRST before any early exit checks
    -- This ensures we don't miss counting cycles if Factorio stops mining
    -- in the same tick that a cycle completes
    if mining_state.mode == MINING_MODE.INCREMENTAL then
        local current_progress = self.character.character_mining_progress or 0
        local last_progress = mining_state.last_progress or 0
        local threshold = mining_state.completion_threshold or 0.99

        -- Detect cycle completion: was at or above threshold, now dropped (reset)
        -- Use >= instead of > to handle floating-point edge cases where
        -- last_progress exactly equals threshold
        if last_progress >= threshold and current_progress < last_progress then
            mining_state.count_progress = mining_state.count_progress + 1

            if DEBUG then
                game.print(string.format("[DEBUG mining.process_mining] Tick %d: Cycle detected! count_progress=%d, last_progress=%.4f, current_progress=%.4f, threshold=%.4f",
                    game.tick, mining_state.count_progress, last_progress, current_progress, threshold))
            end

            -- Render floating text using localized string format
            -- Format: +<amount> <icon> <localised name> (<total>)
            local entity = self.character.selected
            if entity and entity.valid then
                local total_count = self.character.get_main_inventory().get_item_count(entity.name)
                local text = {
                    "",
                    "+1 ",
                    "[item=" .. entity.name .. "]",
                    {"item-name." .. entity.name},
                    " (", total_count, ")"
                }
                debug_render.render_player_floating_text(text, entity.position, 1)
            end

            -- Check if target reached
            if mining_state.target_count and mining_state.count_progress >= mining_state.target_count then
                self:finalize_mining("completed")
                return
            end
        end

        mining_state.last_progress = current_progress
    end

    -- Now check if Factorio stopped mining (entity depleted or other reason)
    -- This check is AFTER cycle detection to ensure we count the final cycle
    if not self.character.mining_state.mining then
        -- A stopped character is not proof of depletion.  For depleting
        -- entities, reconcile against the exact LuaEntity captured at start.
        if mining_state.mode == MINING_MODE.DEPLETE and
           mining_state.entity and mining_state.entity.valid then
            local current_identity = entity_identity(mining_state.entity)
            local selected_identity = entity_identity(self.character.selected)
            local can_reach = self.character.can_reach_entity(mining_state.entity)
            mining_state.depletion_restarts = (mining_state.depletion_restarts or 0) + 1
            append_causal_trace(mining_state, "stopped_while_entity_exists", {
                identity = current_identity,
                selected_identity = selected_identity,
                selected_matches = identities_match(current_identity, selected_identity),
                engine_exists = true,
                can_reach = can_reach,
                restart = mining_state.depletion_restarts,
                inventory_delta = get_inventory_diff(
                    self.character, mining_state.start_inventory or {}
                ),
            })

            local mining_position = can_reach and
                select_exact_entity(self.character, mining_state.entity) or nil
            if can_reach and mining_position and
               mining_state.depletion_restarts <= MAX_DEPLETION_RESTARTS then
                -- A depleting entity credits products only when it becomes
                -- invalid. This branch requires the exact entity to remain
                -- valid, so re-arming cannot double-credit a completed mine.
                mining_state.mining_position = mining_position
                self.character.mining_state = {
                    mining = true,
                    position = mining_position,
                }
                return
            end

            self:finalize_mining("reconciliation_failed")
            return
        end

        local reason = mining_state.mode == MINING_MODE.INCREMENTAL and "completed" or "depleted"
        if DEBUG then
            game.print(string.format("[DEBUG mining.process_mining] Tick %d: Factorio stopped mining, count_progress=%d, calling finalize_mining with reason=%s",
                game.tick, mining_state.count_progress or 0, reason))
        end
        self:finalize_mining(reason)
        return
    end

    local entity = self.character.selected

    -- Check entity validity (depleted) - backup check
    if not entity or not entity.valid then
        local reason = mining_state.mode == MINING_MODE.INCREMENTAL and "completed" or "depleted"
        if DEBUG then
            game.print(string.format("[DEBUG mining.process_mining] Tick %d: Entity invalid, count_progress=%d, calling finalize_mining with reason=%s",
                game.tick, mining_state.count_progress or 0, reason))
        end
        self:finalize_mining(reason)
        return
    end
    -- DEPLETE mode: nothing to do, just wait for entity.valid == false
end

return MiningActions
