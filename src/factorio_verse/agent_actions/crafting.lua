--- Agent crafting action methods
--- Methods operate directly on Agent instances (self)
--- State is stored in self.crafting (in_progress)
--- These methods are mixed into the Agent class at module level

local CraftingActions = {}

local valid_recipe_categories = {
    ["crafting"] = true,
    ["smelting"] = true,
}

function CraftingActions.get_recipes(self, category)
    if category and not valid_recipe_categories[category] then
        local categories = {}
        for k, _ in pairs(valid_recipe_categories) do
            table.insert(categories, k)
        end
        return {
            error = "Invalid recipe category",
            valid_categories = categories,
        }
    end
    local recipes = self.character.force.recipes
    local valid_recipes = {}
    for recipe_name, recipe in pairs(recipes) do
        if recipe.category == "parameters" or (category and category ~= recipe.category) then
            goto skip
        end
        local details = {
            name = recipe_name,
            category = recipe.category,
            energy = recipe.energy,
            ingredients = recipe.ingredients,
        }
        if recipe.enabled then
            table.insert(valid_recipes, details)
        end
        ::skip::
    end
    return valid_recipes
end

--- Calculate estimated crafting time in ticks
--- @param entity LuaEntity Character entity
--- @param recipe_proto table Recipe prototype (from prototypes.recipe)
--- @param count number Number of items to craft
--- @return number|nil Estimated ticks (nil if cannot calculate)
local function calculate_crafting_time_ticks(entity, recipe_proto, count)
    if not entity or not entity.valid or not recipe_proto then
        return nil
    end
    
    -- Recipe energy is base crafting time in seconds at speed 1.0
    local recipe_energy = recipe_proto.energy
    if not recipe_energy then
        return nil
    end
    
    -- Get character prototype
    local character_proto = entity.prototype
    if not character_proto then
        return nil
    end
    
    -- Get base crafting speed (typically 1.0 for characters)
    local base_crafting_speed = character_proto.get_crafting_speed() or 1.0
    
    -- Get modifiers
    local force = entity.force
    local force_modifier = force and force.manual_crafting_speed_modifier or 0
    local character_modifier = entity.character_crafting_speed_modifier or 0
    
    -- Calculate effective crafting speed
    local effective_crafting_speed = base_crafting_speed * (1 + force_modifier + character_modifier)
    
    -- Time in ticks: (recipe_energy / effective_speed) * count * 60
    local ticks_for_batch = (recipe_energy / effective_crafting_speed) * count * 60
    
    return math.ceil(ticks_for_batch)
end

--- Enqueue crafting recipe (async)
--- @param recipe_name string Recipe name
--- @param count number|nil Count to craft (default: 1)
--- @return table Result with {success, queued, action_id, tick, recipe, count_queued}
function CraftingActions.craft_enqueue(self, recipe_name, count)
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    -- Block crafting if mining stochastic entity (huge-rock)
    -- This ensures inventory diff is accurate for tracking mined products
    if self:is_mining_blocking_crafting() then
        error("Agent: Cannot craft while mining huge-rock (stochastic products)")
    end
    
    if not recipe_name or type(recipe_name) ~= "string" then
        error("Agent: recipe_name (string) is required")
    end
    
    count = math.max(1, math.floor(count or 1))
    
    -- Validate recipe is available to agent's force
    local force = self.character.force
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
    local craftable_count = self.character.get_craftable_count(recipe_proto)
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
        start_products[item_name] = self.character.get_item_count(item_name)
    end
    
    -- Start crafting
    local count_to_queue = math.min(count, craftable_count)
    local count_started = self.character.begin_crafting{
        recipe = recipe_proto,
        count = count_to_queue,
        silent = true
    }
    
    if count_started == 0 then
        error("Agent: Failed to start crafting")
    end
    
    -- Calculate estimated crafting time
    local estimated_ticks = calculate_crafting_time_ticks(
        self.character,
        recipe_proto,
        count_started
    )
    
    -- Store tracking
    self.crafting.in_progress = {
        action_id = action_id,
        recipe = recipe_name,
        count_requested = count,
        count_queued = count_started,
        start_queue_size = self.character.crafting_queue_size,
        start_products = start_products,
        products = products,
        cancelled = false,
        start_tick = rcon_tick,  -- Store start tick for actual time calculation
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
        estimated_ticks = estimated_ticks,
    }, "crafting")
    
    return {
        success = true,
        queued = true,
        action_id = action_id,
        tick = rcon_tick,
        recipe = recipe_name,
        count_queued = count_started,
        estimated_ticks = estimated_ticks,
    }
end

--- Dequeue crafting recipe
--- @param recipe_name string Recipe name
--- @param count number|nil Count to dequeue (nil to dequeue all)
--- @return table Result
function CraftingActions.craft_dequeue(self, recipe_name, count)
    if not (self.character and self.character.valid) then
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
    local queue_size = self.character.crafting_queue_size or 0
    if queue_size == 0 then
        error("Agent: Crafting queue is empty")
    end
    
    -- Find the recipe in the queue
    local queue = self.character.crafting_queue
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
    self.character.cancel_crafting{index = target_index, count = count_to_cancel}
    
    -- Mark as cancelled in tracking
    tracking.cancelled = true
    tracking.cancel_tick = game.tick
    tracking.count_cancelled = count_to_cancel
    
    -- Check remaining queue size
    local remaining_queue_size = self.character.crafting_queue_size or 0
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

CraftingActions.process_crafting = function(self)

    local current_tick = game.tick or 0
    -- Process crafting
    if self.crafting.in_progress then
        local tracking = self.crafting.in_progress

        -- Check if crafting queue is empty (crafting completed)
        local queue_size = self.character.crafting_queue_size or 0

        if queue_size == 0 and tracking.start_queue_size > 0 then
            -- Crafting completed
            local products = tracking.products or {}
            local actual_products = {}

            -- Calculate actual products crafted
            for item_name, amount_per_craft in pairs(products) do
                local current_count = self.character.get_item_count(item_name)
                local start_count = tracking.start_products[item_name] or 0
                local delta = current_count - start_count
                if delta > 0 then
                    actual_products[item_name] = delta
                end
            end

            -- Estimate count_crafted from product deltas
            local count_crafted = 0
            for item_name, amount_per_craft in pairs(products) do
                local delta = actual_products[item_name] or 0
                if amount_per_craft > 0 then
                    local estimated = math.floor(delta / amount_per_craft)
                    if estimated > count_crafted then
                        count_crafted = estimated
                    end
                end
            end

            -- Calculate actual time taken
            local actual_ticks = nil
            if tracking.start_tick then
                actual_ticks = current_tick - tracking.start_tick
            end

            self:enqueue_message({
                action = "craft_enqueue",
                agent_id = self.agent_id,
                success = true,
                action_id = tracking.action_id,
                tick = current_tick,
                recipe = tracking.recipe,
                count_requested = tracking.count_requested,
                count_queued = tracking.count_queued,
                count_crafted = count_crafted,
                products = actual_products,
                actual_ticks = actual_ticks,
            }, "crafting")

            self.crafting.in_progress = nil
        elseif tracking.cancelled then
            -- Crafting was cancelled
            self:enqueue_message({
                action = "craft_dequeue",
                agent_id = self.agent_id,
                success = true,
                cancelled = true,
                action_id = tracking.action_id,
                tick = current_tick,
                recipe = tracking.recipe,
                count_cancelled = tracking.count_cancelled or 0,
            }, "crafting")

            self.crafting.in_progress = nil
        end
    end

end

return CraftingActions

