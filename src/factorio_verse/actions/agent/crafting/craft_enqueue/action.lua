--[[
    actions.agent.crafting.craft_enqueue.action

    This file defines the enqueue version of the item crafting action, as an alternative entry point to `craft_sync`.
    The primary functionality of this action is to enqueue a crafting job for the agent, which is then processed asynchronously by the Factorio game engine:
      - The requested crafting job is added to the agent's crafting queue, handled in the background without blocking script execution.
      - The action immediately returns a response confirming that the crafting job has been enqueued, or raises an error (via the validator) if the job cannot be added.
      - The job's status and any relevant metadata are tracked using the global `storage` table, allowing controllers or agents to monitor the progress of the job, poll for completion, or correlate it with later results asynchronously.
    This interface is useful when agents/controllers should queue up crafting jobs and not wait/block for their immediate completion.
    It is the user's responsibility to monitor job completion or state by querying the agent's craft/job status elsewhere, typically via polling the global `storage`.
    This action is equivalent to `craft_sync` but does not block and returns immediately, enabling concurrent or pipelined crafting management.
]]
