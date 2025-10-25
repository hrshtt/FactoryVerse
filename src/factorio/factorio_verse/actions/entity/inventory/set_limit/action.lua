--[[
    Factorio Inventory Set Limit Action

    In Factorio, some types of entity inventories (such as containers, assembling machines, furnaces, etc.) can have a "limit" set on them. 
    A limit restricts the maximum number of slots available for use within an inventory, which is often used for automation and logistics control 
    (for example, limiting the number of items a chest will request from inserters).

    However, not all inventory types or entities support having their inventory limits set (e.g., basic chests do, but not all machines or special inventories).

    This action allows an agent to set the inventory "limit" for entities and inventories where this is supported. 
    The agent must specify:
      - The `unit_number` (identifying the entity)
      - The `inventory_type` (e.g., "main", "chest", "fuel", etc. as appropriate for the entity)
      - The `limit` (maximum number of slots to allow; must be an integer within valid range for that inventory/entity)

    Attempting to set a limit on an unsupported inventory or entity will result in a no-op or error from the validator, according to implementation.

    This action supports advanced automation scenarios, such as controlling how full assemblers or containers can get, improving resource flow management by intelligent agents.
]]
