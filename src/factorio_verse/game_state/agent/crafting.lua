--- Agent crafting completion monitoring
--- Handles crafting job completion detection, inventory tracking, and UDP notifications

--- @class CraftingModule
local M = {}
M.__index = M

-- ============================================================================
-- CRAFTING COMPLETION MONITORING
-- ============================================================================

--- Send UDP notification for crafting completion or cancellation
--- @param tracking table Tracking entry from storage.craft_in_progress
--- @param agent_id number
--- @param agent LuaEntity
local function send_craft_udp(tracking, agent_id, agent)
    local completion_tick = game.tick
    
    -- Use count_queued as the primary source of truth for how many were crafted
    -- This is more reliable than inventory delta, especially if agent already had items
    local count_crafted = tracking.count_queued or 0
    
    -- If cancelled, subtract cancelled count
    if tracking.cancelled and tracking.count_cancelled then
        count_crafted = math.max(0, count_crafted - tracking.count_cancelled)
    end
    
    -- Calculate actual products from recipe and count_crafted
    local actual_products = {}
    if tracking.products and count_crafted > 0 then
        for item_name, amount_per_craft in pairs(tracking.products) do
            local total_amount = amount_per_craft * count_crafted
            if total_amount > 0 then
                actual_products[item_name] = total_amount
            end
        end
    end
    
    -- Debug: log tracking data
    game.print("Craft completion tracking - count_queued: " .. tostring(tracking.count_queued))
    game.print("Craft completion tracking - count_cancelled: " .. tostring(tracking.count_cancelled))
    game.print("Craft completion tracking - count_crafted: " .. tostring(count_crafted))
    game.print("Craft completion tracking - products: " .. helpers.table_to_json(actual_products))
    
    -- Also verify with inventory delta for debugging (but don't use it for count_crafted)
    if tracking.products and tracking.start_products then
        game.print("Inventory delta verification:")
        for item_name, amount_per_craft in pairs(tracking.products) do
            local current_count = agent.get_item_count(item_name)
            local start_count = tracking.start_products[item_name] or 0
            local delta = current_count - start_count
            game.print(string.format("  Product %s: start=%d, current=%d, delta=%d, expected=%d", 
                item_name, start_count, current_count, delta, amount_per_craft * count_crafted))
        end
    end
    
    -- Build payload
    local payload = {
        action_id = tracking.action_id,
        agent_id = agent_id,
        action_type = "agent_crafting_enqueue",
        start_tick = tracking.rcon_tick,
        completion_tick = completion_tick,
        success = true,
        cancelled = tracking.cancelled or false,
        result = {
            agent_id = agent_id,
            recipe = tracking.recipe,
            count_requested = tracking.count_requested or 0,
            count_queued = tracking.count_queued or 0,
            count_crafted = count_crafted,
            count_cancelled = tracking.count_cancelled or 0,
            products = actual_products
        }
    }
    
    local json_payload = helpers.table_to_json(payload)
    pcall(function() helpers.send_udp(34202, json_payload) end)
end

--- Tick handler for crafting completion monitoring
--- @param event table
function M.on_tick(event)
    if not storage.craft_in_progress then return end
    
    for agent_id, tracking in pairs(storage.craft_in_progress) do
        local agent = storage.agents[agent_id]
        
        -- Clean up if agent invalid
        if not agent or not agent.valid then
            storage.craft_in_progress[agent_id] = nil
            goto continue
        end
        
        -- Check completion conditions
        local current_queue_size = agent.crafting_queue_size or 0
        local start_queue_size = tracking.start_queue_size or 0
        local completed = false
        
        -- If cancelled, check if queue actually changed (cancellation took effect)
        if tracking.cancelled then
            if current_queue_size < start_queue_size then
                completed = true
            end
        else
            -- Normal completion: queue decreased or became empty
            if current_queue_size < start_queue_size then
                completed = true
            elseif current_queue_size == 0 and (agent.crafting_queue_progress or 0) == 0 and start_queue_size > 0 then
                completed = true
            end
        end
        
        if completed then
            send_craft_udp(tracking, agent_id, agent)
            storage.craft_in_progress[agent_id] = nil
        end
        
        ::continue::
    end
end

--- Get event handlers for registration
--- @return table Event handlers keyed by event ID
function M.get_event_handlers()
    return {
        [defines.events.on_tick] = M.on_tick
    }
end

return M