--[[
    actions.entity.set_recipe.action

    -- This file defines the action that allows an agent to set or overwrite the recipe on a given entity (such as an assembling machine or furnace).
    -- The validator ensures:
    --   - The supplied entity is capable of having a recipe set.
    --   - The provided recipe is compatible with the entity type.
    --   - If the entity already has a recipe and the overwrite flag is not set, it errors with a message indicating the entity's existing recipe must be overwritten intentionally.
    --   - If the entity does not have a recipe and overwrite is requested, it may also error to discourage unnecessary overwriting.
    -- Mechanism:
    --   - Upon valid parameters and conditions, the recipe is set on the entity.
    --   - If overwriting, the old recipe is swapped out for the new one.
    --   - A post-action hook ensures any chunk/entity data structures tracking recipes for entities are updated or replaced with the new recipe data.
    --   - The action’s response gives back to the agent the new (current) recipe for this entity, confirming the result of the operation.
]]
