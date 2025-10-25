--[[
    Factorio Inventory Set Item Action - Overview

    This action enables agent-driven automation to set or insert specific item stacks into any supported inventory of a Factorio entity. It is robustly designed to address the complexity and variability of Factorio inventories, including:

    **Supported Inventory Types:**
      - **Main inventory:** Standard item storage (e.g., for chests, assemblers, furnaces).
      - **Module slots:** Only accept module items; number of slots is limited by the entity's prototype.
      - **Fuel inventory:** Only valid fuels; used by furnaces, vehicles, some machines.
      - **Input/Output inventories:** Control the flow of items for machines, belts, inserters, etc.

    **Behavioral Rules:**
      - Each inventory type enforces its own constraints: allowed items, slot count, stack size limits ([lua-api.factorio.com/classes/LuaInventory](https://lua-api.factorio.com/latest/classes/LuaInventory.html)).
      - When inserting, properties such as health (for damaged items), durability (for tools), and ammo count (for weapons/magazines) must be considered to match stack types. E.g., damaged items have `.health < 1`, some items (e.g. modded) may require explicit attention to these attributes.
      - All insertions should use LuaInventory methods: `can_insert`, `insert`, `remove`, and `get_item_count`.

    **Implementation Details:**
      * Input parameters:
          - `unit_number`: (required) Unique identifier of the target entity.
          - `item`: (required) Name of the item to insert.
          - `count`: (optional) Number of items to insert (defaults to the maximum stack size for that item).
          - `inventory_type`: (optional) Inventory type string (e.g., "main", "module", "fuel"); use for entities with multiple inventory options to disambiguate.
      * The action attempts to resolve the inventory type automatically if not specified, choosing the correct type based on context or failing with an explicit error/warning if ambiguous.
      * For module and fuel inventories, strict item checks are enforced; attempts to insert an incorrect item (e.g., non-module into modules, non-fuel into fuel) must fail gracefully.
      * The action will check for full inventories, invalid entities, or type mismatches, and will only insert items if all conditions are met. Partial insertions (if not all items fit) will be reported accordingly.
      * Works for specialized cases, such as filling buffer inventories, loading fuel for automation start-up, or swapping modules for upgrades.
      * Handles insertion of item stacks preserving important attributes (health, durability, ammo) for correct gameplay semantics.

    **Edge Case Handling:**
      - If an entity does not exist or does not have the specified inventory, the action returns a clear error.
      - If agent does not have the item in inventory, the action returns a clear error.
      - If ambiguity exists (e.g., an assembler has both main and module inventories) and `inventory_type` is omitted, an explicit warning or error MUST be returned.
      - If the requested item is inappropriate for the inventory (e.g., inserting standard items into module/fluid/fuel slots or vice versa), the action fails with a descriptive error.
      - Insertion respects actual inventory space limits and stack sizes, supporting partial insertions when possible and informing the caller of the operation outcome.
      - Where appropriate, supports advanced inventory options, e.g., for entities with unique or modded inventories.

    **Usage Examples:**
      - Load fuel into a burner assembler or locomotive
      - Insert productivity modules into assembler module slots
      - Fill a chest or buffer with specific items for logistic agents
      - Top up machine input inventories during automation scenarios

    **References:**
      - [Factorio LuaInventory API](https://lua-api.factorio.com/latest/classes/LuaInventory.html)
      - Item/stack properties: `.health`, `.durability`, `.ammo`—see [LuaItemStack](https://lua-api.factorio.com/latest/classes/LuaItemStack.html)

    This action underpins high-level agent workflows for loading, preparation, upgrading, and automation in the Factorio world, with accuracy and safety for edge cases and ambiguity resolution.
]]
