local Action = require("core.action.Action")
local ParamSpec = require("core.action.ParamSpec")
local GameState = require("core.game_state.GameState")

local gs = GameState:new()

--- @class CraftParams : ParamSpec
--- @field agent_id number
--- @field recipe string            -- recipe prototype name
--- @field count number|nil         -- desired crafts; defaults to 1
local CraftParams = ParamSpec:new({
    agent_id = { type = "number", required = true },
    recipe = { type = "string", required = true },
    count = { type = "number", required = false }
})

--- @class CraftAction : Action
local CraftAction = Action:new("item.craft", CraftParams)

local function is_hand_craftable(recipe_proto)
    if not recipe_proto then return false end
    local cat = recipe_proto.category or "crafting"
    return cat == "crafting" or cat == "advanced-crafting"
end

local function get_item_ingredients(recipe_proto)
    local items = {}
    for _, ing in ipairs(recipe_proto.ingredients or {}) do
        if ing.type == nil or ing.type == "item" then
            local name = ing.name or ing[1]
            local amount = ing.amount or ing[2] or 0
            if name and amount and amount > 0 then
                items[name] = (items[name] or 0) + amount
            end
        elseif ing.type == "fluid" then
            -- character cannot hand-craft fluid recipes
            return nil, "fluid_ingredient"
        end
    end
    return items, nil
end

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

--- @param params CraftParams
--- @return table
function CraftAction:run(params)
    params = self:_pre_run(gs, params)
    ---@cast params CraftParams

    ---@type LuaEntity
    local agent = gs:agent_state():get_agent(params.agent_id)
    local inv = agent.get_inventory(defines.inventory.character_main)
    local recipe_proto = (prototypes and prototypes.recipe and prototypes.recipe[params.recipe])

    local ingredients, reason = get_item_ingredients(recipe_proto)
    if not ingredients then
        error("Recipe requires unsupported ingredients (" .. tostring(reason) .. ")")
    end

    local desired = math.max(1, math.floor(params.count or 1))

    -- Compute feasible crafts based on inventory
    local feasible = desired
    for name, need in pairs(ingredients) do
        local have = (inv and inv.get_item_count and inv.get_item_count(name)) or 0
        local can = math.floor(have / need)
        if can < feasible then feasible = can end
    end
    if feasible <= 0 then
        error("Insufficient ingredients for recipe: " .. params.recipe)
    end

    -- Remove ingredients
    for name, need in pairs(ingredients) do
        local to_remove = need * feasible
        local removed = (inv and inv.remove and inv.remove({ name = name, count = to_remove })) or 0
        if removed < to_remove then
            error("Failed to remove ingredients from inventory")
        end
    end

    -- Insert products; spill overflow
    local surface = agent.surface
    local pos = agent.position
    local products = get_item_products(recipe_proto)
    local produced = {}
    for name, amount in pairs(products) do
        local total = amount * feasible
        local inserted = (inv and inv.insert and inv.insert({ name = name, count = total })) or 0
        produced[name] = inserted
        local leftover = total - inserted
        if leftover > 0 and surface and pos then
            surface.spill_item_stack{
                position = pos,
                stack = { name = name, count = leftover },
                enable_looted = true,
                force = agent.force,
                allow_belts_and_inserters = false
            }
        end
    end

    -- Create mutation contract result
    local inventory_changes = {}
    
    -- Add consumed ingredients (negative values)
    for name, amount in pairs(ingredients) do
        inventory_changes[name] = -(amount * feasible)
    end
    
    -- Add produced items (positive values)
    for name, amount in pairs(produced) do
        inventory_changes[name] = (inventory_changes[name] or 0) + amount
    end
    
    local result = {
        crafted = feasible,
        recipe = params.recipe,
        products = produced,
        affected_inventories = {
            {
                owner_type = "agent",
                owner_id = params.agent_id,
                inventory_type = "character_main",
                changes = inventory_changes
            }
        }
    }
    
    return self:_post_run(result, params)
end

return CraftAction


