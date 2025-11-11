local AsyncAction = require("types.AsyncAction")

--- @class CraftEnqueueParams : ParamSpec
--- @field agent_id number
--- @field recipe string Recipe prototype name (validated against agent's force)
--- @field count number|nil Desired crafts; defaults to 1
local CraftEnqueueParams = AsyncAction.ParamSpec:new({
    agent_id = { type = "number", required = true },
    recipe = { type = "recipe", required = true },
    count = { type = "number", required = false },
})

--- @class CraftCancelParams : ParamSpec
--- @field agent_id number
--- @field recipe string Recipe prototype name to cancel (validated against agent's force)
--- @field count number|nil Count to cancel, or all if not specified
local CraftCancelParams = AsyncAction.ParamSpec:new({
    agent_id = { type = "number", required = true },
    recipe = { type = "recipe", required = true },
    count = { type = "number", required = false },
})

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
    
    -- Get agent
    local agent = storage.agents[agent_id]
    if not agent or not agent.valid then
        return self:_post_run({ success = false, error = "Agent not found or invalid" }, p)
    end
    
    -- Recipe is already validated by ParamSpec against agent's force
    -- Get recipe prototype for craftable_count check
    local recipe_proto = (prototypes and prototypes.recipe and prototypes.recipe[recipe_name])
    if not recipe_proto then
        -- This should not happen if ParamSpec validation worked, but keep as safety check
        return self:_post_run({ success = false, error = "Recipe prototype not found: " .. recipe_name }, p)
    end

    -- Validate recipe is unlocked for agent's force
    local force = agent.force
    local recipe = force.recipes[recipe_name]
    if not recipe then
        return self:_post_run({ success = false, error = "Recipe not found in force: " .. recipe_name }, p)
    end
    if not recipe.enabled then
        return self:_post_run({ success = false, error = "Recipe is not unlocked: " .. recipe_name }, p)
    end

    -- game.print("Trying to craft: " .. recipe_name)
    
    -- Validate craftable
    local craftable_count = agent.get_craftable_count(recipe_proto)
    game.print("Craftable count: " .. craftable_count)
    if craftable_count <= 0 then
        return self:_post_run({ 
            success = false,
            error = "Cannot craft recipe: insufficient ingredients or recipe not available" 
        }, p)
    end
    game.print("Craftable count after validation: " .. craftable_count)
    
    -- Generate action_id and store tracking (before starting craft)
    local action_id, rcon_tick = self:generate_action_id(agent_id)
    
    -- Get recipe products for tracking
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
    
    -- Snapshot current product counts in inventory BEFORE starting craft
    local start_products = {}
    for item_name, _ in pairs(products) do
        start_products[item_name] = agent.get_item_count(item_name)
    end
    
    -- Debug: log products and start counts
    game.print("Products to track: " .. helpers.table_to_json(products))
    game.print("Start product counts: " .. helpers.table_to_json(start_products))
    
    -- Start crafting
    local count_to_queue = math.min(count_requested, craftable_count)
    local count_started = agent.begin_crafting{
        recipe = recipe_proto,
        count = count_to_queue,
        silent = true
    }
    
    if count_started == 0 then
        return self:_post_run({ success = false, error = "Failed to start crafting" }, p)
    end
    
    game.print(helpers.table_to_json(agent.crafting_queue))
    self:store_tracking("craft_in_progress", agent_id, action_id, rcon_tick, {
        recipe = recipe_name,
        count_requested = count_requested,
        count_queued = count_started,
        start_queue_size = agent.crafting_queue_size,
        start_products = start_products,
        products = products,
        cancelled = false,
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
    local agent = storage.agents[agent_id]
    if not agent or not agent.valid then
        return self:create_cancel_result(false, false, nil, {error = "Agent not found or invalid"})
    end
    
    -- Validate tracking exists and matches
    if not tracking then
        return self:create_cancel_result(false, false, nil, {error = "No active crafting found for this recipe"})
    end
    
    if tracking.recipe ~= recipe_name then
        return self:create_cancel_result(false, false, nil, {
            error = string.format("Recipe '%s' does not match tracked recipe '%s'", recipe_name, tracking.recipe)
        })
    end
    
    -- Check if queue is empty
    local queue_size = agent.crafting_queue_size or 0
    if queue_size == 0 then
        return self:create_cancel_result(false, false, nil, {error = "Crafting queue is empty"})
    end
    
    -- Find the recipe in the queue and cancel it
    local queue = agent.crafting_queue
    if not queue then
        return self:create_cancel_result(false, false, nil, {error = "Crafting queue is empty"})
    end
    
    local target_index = nil
    for _, item in pairs(queue) do
        if item.recipe == recipe_name and not item.prerequisite then
            target_index = item.index
            break
        end
    end
    
    if not target_index then
        return self:create_cancel_result(false, false, nil, {
            error = "Recipe not found in crafting queue"
        })
    end
    
    -- Cancel the recipe (and its prerequisites will be auto-cancelled)
    local actual_count_to_cancel = count_to_cancel or tracking.count_queued
    agent.cancel_crafting{index = target_index, count = actual_count_to_cancel}
    
    -- Mark as cancelled in tracking so on_tick can handle UDP notification
    tracking.cancelled = true
    tracking.cancel_tick = game.tick
    tracking.count_cancelled = actual_count_to_cancel
    
    -- Check remaining queue size to determine if fully cancelled
    local remaining_queue_size = agent.crafting_queue_size or 0
    local fully_cancelled = (remaining_queue_size < tracking.start_queue_size)
    
    return self:create_cancel_result(true, fully_cancelled, tracking.action_id, {
        recipe = recipe_name,
        count_cancelled = actual_count_to_cancel,
        remaining_queue_size = remaining_queue_size
    })
end

return { action = CraftEnqueueAction, params = CraftEnqueueParams }