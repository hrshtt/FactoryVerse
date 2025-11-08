local AsyncAction = require("types.AsyncAction")
local agent_helpers = require("game_state.agent.helpers")

--- @class CraftEnqueueParams : ParamSpec
--- @field agent_id number
--- @field recipe string Recipe prototype name
--- @field count number|nil Desired crafts; defaults to 1
local CraftEnqueueParams = AsyncAction.ParamSpec:new({
    agent_id = { type = "number", required = true },
    recipe = { type = "string", required = true },
    count = { type = "number", required = false },
})

--- @class CraftCancelParams : ParamSpec
--- @field agent_id number
--- @field recipe string Recipe prototype name to cancel
--- @field count number|nil Count to cancel, or all if not specified
local CraftCancelParams = AsyncAction.ParamSpec:new({
    agent_id = { type = "number", required = true },
    recipe = { type = "string", required = true },
    count = { type = "number", required = false },
})

--- Get item products from recipe prototype
--- @param recipe_proto table
--- @return table<string, number>
local function get_item_products(recipe_proto)
    local products = {}
    for _, prod in ipairs(recipe_proto.products or {}) do
        if prod.type == nil or prod.type == "item" then
            local name = prod.name
            local amount = prod.amount or prod.amount_min or 0
            if name and amount and amount > 0 then
                products[name] = (products[name] or 0) + amount
            end
        end
    end
    return products
end

--- Snapshot product items in agent inventory
--- @param agent LuaEntity
--- @param products table<string, number>
--- @return table<string, number>
local function snapshot_product_items(agent, products)
    local snapshot = {}
    for item_name, _ in pairs(products) do
        snapshot[item_name] = agent_helpers.get_actor_item_count(agent, item_name)
    end
    return snapshot
end

--- Cancel recipe from queue by iterating and cancelling from index 0
--- @param agent LuaEntity
--- @param count_to_cancel number|nil How many to cancel (nil = all)
--- @return number Count actually cancelled
local function cancel_recipe_from_queue(agent, count_to_cancel)
    local cancelled_count = 0
    local target_count = count_to_cancel or math.huge
    
    while cancelled_count < target_count and agent.crafting_queue_size > 0 do
        local queue_size_before = agent.crafting_queue_size
        agent.cancel_crafting{index = 0, count = 1}
        
        if agent.crafting_queue_size < queue_size_before then
            cancelled_count = cancelled_count + 1
        else
            break  -- Queue size didn't decrease, stop
        end
    end
    
    return cancelled_count
end

--- Send UDP notification for cancelled crafting
--- @param tracking table Tracking entry
--- @param agent_id number
--- @param count_cancelled number
--- @param actual_products table<string, number>
--- @param count_crafted number
local function send_cancel_udp(tracking, agent_id, count_cancelled, actual_products, count_crafted)
    local payload = {
        action_id = tracking.action_id or string.format("craft_enqueue_unknown_%d_%d", tracking.rcon_tick or game.tick, agent_id),
        agent_id = agent_id,
        action_type = "agent_crafting_enqueue",
        rcon_tick = tracking.rcon_tick or game.tick,
        completion_tick = game.tick,
        success = true,
        cancelled = true,
        result = {
            agent_id = agent_id,
            recipe = tracking.recipe,
            count_requested = tracking.count_requested or 0,
            count_queued = tracking.count_queued or 0,
            count_crafted = count_crafted or 0,
            count_cancelled = count_cancelled,
            products = actual_products or {}
        }
    }
    
    local json_payload = helpers.table_to_json(payload)
    pcall(function() helpers.send_udp(34202, json_payload) end)
end

--- @class CraftEnqueueAction : AsyncAction
local CraftEnqueueAction = AsyncAction:new("agent.crafting.enqueue", CraftEnqueueParams, nil, {
    cancel_params = CraftCancelParams,
    cancel_storage_key = "craft_in_progress",
})

--- @param params CraftEnqueueParams
--- @return table
function CraftEnqueueAction:run(params)
    local p = self:_pre_run(params)
    ---@cast p CraftEnqueueParams
    
    local agent_id = p.agent_id
    local recipe_name = p.recipe
    local count_requested = math.max(1, math.floor(p.count or 1))
    
    -- Get agent and recipe
    local agent = self.game_state.agent:get_agent(agent_id)
    if not agent or not agent.valid then
        return self:_post_run({ success = false, error = "Agent not found or invalid" }, p)
    end
    
    local recipe_proto = (prototypes and prototypes.recipe and prototypes.recipe[recipe_name])
    if not recipe_proto then
        return self:_post_run({ success = false, error = "Unknown recipe: " .. recipe_name }, p)
    end
    
    -- Validate craftable
    local craftable_count = agent.get_craftable_count(recipe_proto)
    if craftable_count <= 0 then
        return self:_post_run({ 
            success = false, 
            error = "Cannot craft recipe: insufficient ingredients or recipe not available" 
        }, p)
    end
    
    -- Queue recipe
    local count_to_queue = math.min(count_requested, craftable_count)
    local count_started = agent.begin_crafting{
        recipe = recipe_proto,
        count = count_to_queue,
        silent = true
    }
    
    if count_started == 0 then
        return self:_post_run({ success = false, error = "Failed to start crafting" }, p)
    end
    
    -- Generate action_id and store tracking
    local action_id, rcon_tick = self:generate_action_id(agent_id)
    local products = get_item_products(recipe_proto)
    local start_products = snapshot_product_items(agent, products)
    
    self:store_tracking("craft_in_progress", agent_id, action_id, rcon_tick, {
        recipe = recipe_name,
        count_requested = count_requested,
        count_queued = count_started,
        start_queue_size = agent.crafting_queue_size,
        start_products = start_products,
        products = products
    })
    
    -- Return async result
    return self:_post_run(
        self:create_async_result(action_id, rcon_tick, {
            recipe = recipe_name,
            count_requested = count_requested,
            count_queued = count_started
        }),
        p
    )
end

--- @param cancel_params CraftCancelParams
--- @param tracking table|nil
--- @return table
function CraftEnqueueAction:_do_cancel(cancel_params, tracking)
    local agent_id = cancel_params.agent_id
    local recipe_name = cancel_params.recipe
    local count_to_cancel = cancel_params.count
    
    -- Get agent
    local agent = self.game_state.agent:get_agent(agent_id)
    if not agent or not agent.valid or agent.type ~= "character" then
        return self:create_cancel_result(false, false, nil, {error = "Agent not found or invalid"})
    end
    
    -- Validate tracking
    if tracking and tracking.recipe ~= recipe_name then
        return self:create_cancel_result(false, false, nil, {
            error = string.format("Recipe '%s' does not match tracked recipe '%s'", recipe_name, tracking.recipe)
        })
    end
    
    -- Check queue
    local queue_size = agent.crafting_queue_size or 0
    if queue_size == 0 then
        return self:create_cancel_result(false, false, nil, {error = "Crafting queue is empty"})
    end
    
    -- Calculate items already crafted
    local count_crafted = 0
    local actual_products = {}
    if tracking then
        actual_products, count_crafted = self.game_state.agent.crafting:calculate_crafted_items(agent, tracking)
    end
    
    -- Cancel from queue
    local count_cancelled = cancel_recipe_from_queue(agent, count_to_cancel)
    if count_cancelled == 0 then
        return self:create_cancel_result(false, false, nil, {error = "Failed to cancel any items"})
    end
    
    -- Determine if complete or partial cancellation
    local remaining_queue_size = agent.crafting_queue_size or 0
    local total_queued = tracking and tracking.count_queued or count_cancelled
    local everything_cancelled = (remaining_queue_size == 0) or (tracking and count_cancelled >= total_queued)
    
    -- Handle tracking and UDP
    if tracking then
        if everything_cancelled then
            -- Complete cancellation - send UDP, tracking will be cleaned by base cancel()
            send_cancel_udp(tracking, agent_id, count_cancelled, actual_products, count_crafted)
        else
            -- Partial cancellation - update tracking, let game state handle completion
            tracking.count_queued = tracking.count_queued - count_cancelled
            tracking.start_queue_size = remaining_queue_size
        end
    end
    
    return self:create_cancel_result(true, true, tracking and tracking.action_id, {
        recipe = recipe_name,
        count_cancelled = count_cancelled,
        count_crafted = count_crafted,
        remaining_queue_size = remaining_queue_size
    })
end

return { action = CraftEnqueueAction, params = CraftEnqueueParams }

