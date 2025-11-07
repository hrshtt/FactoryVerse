local Action = require("types.Action")
local agent_helpers = require("game_state.agent.helpers")

--- @class CraftCancelParams : ParamSpec
--- @field agent_id number
--- @field recipe string            -- recipe prototype name to cancel
--- @field count number|nil         -- count to cancel, or all if not specified
local CraftCancelParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    recipe = { type = "string", required = true },
    count = { type = "number", required = false }
})

--- @class CraftCancelAction : Action
local CraftCancelAction = Action:new("agent.crafting.craft_cancel", CraftCancelParams)

--- Calculate actual items crafted by comparing inventory before/after
--- @param agent LuaEntity
--- @param tracking table Tracking entry with start_products and products
--- @return table<string, number> Actual products added to inventory
--- @return number Estimated count crafted
local function calculate_crafted_items(agent, tracking)
    local products = tracking.products or {}
    local start_products = tracking.start_products or {}
    local actual_products = {}
    
    -- Calculate delta for each product item
    for item_name, _ in pairs(products) do
        local current_count = agent_helpers.get_actor_item_count(agent, item_name)
        local start_count = start_products[item_name] or 0
        local delta = math.max(0, current_count - start_count)
        if delta > 0 then
            actual_products[item_name] = delta
        end
    end
    
    -- Estimate count crafted based on first product (assuming consistent recipe output)
    local count_crafted = 0
    local first_product_name = nil
    local first_product_amount = nil
    for name, amount in pairs(products) do
        first_product_name = name
        first_product_amount = amount
        break
    end
    
    if first_product_name and first_product_amount and first_product_amount > 0 then
        local actual_count = actual_products[first_product_name] or 0
        count_crafted = math.floor(actual_count / first_product_amount)
    end
    
    return actual_products, count_crafted
end

--- Send UDP notification for cancelled crafting
--- @param tracking table Tracking entry from storage.craft_in_progress
--- @param agent_id number
--- @param count_cancelled number How many were cancelled
--- @param actual_products table<string, number> Actual items crafted (if any)
--- @param count_crafted number Estimated count crafted (if any)
local function _send_cancel_completion_udp(tracking, agent_id, count_cancelled, actual_products, count_crafted)
    local action_id = tracking.action_id
    local rcon_tick = tracking.rcon_tick
    local completion_tick = game.tick
    
    -- UDP payload for cancelled crafting
    local payload = {
        action_id = action_id or string.format("craft_enqueue_unknown_%d_%d", rcon_tick or completion_tick, agent_id),
        agent_id = agent_id,
        action_type = "agent_crafting_craft_enqueue",
        rcon_tick = rcon_tick or completion_tick,  -- when action was triggered
        completion_tick = completion_tick,          -- when action completed
        success = true,
        cancelled = true,  -- Indicates this was cancelled
        result = {
            agent_id = agent_id,
            recipe = tracking.recipe,
            count_requested = tracking.count_requested or 0,
            count_queued = tracking.count_queued or 0,
            count_crafted = count_crafted or 0,
            count_cancelled = count_cancelled,
            products = actual_products or {}  -- Only items that were actually crafted
        }
    }
    
    log(string.format("[UDP] Sending craft cancellation for agent %d: action_id=%s (cancelled=%d, crafted=%d)", 
        agent_id, payload.action_id, count_cancelled, count_crafted))
    
    local json_payload = helpers.table_to_json(payload)
    log(string.format("[UDP] Payload: %s", json_payload))
    
    local ok, err = pcall(function() helpers.send_udp(34202, json_payload) end)
    if not ok then
        log(string.format("[UDP] ERROR: %s", err or "unknown"))
    else
        log(string.format("[UDP] ✅ Sent"))
    end
end

--- Cancel recipe from queue by iterating and cancelling from index 0
--- @param agent LuaEntity
--- @param recipe_name string Recipe name to cancel
--- @param count_to_cancel number|nil How many to cancel (nil = all)
--- @param tracking table|nil Tracking entry (for validation)
--- @return number Count actually cancelled
local function cancel_recipe_from_queue(agent, recipe_name, count_to_cancel, tracking)
    local cancelled_count = 0
    local target_count = count_to_cancel or math.huge  -- "all" if not specified
    local initial_queue_size = agent.crafting_queue_size or 0
    
    if initial_queue_size == 0 then
        return 0  -- Nothing to cancel
    end
    
    -- Cancel from index 0 repeatedly until:
    --   1. We've cancelled target_count items
    --   2. Queue is empty
    --   3. Queue size stops decreasing (different recipe or error)
    while cancelled_count < target_count and agent.crafting_queue_size > 0 do
        local queue_size_before = agent.crafting_queue_size
        
        -- Try cancelling 1 from index 0
        agent.cancel_crafting{index = 0, count = 1}
        
        local queue_size_after = agent.crafting_queue_size
        
        if queue_size_after < queue_size_before then
            -- Successfully cancelled 1 item
            cancelled_count = cancelled_count + 1
        else
            -- Size didn't decrease - might be wrong recipe, error, or queue issue
            -- Break to avoid infinite loop
            log(string.format("[craft_cancel] Queue size didn't decrease after cancel attempt (before=%d, after=%d)", 
                queue_size_before, queue_size_after))
            break
        end
    end
    
    return cancelled_count
end

--- @param params CraftCancelParams
--- @return table
function CraftCancelAction:run(params)
    local p = self:_pre_run(params)
    ---@cast p CraftCancelParams
    
    local agent_id = p.agent_id
    local recipe_name = p.recipe
    local count_to_cancel = p.count  -- nil means "all"
    
    -- Get agent entity
    local agent = self.game_state.agent:get_agent(agent_id)
    if not agent or not agent.valid then
        return self:_post_run({ success = false, error = "Agent not found or invalid" }, p)
    end
    
    -- Verify agent is a character
    if agent.type ~= "character" then
        return self:_post_run({ success = false, error = "Agent is not a character entity" }, p)
    end
    
    -- Check if there's a tracking entry
    storage.craft_in_progress = storage.craft_in_progress or {}
    local tracking = storage.craft_in_progress[agent_id]
    
    -- Validate recipe matches tracking (if tracking exists)
    if tracking then
        if tracking.recipe ~= recipe_name then
            return self:_post_run({ 
                success = false, 
                error = string.format("Recipe '%s' does not match tracked recipe '%s'", 
                    recipe_name, tracking.recipe) 
            }, p)
        end
    end
    
    -- Check if queue has items
    local queue_size = agent.crafting_queue_size or 0
    if queue_size == 0 then
        -- Nothing to cancel
        if tracking then
            -- Clean up stale tracking
            storage.craft_in_progress[agent_id] = nil
        end
        return self:_post_run({ 
            success = false, 
            error = "Crafting queue is empty, nothing to cancel" 
        }, p)
    end
    
    -- Calculate what was already crafted (before cancellation)
    local count_crafted = 0
    local actual_products = {}
    if tracking then
        actual_products, count_crafted = calculate_crafted_items(agent, tracking)
    end
    
    -- Cancel the recipe from queue
    local count_cancelled = cancel_recipe_from_queue(agent, recipe_name, count_to_cancel, tracking)
    
    if count_cancelled == 0 then
        return self:_post_run({ 
            success = false, 
            error = "Failed to cancel any items from crafting queue" 
        }, p)
    end
    
    -- Determine if everything was cancelled
    local remaining_queue_size = agent.crafting_queue_size or 0
    local total_queued = tracking and tracking.count_queued or count_cancelled
    local everything_cancelled = (remaining_queue_size == 0) or 
                                (tracking and count_cancelled >= total_queued)
    
    -- Handle UDP completion and tracking cleanup
    if tracking then
        -- Case 1: Nothing crafted, everything cancelled -> Send UDP immediately
        if count_crafted == 0 and everything_cancelled then
            _send_cancel_completion_udp(tracking, agent_id, count_cancelled, actual_products, count_crafted)
            storage.craft_in_progress[agent_id] = nil
        -- Case 2: Some items were crafted, everything done -> Send UDP with only crafted items
        elseif count_crafted > 0 and remaining_queue_size == 0 then
            -- Everything done (some crafted, rest cancelled)
            -- Send UDP with only crafted items (not cancelled ones)
            _send_cancel_completion_udp(tracking, agent_id, count_cancelled, actual_products, count_crafted)
            storage.craft_in_progress[agent_id] = nil
        -- Case 3: Partial cancellation (queue still has items) -> Update tracking, let tick handler complete
        elseif remaining_queue_size > 0 then
            -- Partial cancellation, update tracking
            tracking.count_queued = tracking.count_queued - count_cancelled
            tracking.start_queue_size = remaining_queue_size
            -- Tick handler will detect completion and send UDP with only crafted items
        -- Case 4: Nothing crafted, partial cancellation -> Update tracking, no UDP yet
        else
            -- Partial cancellation, nothing crafted yet, update tracking
            tracking.count_queued = tracking.count_queued - count_cancelled
            tracking.start_queue_size = remaining_queue_size
        end
    else
        -- No tracking entry (external crafting) - just cancel, no UDP
        log(string.format("[craft_cancel] Cancelled %d items for agent %d (no tracking entry)", 
            count_cancelled, agent_id))
    end
    
    log(string.format("[craft_cancel] Cancelled %d items of recipe '%s' for agent %d (crafted=%d, remaining_queue=%d)", 
        count_cancelled, recipe_name, agent_id, count_crafted, remaining_queue_size))
    
    -- Return sync response
    local result = {
        success = true,
        cancelled = true,
        recipe = recipe_name,
        count_cancelled = count_cancelled,
        count_crafted = count_crafted,
        remaining_queue_size = remaining_queue_size
    }
    
    return self:_post_run(result, p)
end

return { action = CraftCancelAction, params = CraftCancelParams }
