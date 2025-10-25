--- @class TestHelpers
--- Minimal test utilities - wrappers around Factorio API for convenience
local TestHelpers = {}

--- Create a wooden chest with optional items at position
function TestHelpers.create_test_chest(surface, position, items)
    local chest = surface.create_entity({
        name = "wooden-chest",
        position = position,
        force = game.forces.player
    })
    
    if items then
        local inventory = chest.get_inventory(defines.inventory.chest)
        for item_name, count in pairs(items) do
            inventory.insert({name = item_name, count = count})
        end
    end
    
    return chest
end

--- Create an assembling machine at position
function TestHelpers.create_test_assembler(surface, position, recipe)
    local assembler = surface.create_entity({
        name = "assembling-machine-1",
        position = position,
        force = game.forces.player
    })
    
    if recipe then
        assembler.set_recipe(recipe)
    end
    
    return assembler
end

--- Get agent's main inventory
function TestHelpers.get_agent_inventory(agent)
    return agent.get_inventory(defines.inventory.character_main)
end

--- Clear agent's main inventory
function TestHelpers.clear_agent_inventory(agent)
    TestHelpers.get_agent_inventory(agent).clear()
end

--- Give items to agent
function TestHelpers.give_agent_items(agent, items)
    local inventory = TestHelpers.get_agent_inventory(agent)
    for item_name, count in pairs(items) do
        inventory.insert({name = item_name, count = count})
    end
end

return TestHelpers
