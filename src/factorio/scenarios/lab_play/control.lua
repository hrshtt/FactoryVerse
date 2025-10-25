
--[[
Lab Play Scenario - Agent Crafting Testbed

This scenario acts as a testbed specifically designed for agents (such as LLMs or bots)
to experiment with creating custom recipes, automating crafting, and demonstrating their
interactions with the Factorio environment.

Key Goals:
- Provide a safe, isolated environment for agents to programmatically create and use their own recipes.
- Supply helper methods and remote interfaces to allow external systems (such as test harnesses or trainers)
  to query agent progress, crafting statistics, and other relevant metrics.

Tracking Integrity:
- Unlike 'supply', tests in 'lab_play' will not be time-bounded, as bounding LLMs by ticks is unreliable.
  Instead, all progress is tracked based on crafted items, completion of objectives, or other non-time metrics.
- The scenario will implement robust mechanisms to detect and prevent agents from circumventing
  intended challenges (e.g., by hand-crafting items rather than using proper automations).
  This includes:
    - Tracking all item crafting events, with clear distinction between hand-crafting,
      assembler-crafting, and any illegal item insertions/spawns.
    - Providing logging and/or error reporting if agents attempt to "hack" their inventory.

Remote Interfaces:
- The scenario will expose remote calls to:
    * Get the status and progress of crafting objectives
    * Retrieve logs/statistics of all crafting events (what was crafted, how, when, by whom)
    * Reset or initialize the crafting testbed for new experiments
- More advanced remote calls may provide granular metadata useful for agent evaluation (e.g., breakdown by recipe, crafting source, etc).

Implementation Guidance:
- Use the 'supply' scenario @control.lua as a reference for scripting structure, 
  GUI helpers, and event-driven progress tracking.
- Instead of levels and time pressure, focus on recipe fulfillment, agent creativity, and careful auditing of all crafting actions.
- Place special emphasis on monitoring remote call usage, including audit trails and anti-cheat checks for agent actions.

NOTES FOR IMPLEMENTERS:
- No game logic is implemented here: this block is strictly scenario documentation.
- Actual scenario logic must faithfully follow the constraints and anti-cheating requirements outlined above.

]]


