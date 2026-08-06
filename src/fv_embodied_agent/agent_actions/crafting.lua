--- Agent crafting action methods
--- Methods operate directly on Agent instances (self)
--- State is stored in self.crafting (in_progress)
--- These methods are mixed into the Agent class at module level

local custom_events = require("utils.custom_events")

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

--- Restore vanilla trigger parity for the one trigger item an embodied agent
--- can hand-craft in base-game freeplay.  A script-owned character's
--- begin_crafting() output is not attributed to the force's native item
--- production statistics, so Factorio does not satisfy the otherwise-normal
--- craft-item trigger for automation-science-pack.
--- @param agent Agent
--- @param actual_products table<string, number>
local function unlock_automation_science_for_agent_lab(agent, actual_products)
    if (actual_products["lab"] or 0) < 1 then
        return
    end

    local force = agent.character and agent.character.valid and agent.character.force
    local technology = force and force.technologies["automation-science-pack"]
    if not technology or technology.researched then
        return
    end

    -- Do not let the compatibility shim bypass the prototype's prerequisites.
    for _, prerequisite in pairs(technology.prerequisites or {}) do
        if not prerequisite.researched then
            return
        end
    end

    technology.researched = true
end

--- Enqueue crafting recipe (async)
--- @param recipe_name string Recipe name
--- @param count number|nil Count to craft (default: 1)
--- @return table Result with {success, queued, action_id, tick, recipe, count_queued}
function CraftingActions.craft_enqueue(self, recipe_name, count)
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end

    -- Agent-reachable failures return {success=false, error=<cause>} so the
    -- agent sees a clean actionable message, never a traceback (ERR-1
    -- treatment; same contract as placement.lua, certified L4.2). Only the
    -- error STRING reaches the Python agent, so guidance lives in the text.

    -- Block crafting if mining stochastic entity (huge-rock)
    -- This ensures inventory diff is accurate for tracking mined products
    if self:is_mining_blocking_crafting() then
        return {
            success = false,
            error = "Cannot craft while mining huge-rock (stochastic products) — wait for the mining action to complete, then retry.",
        }
    end

    if not recipe_name or type(recipe_name) ~= "string" then
        return {
            success = false,
            error = "recipe_name (string) is required — e.g. craft('iron-gear-wheel', 2)",
        }
    end

    -- (d) invalid count: report instead of silently coercing
    if count ~= nil and (type(count) ~= "number" or count ~= count or count < 1) then
        return {
            success = false,
            error = string.format(
                "Invalid count %s for recipe '%s': must be a positive integer (omit it to craft once)",
                tostring(count), recipe_name),
            recipe = recipe_name,
        }
    end
    count = math.floor(count or 1)

    local force = self.character.force
    if not force then
        error("Agent: Agent force is invalid")
    end

    -- (a) recipe does not exist at all
    local recipe_proto = prototypes and prototypes.recipe and prototypes.recipe[recipe_name]
    if not recipe_proto then
        return {
            success = false,
            error = string.format(
                "Unknown recipe '%s': no such recipe exists. Check spelling (recipe names usually match the product item, e.g. 'iron-gear-wheel'); use get_recipes() to list recipes available to you.",
                recipe_name),
            recipe = recipe_name,
        }
    end

    -- (b) recipe exists but is not unlocked for the agent's force.
    -- Distinguishing this from missing ingredients matters: retrying a locked
    -- recipe is wasted turns (field failure mode #7, 2026-06-10 retro).
    local recipe = force.recipes[recipe_name]
    if not recipe or not recipe.enabled then
        -- Name the unlocking technology when cheaply findable. This scan only
        -- runs on this failure path (never on the happy path), so the one-off
        -- iteration over force.technologies is acceptable.
        local unlocking_techs = {}
        for tech_name, tech in pairs(force.technologies) do
            local effects = tech.prototype and tech.prototype.effects
            if effects then
                for _, effect in pairs(effects) do
                    if effect.type == "unlock-recipe" and effect.recipe == recipe_name then
                        table.insert(unlocking_techs, tech_name)
                        break
                    end
                end
            end
        end
        local how
        if #unlocking_techs > 0 then
            how = string.format(
                "unlocked by technology '%s' — research it first",
                table.concat(unlocking_techs, "' or '"))
        else
            how = "locked — research required (no unlocking technology found by scan; it may unlock via a trigger, e.g. crafting/mining a prerequisite item)"
        end
        return {
            success = false,
            error = string.format(
                "Recipe '%s' exists but is NOT unlocked for your force: %s. This is not an ingredient problem — crafting it now is impossible regardless of inventory.",
                recipe_name, how),
            recipe = recipe_name,
            locked = true,
            unlocked_by = unlocking_techs,
        }
    end

    -- Recipe category must be hand-craftable by the character
    local char_categories = self.character.prototype and self.character.prototype.crafting_categories
    if char_categories and recipe_proto.category and not char_categories[recipe_proto.category] then
        return {
            success = false,
            error = string.format(
                "Recipe '%s' (category '%s') cannot be hand-crafted — it needs a machine. Use set_entity_recipe() on an appropriate machine instead.",
                recipe_name, recipe_proto.category),
            recipe = recipe_name,
        }
    end

    -- (c) missing ingredients — enumerate name + have + need
    local craftable_count = self.character.get_craftable_count(recipe_proto)
    if craftable_count <= 0 then
        local missing = {}
        local fluid_blocked = false
        for _, ing in pairs(recipe_proto.ingredients or {}) do
            if ing.type == "fluid" then
                fluid_blocked = true
            else
                local have = self.character.get_item_count(ing.name)
                if have < (ing.amount or 0) then
                    table.insert(missing, string.format(
                        "%s (have %d, need %d)", ing.name, have, ing.amount or 0))
                end
            end
        end
        local detail
        if fluid_blocked then
            detail = "it requires fluid ingredients, which cannot be supplied by hand — use a machine"
        elseif #missing > 0 then
            detail = "missing ingredients (per craft): " .. table.concat(missing, ", ")
        else
            detail = "ingredients appear present but the engine reports 0 craftable — an intermediate sub-recipe may be locked or items reserved"
        end
        return {
            success = false,
            error = string.format(
                "Cannot craft '%s': %s. Acquire or craft what is missing, then retry.",
                recipe_name, detail),
            recipe = recipe_name,
            craftable_count = 0,
        }
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
        -- (d) queue rejected the craft despite craftable ingredients
        return {
            success = false,
            error = string.format(
                "Failed to queue crafting for '%s': the engine accepted 0 of %d (crafting queue may be full — current queue size %d). Wait for the queue to drain or cancel entries with craft_dequeue(), then retry.",
                recipe_name, count_to_queue, self.character.crafting_queue_size or 0),
            recipe = recipe_name,
        }
    end

    -- Honesty on partial queue: fewer queued than requested (ingredient-limited)
    local partial_message = nil
    if count_started < count then
        partial_message = string.format(
            "Queued %d of %d requested crafts of '%s' — limited by available ingredients (craftable now: %d). Craft/acquire more ingredients for the rest.",
            count_started, count, recipe_name, craftable_count)
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
        status = "queued",
        queued = true,
        action_id = action_id,
        tick = rcon_tick,
        recipe = recipe_name,
        count_requested = count,
        count_queued = count_started,
        estimated_ticks = estimated_ticks,
        message = partial_message,
    }, "crafting")

    return {
        success = true,
        queued = true,
        action_id = action_id,
        tick = rcon_tick,
        recipe = recipe_name,
        count_requested = count,
        count_queued = count_started,
        estimated_ticks = estimated_ticks,
        message = partial_message,
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
    
    -- Check remaining queue size
    local remaining_queue_size = self.character.crafting_queue_size or 0
    local fully_cancelled = (remaining_queue_size < tracking.start_queue_size)
    
    -- Enqueue cancel message
    self:enqueue_message({
        action = "craft_dequeue",
        agent_id = self.agent_id,
        success = true,
        status = "cancelled",
        cancelled = fully_cancelled,
        action_id = tracking.action_id,
        recipe = recipe_name,
        count_cancelled = count_to_cancel,
        remaining_queue_size = remaining_queue_size,
        tick = game.tick or 0,
    }, "crafting")
    
    -- Always clear tracking after dequeue - we've sent the message
    self.crafting.in_progress = nil
    
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
    
    if not self.crafting.in_progress then
        return
    end
    
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

        unlock_automation_science_for_agent_lab(self, actual_products)

        -- Raise crafting completed event for fv_snapshot to log
        script.raise_event(custom_events.on_agent_crafting_completed, {
            agent_id = self.agent_id,
            tick = current_tick,
            recipe = tracking.recipe,
            count_crafted = count_crafted,
            products = actual_products,
        })

        -- Calculate actual time taken
        local actual_ticks = nil
        if tracking.start_tick then
            actual_ticks = current_tick - tracking.start_tick
        end

        self:enqueue_message({
            action = "craft_enqueue",
            agent_id = self.agent_id,
            success = true,
            status = "completed",
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
    end
    -- Note: Cancellation is handled entirely in craft_dequeue() which clears tracking
end

--- Get current crafting queue with full details
--- @return table Crafting queue with items, size, and progress
function CraftingActions.get_crafting_queue(self)
    if not (self.character and self.character.valid) then
        error("Agent: Agent entity is invalid")
    end
    
    local queue = self.character.crafting_queue or {}
    local queue_items = {}
    
    -- Convert Lua queue to array format
    -- Factorio's crafting_queue is an array of CraftingQueueItem objects
    -- The queue is indexed by position (1-based), and each item has:
    --   - index: position in queue
    --   - recipe: LuaRecipe object (has .name property) OR recipe name string
    --   - count: number of items to craft
    --   - prerequisite: boolean
    for i = 1, #queue do
        local item = queue[i]
        if item then
            local recipe_name = ""
            if item.recipe then
                -- Recipe might be a LuaRecipe object (with .name) or a string
                if type(item.recipe) == "string" then
                    recipe_name = item.recipe
                elseif item.recipe.name then
                    recipe_name = item.recipe.name
                end
            end
            
            table.insert(queue_items, {
                index = item.index or i,
                recipe = recipe_name,
                count = item.count or 0,
                prerequisite = item.prerequisite or false,
            })
        end
    end
    
    -- Sort by index to ensure correct order
    table.sort(queue_items, function(a, b) return a.index < b.index end)
    
    return {
        queue = queue_items,
        queue_size = self.character.crafting_queue_size or 0,
        progress = self.character.crafting_queue_progress or 0.0,
    }
end

return CraftingActions
