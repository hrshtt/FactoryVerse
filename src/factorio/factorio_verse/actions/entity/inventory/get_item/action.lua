--[[
    actions.entity.inventory.get_item.action

    This file defines the "get_entity_inventory_item" action, enabling an agent to retrieve items from any entity's inventory within the Factorio world.

    Key features:
    - Allows an agent to request the transfer of one or more specified items (and amounts) from a target entity's inventory into the agent's own inventory.
    - Validators for this action perform several critical checks:
        * Ensure the target entity exists and possesses an inventory of the expected type. This is performed using the `get_inventory` method on the target `LuaEntity`. ([See: lua-api.factorio.com/latest/classes/LuaEntity.html#get_inventory](https://lua-api.factorio.com/latest/classes/LuaEntity.html#get_inventory))
        * Check for the presence and total count of the item(s) to be transferred using the `get_item_count` method of the `LuaInventory`. ([See: lua-api.factorio.com/latest/classes/LuaInventory.html#get_item_count](https://lua-api.factorio.com/latest/classes/LuaInventory.html#get_item_count))
        * Confirm that the agent's inventory can accommodate the incoming items by leveraging the `can_insert` method and respecting stack sizes and slot constraints. ([See: lua-api.factorio.com/latest/classes/LuaInventory.html#can_insert](https://lua-api.factorio.com/latest/classes/LuaInventory.html#can_insert))
    - Transfers up to the minimum of the requested amount, the available items in the entity's inventory, and the available space in the agent's inventory.
        * The actual item transfer utilizes the `insert` (and for removal, `remove`) methods of `LuaInventory`.
        * Handles partial transfers: if either source inventory lacks the requested items, or destination inventory is nearly full, as many items as possible are moved and the remainder is reported in the response.
    - The result of the operation (including the actual number of items transferred for each item, and a clear indication of cases where less than requested was moved) is returned in the action's response.
    - Supports batch operations: the agent may provide a table or map of item name → amount, and all will be processed sequentially.
    - If the JSON input omits an amount for any item, the system defaults that request to the maximum count available and transferable.
    - Supports "ALL_ITEMS": if the string "ALL_ITEMS" is provided as an item name, the action attempts to transfer all items present in the entity's inventory, subject to agent inventory constraints.
    - Error or status reporting (optionally via `rcon.print`) is provided for situations where transfers are partial, impossible, or ambiguous.

    This action is essential for agent-directed automation of picking up, looting, clearing, or otherwise extracting items from assemblers, chests, belts, machines, and similar entities in the Factorio simulation world.
]]
