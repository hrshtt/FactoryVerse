--[[
    actions.entity.pickup.action

    -- This file defines the action for picking up (removing) an entity from the map and transferring both the entity and any contained items into the agent's inventory.
    -- Mechanism:
    --   - The validator ensures the agent's inventory has enough space for both the picked-up entity and any items currently held by that entity; insufficient capacity results in an error to inform the agent.
    --   - Allows an agent to pick up an entity from the world and store it in their inventory.
    --   - All items stored within the picked-up entity (e.g., chest contents, module slots) are also added to the agent's inventory.
    --   - The action's response provides details about the removed entity and a comprehensive list of all items obtained, allowing downstream agents or controllers to track and utilize these resources.
]]
