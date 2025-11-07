local Action = require("types.Action")
local agent_helpers = require("game_state.agent.helpers")

--- @class CraftEnqueueParams : ParamSpec
--- @field agent_id number
--- @field recipe string            -- recipe prototype name
--- @field count number|nil         -- desired crafts; defaults to 1
local CraftEnqueueParams = Action.ParamSpec:new({
    agent_id = { type = "number", required = true },
    recipe = { type = "string", required = true },
    count = { type = "number", required = false }
})

--- @class CraftEnqueueAction : Action
local CraftEnqueueAction = Action:new("agent.crafting.craft_enqueue", CraftEnqueueParams)

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

--- @param params CraftEnqueueParams
--- @return table
function CraftEnqueueAction:run(params)
    local p = self:_pre_run(params)
    ---@cast p CraftEnqueueParams
    
    local agent_id = p.agent_id
    local recipe_name = p.recipe
    local count_requested = math.max(1, math.floor(p.count or 1))
    
    -- Get agent entity
    local agent = self.game_state.agent:get_agent(agent_id)
    if not agent or not agent.valid then
        return self:_post_run({ success = false, error = "Agent not found or invalid" }, p)
    end
    
    -- Get recipe prototype
    local recipe_proto = (prototypes and prototypes.recipe and prototypes.recipe[recipe_name])
    if not recipe_proto then
        return self:_post_run({ success = false, error = "Unknown recipe: " .. recipe_name }, p)
    end
    
    -- Check craftable count (validates ingredients and recipe availability)
    local craftable_count = agent.get_craftable_count(recipe_proto)
    if craftable_count <= 0 then
        return self:_post_run({ 
            success = false, 
            error = "Cannot craft recipe: insufficient ingredients or recipe not available" 
        }, p)
    end
    
    -- Check crafting queue capacity (characters typically have max queue size of 3)
    -- local max_queue_size = 3
    -- if agent.crafting_queue_size >= max_queue_size then
    --     return self:_post_run({ 
    --         success = false, 
    --         error = "Crafting queue is full (size: " .. agent.crafting_queue_size .. ")" 
    --     }, p)
    -- end
    
    -- Determine count to queue (limited by craftable count)
    local count_to_queue = math.min(count_requested, craftable_count)
    
    -- Queue the recipe
    local count_started = agent.begin_crafting{
        recipe = recipe_proto,
        count = count_to_queue,
        silent = true  -- Don't print failure messages
    }
    
    if count_started == 0 then
        return self:_post_run({ 
            success = false, 
            error = "Failed to start crafting (begin_crafting returned 0)" 
        }, p)
    end
    
    -- Generate unique action_id from tick + agent_id
    local rcon_tick = game.tick
    local action_id = string.format("craft_enqueue_%d_%d", rcon_tick, agent_id)
    
    -- Get product items for tracking
    local products = get_item_products(recipe_proto)
    local start_products = snapshot_product_items(agent, products)
    
    -- Store tracking info for completion monitoring
    storage.craft_in_progress = storage.craft_in_progress or {}
    storage.craft_in_progress[agent_id] = {
        action_id = action_id,
        rcon_tick = rcon_tick,
        recipe = recipe_name,
        count_requested = count_requested,
        count_queued = count_started,
        start_queue_size = agent.crafting_queue_size,
        start_products = start_products,
        products = products  -- recipe product definitions for completion calculation
    }
    
    log(string.format("[craft_enqueue] Queued crafting for agent %d at tick %d: recipe=%s, count=%d/%d, action_id=%s", 
        agent_id, rcon_tick, recipe_name, count_started, count_requested, action_id))
    
    -- Return async contract: queued + action_id for UDP tracking
    local result = {
        success = true,
        queued = true,
        action_id = action_id,
        tick = rcon_tick,
        recipe = recipe_name,
        count_requested = count_requested,
        count_queued = count_started
    }
    
    return self:_post_run(result, p)
end

return { action = CraftEnqueueAction, params = CraftEnqueueParams }
