--- Agent crafting action methods
--- Methods operate directly on Agent instances (self)
--- State is stored in self.crafting (in_progress)
--- These methods are mixed into the Agent class at module level

local CraftingActions = {}

--- Enqueue crafting recipe (async)
--- @param recipe_name string Recipe name
--- @param count number|nil Count to craft (default: 1)
--- @return table Result with {success, queued, action_id, tick, recipe, count_queued}
function CraftingActions.craft_enqueue(self, recipe_name, count)
    if not (self.entity and self.entity.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    if not recipe_name or type(recipe_name) ~= "string" then
        error("Agent: recipe_name (string) is required")
    end
    
    count = math.max(1, math.floor(count or 1))
    
    -- Validate recipe is available to agent's force
    local force = self.entity.force
    if not force then
        error("Agent: Agent force is invalid")
    end
    
    local recipe = force.recipes[recipe_name]
    if not recipe or not recipe.enabled then
        error("Agent: Recipe '" .. recipe_name .. "' is not available to agent's force")
    end
    
    -- Get recipe prototype
    local recipe_proto = prototypes and prototypes.recipe and prototypes.recipe[recipe_name]
    if not recipe_proto then
        error("Agent: Recipe prototype not found: " .. recipe_name)
    end
    
    -- Validate craftable
    local craftable_count = self.entity.get_craftable_count(recipe_proto)
    if craftable_count <= 0 then
        error("Agent: Cannot craft recipe: insufficient ingredients or recipe not available")
    end
    
    -- Generate action ID
    local action_id = string.format("craft_enqueue_%d_%d", game.tick, self.agent_id)
    local rcon_tick = game.tick
    
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
        start_products[item_name] = self.entity.get_item_count(item_name)
    end
    
    -- Start crafting
    local count_to_queue = math.min(count, craftable_count)
    local count_started = self.entity.begin_crafting{
        recipe = recipe_proto,
        count = count_to_queue,
        silent = true
    }
    
    if count_started == 0 then
        error("Agent: Failed to start crafting")
    end
    
    -- Store tracking
    self.crafting.in_progress = {
        action_id = action_id,
        recipe = recipe_name,
        count_requested = count,
        count_queued = count_started,
        start_queue_size = self.entity.crafting_queue_size,
        start_products = start_products,
        products = products,
        cancelled = false,
    }
    
    -- Enqueue async result message
    self:enqueue_message({
        action = "craft_enqueue",
        agent_id = self.agent_id,
        success = true,
        queued = true,
        action_id = action_id,
        tick = rcon_tick,
        recipe = recipe_name,
        count_requested = count,
        count_queued = count_started,
    }, "crafting")
    
    return {
        success = true,
        queued = true,
        action_id = action_id,
        tick = rcon_tick,
        recipe = recipe_name,
        count_queued = count_started,
    }
end

--- Dequeue crafting recipe
--- @param recipe_name string Recipe name
--- @param count number|nil Count to dequeue (nil to dequeue all)
--- @return table Result
function CraftingActions.craft_dequeue(self, recipe_name, count)
    if not (self.entity and self.entity.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    if not recipe_name or type(recipe_name) ~= "string" then
        error("Agent: recipe_name (string) is required")
    end
    
    -- Validate tracking exists and matches
    local tracking = self.crafting.in_progress
    if not tracking then
        error("Agent: No active crafting found")
    end
    
    if tracking.recipe ~= recipe_name then
        error(string.format("Agent: Recipe '%s' does not match tracked recipe '%s'", recipe_name, tracking.recipe))
    end
    
    -- Check if queue is empty
    local queue_size = self.entity.crafting_queue_size or 0
    if queue_size == 0 then
        error("Agent: Crafting queue is empty")
    end
    
    -- Find the recipe in the queue
    local queue = self.entity.crafting_queue
    if not queue then
        error("Agent: Crafting queue is empty")
    end
    
    local target_index = nil
    for _, item in pairs(queue) do
        if item.recipe == recipe_name and not item.prerequisite then
            target_index = item.index
            break
        end
    end
    
    if not target_index then
        error("Agent: Recipe not found in crafting queue")
    end
    
    -- Cancel the recipe
    local count_to_cancel = count or tracking.count_queued
    self.entity.cancel_crafting{index = target_index, count = count_to_cancel}
    
    -- Mark as cancelled in tracking
    tracking.cancelled = true
    tracking.cancel_tick = game.tick
    tracking.count_cancelled = count_to_cancel
    
    -- Check remaining queue size
    local remaining_queue_size = self.entity.crafting_queue_size or 0
    local fully_cancelled = (remaining_queue_size < tracking.start_queue_size)
    
    -- Clear tracking if fully cancelled
    if fully_cancelled then
        self.crafting.in_progress = nil
    end
    
    -- Enqueue cancel message
    self:enqueue_message({
        action = "craft_dequeue",
        agent_id = self.agent_id,
        success = true,
        cancelled = fully_cancelled,
        action_id = tracking.action_id,
        recipe = recipe_name,
        count_cancelled = count_to_cancel,
        remaining_queue_size = remaining_queue_size,
        tick = game.tick or 0,
    }, "crafting")
    
    return {
        success = true,
        cancelled = fully_cancelled,
        action_id = tracking.action_id,
        recipe = recipe_name,
        count_cancelled = count_to_cancel,
        remaining_queue_size = remaining_queue_size,
    }
end

return CraftingActions

