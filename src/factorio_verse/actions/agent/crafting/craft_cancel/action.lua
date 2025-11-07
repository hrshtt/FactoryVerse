--[[
    actions.agent.crafting.craft_cancel.action

    -- This action enables an agent to cancel a previously queued crafting job submitted via `craft_enqueue`.
    -- 1. Validator is checked on invocation; it will raise an error if this action cannot be called for the given params.
    -- 2. The global `storage` table is checked for an entry of crafting jobs for the given agent. If jobs exist for the specified job id (or currently in progress), it attempts to cancel those jobs.
    -- 3. On successful cancellation, any remaining or pending ingredients that were being consumed as part of crafting are returned to the agent's inventory.
    -- 4. The response for this action includes a detailed list of ingredients recovered and returned to the agent as the result of cancellation.
]]

