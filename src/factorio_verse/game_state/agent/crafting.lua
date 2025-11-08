--- Agent crafting completion monitoring
--- Handles crafting job completion detection, inventory tracking, and UDP notifications

-- Note: Do not capture 'game' at module level - it may be nil during on_load
-- Access 'game' directly in functions where it's guaranteed to be available (event handlers)
local pairs = pairs
local math = math

local agent_helpers = require("game_state.agent.helpers")

local M = {}

-- ============================================================================
-- CRAFTING COMPLETION MONITORING
-- ============================================================================

--- @class CraftingModule
--- @field agent_control table|nil Interface (not currently used, but kept for consistency)
--- @field get_event_handlers fun(self: CraftingModule): table Event handler registration function
--- Initialize crafting module
--- @param agent_control table|nil Interface (optional, for consistency with other modules)
function M:init(agent_control)
    self.agent_control = agent_control
end

--- Calculate actual items crafted by comparing inventory before/after
--- @param agent LuaEntity
--- @param tracking table Tracking entry with start_products and products
--- @return table<string, number> Actual products added to inventory
--- @return number Estimated count crafted
function M:calculate_crafted_items(agent, tracking)
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

--- Send UDP notification for crafting completion
--- @param tracking table Tracking entry from storage.craft_in_progress
--- @param agent_id number
--- @param actual_products table<string, number> Actual items crafted
--- @param count_crafted number Estimated count crafted
local function _send_craft_completion_udp(tracking, agent_id, actual_products, count_crafted)
    local action_id = tracking.action_id
    local rcon_tick = tracking.rcon_tick
    local completion_tick = game.tick
    
    -- New async action completion payload contract
    local payload = {
        action_id = action_id or string.format("craft_enqueue_unknown_%d_%d", rcon_tick or completion_tick, agent_id),
        agent_id = agent_id,
        action_type = "agent_crafting_enqueue",
        rcon_tick = rcon_tick or completion_tick,  -- when action was triggered
        completion_tick = completion_tick,          -- when action completed
        success = true,
        result = {
            agent_id = agent_id,
            recipe = tracking.recipe,
            count_requested = tracking.count_requested or 0,
            count_queued = tracking.count_queued or 0,
            count_crafted = count_crafted,
            products = actual_products
        }
    }
    
    log(string.format("[UDP] Sending craft completion for agent %d: action_id=%s (count_crafted=%d)", 
        agent_id, payload.action_id, count_crafted))
    
    local json_payload = helpers.table_to_json(payload)
    log(string.format("[UDP] Payload: %s", json_payload))
    
    local ok, err = pcall(function() helpers.send_udp(34202, json_payload) end)
    if not ok then
        log(string.format("[UDP] ERROR: %s", err or "unknown"))
    else
        log(string.format("[UDP] ✅ Sent"))
    end
end

--- Tick handler for crafting completion monitoring
--- @param self CraftingModule
--- @param event table
function M:tick_craft_jobs(event)
    if not storage.craft_in_progress then return end
    
    for agent_id, tracking in pairs(storage.craft_in_progress) do
        if not tracking then
            storage.craft_in_progress[agent_id] = nil
        else
            local agent = agent_helpers.get_control_for_agent(agent_id)
            
            -- Clean up if agent invalid
            if not agent or not agent.valid or agent.type ~= "character" then
                log(string.format("[crafting] Agent %d invalid, cleaning up tracking", agent_id))
                storage.craft_in_progress[agent_id] = nil
                goto continue_agent
            end
            
            -- Check if crafting has completed
            local current_queue_size = agent.crafting_queue_size or 0
            local start_queue_size = tracking.start_queue_size or 0
            
            -- Completion detection: queue size decreased (recipe finished and removed)
            local completed = false
            if current_queue_size < start_queue_size then
                completed = true
                log(string.format("[crafting] Agent %d crafting completed (queue size: %d -> %d)", 
                    agent_id, start_queue_size, current_queue_size))
            end
            
            -- Also check: queue empty and no progress (all crafting done)
            if not completed and current_queue_size == 0 and (agent.crafting_queue_progress or 0) == 0 then
                -- Only mark complete if we had something queued
                if start_queue_size > 0 then
                    completed = true
                    log(string.format("[crafting] Agent %d crafting completed (queue empty)", agent_id))
                end
            end
            
            if completed then
                -- Calculate actual items crafted from inventory delta
                local actual_products, count_crafted = self:calculate_crafted_items(agent, tracking)
                
                -- Send UDP completion notification
                _send_craft_completion_udp(tracking, agent_id, actual_products, count_crafted)
                
                -- Clean up tracking entry
                storage.craft_in_progress[agent_id] = nil
            end
        end
        
        ::continue_agent::
    end
end

--- Get event handlers for crafting activities
--- @param self CraftingModule
--- @return table Event handlers keyed by event ID
function M:get_event_handlers()
    return {
        [defines.events.on_tick] = function(event)
            self:tick_craft_jobs(event)
        end
    }
end

return M

