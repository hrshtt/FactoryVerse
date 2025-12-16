--- Agent Remote Interface
--- Registers per-agent remote interfaces for RCON control
--- Interface name: "agent_{agent_id}"
---
--- Methods are organized by category:
---   - Async actions (walk_to, mine_resource, craft_enqueue) return immediately with action_id
---     and send completion notifications via UDP
---   - Sync actions (place_entity, set_entity_recipe, etc.) complete immediately
---   - Queries (inspect, get_recipes, etc.) return data without side effects
---
--- Schema Export:
---   Use M.export_interface_schema() to get JSON-serializable schema for Python bindings
---   and LLM documentation generation.

local M = {}

-- ============================================================================
-- INTERFACE METHOD REGISTRY
-- ============================================================================

--- Method definitions with full metadata for Python bindings and LLM docs
--- Fields:
---   - category: Method category for grouping in docs
---   - is_async: If true, returns action_id and sends UDP completion
---   - doc: Human-readable description for LLM agents
---   - paramspec: Parameter validation schema
---   - returns: Return type schema for Python type hints
---   - func: Dispatch function

local INTERFACE_METHODS = {
    -- ========================================================================
    -- ASYNC: Walking
    -- ========================================================================
    walk_to = {
        category = "movement",
        is_async = true,
        doc = [[Walk the agent to a target position using pathfinding.
The agent will navigate around obstacles. Returns immediately with an action_id;
completion is signaled via UDP when the agent arrives or fails to reach the goal.]],
        paramspec = {
            _param_order = { "goal", "strict_goal", "options" },
            goal = { type = "position", required = true, doc = "Target position {x, y}" },
            strict_goal = { type = "boolean", default = false, doc = "If true, fail if exact position unreachable" },
            options = { type = "table", default = {}, doc = "Additional pathfinding options" },
        },
        returns = {
            type = "async_action",
            schema = {
                queued = { type = "boolean", doc = "True if action was queued" },
                action_id = { type = "string", doc = "Unique ID for tracking completion" },
            },
            completion = {
                success = { type = "boolean", doc = "True if agent reached goal" },
                position = { type = "position", doc = "Final position of agent" },
                elapsed_ticks = { type = "number", doc = "Game ticks elapsed" },
            },
        },
        func = function(self, goal, strict_goal, options)
            return self:walk_to(goal, strict_goal, options)
        end,
    },
    stop_walking = {
        category = "movement",
        is_async = false,
        doc = "Immediately stop the agent's current walking action.",
        paramspec = { _param_order = {} },
        returns = {
            type = "result",
            schema = {
                success = { type = "boolean", doc = "True if walking was stopped" },
            },
        },
        func = function(self)
            return self:stop_walking()
        end,
    },

    -- ========================================================================
    -- ASYNC: Mining
    -- ========================================================================
    mine_resource = {
        category = "mining",
        is_async = true,
        doc = [[Mine a resource within reach of the agent.
The agent will mine the nearest resource of the given type. Mining is incremental
if max_count is specified, or depletes the resource if max_count is nil.
Returns immediately; completion signaled via UDP with items gained.]],
        paramspec = {
            _param_order = { "resource_name", "max_count" },
            resource_name = { type = "string", required = true, doc = "Resource prototype name (e.g., 'iron-ore', 'coal', 'stone')" },
            max_count = { type = "number", default = nil, doc = "Max items to mine (nil = deplete resource)" },
        },
        returns = {
            type = "async_action",
            schema = {
                queued = { type = "boolean", doc = "True if mining was started" },
                action_id = { type = "string", doc = "Unique ID for tracking completion" },
                entity_name = { type = "string", doc = "Name of resource being mined" },
                entity_position = { type = "position", doc = "Position of resource" },
            },
            completion = {
                success = { type = "boolean", doc = "True if mining completed" },
                items = { type = "table", doc = "Items gained: {item_name: count, ...}" },
                reason = { type = "string", doc = "Completion reason (completed, interrupted, etc.)" },
            },
        },
        func = function(self, resource_name, max_count)
            return self:mine_resource(resource_name, max_count)
        end,
    },
    stop_mining = {
        category = "mining",
        is_async = false,
        doc = "Immediately stop the agent's current mining action.",
        paramspec = { _param_order = {} },
        returns = {
            type = "result",
            schema = {
                success = { type = "boolean", doc = "True if mining was stopped" },
                items = { type = "table", doc = "Items gained before stopping" },
            },
        },
        func = function(self)
            return self:stop_mining()
        end,
    },

    -- ========================================================================
    -- ASYNC: Crafting
    -- ========================================================================
    craft_enqueue = {
        category = "crafting",
        is_async = true,
        doc = [[Queue a recipe for hand-crafting.
The agent will craft the specified recipe if ingredients are available.
Returns immediately; completion signaled via UDP when crafting finishes.]],
        paramspec = {
            _param_order = { "recipe_name", "count" },
            recipe_name = { type = "recipe", required = true, doc = "Recipe name to craft" },
            count = { type = "number", default = 1, doc = "Number of times to craft the recipe" },
        },
        returns = {
            type = "async_action",
            schema = {
                queued = { type = "boolean", doc = "True if crafting was queued" },
                action_id = { type = "string", doc = "Unique ID for tracking completion" },
                recipe = { type = "string", doc = "Recipe being crafted" },
                count = { type = "number", doc = "Number queued" },
            },
            completion = {
                success = { type = "boolean", doc = "True if crafting completed" },
                items = { type = "table", doc = "Items crafted: {item_name: count, ...}" },
            },
        },
        func = function(self, recipe_name, count)
            return self:craft_enqueue(recipe_name, count)
        end,
    },
    craft_dequeue = {
        category = "crafting",
        is_async = false,
        doc = "Cancel queued crafting for a recipe.",
        paramspec = {
            _param_order = { "recipe_name", "count" },
            recipe_name = { type = "recipe", required = true, doc = "Recipe name to cancel" },
            count = { type = "number", default = nil, doc = "Number to cancel (nil = all)" },
        },
        returns = {
            type = "result",
            schema = {
                success = { type = "boolean", doc = "True if crafting was cancelled" },
                cancelled_count = { type = "number", doc = "Number of crafts cancelled" },
            },
        },
        func = function(self, recipe_name, count)
            return self:craft_dequeue(recipe_name, count)
        end,
    },

    -- ========================================================================
    -- SYNC: Entity Operations
    -- ========================================================================
    set_entity_recipe = {
        category = "entity",
        is_async = false,
        doc = [[Set the recipe for a machine (assembler, furnace, chemical plant).
The entity is identified by name and position. If position is nil, finds the
nearest entity of that type within reach.]],
        paramspec = {
            _param_order = { "entity_name", "position", "recipe_name" },
            entity_name = { type = "entity_name", required = true, doc = "Entity prototype name" },
            position = { type = "position", default = nil, doc = "Entity position (nil = nearest)" },
            recipe_name = { type = "recipe", default = nil, doc = "Recipe to set (nil = clear)" },
        },
        returns = {
            type = "entity_ref",
            schema = {
                success = { type = "boolean", doc = "True if recipe was set" },
                entity_name = { type = "string", doc = "Entity name" },
                position = { type = "position", doc = "Entity position" },
                recipe = { type = "string", doc = "Recipe that was set" },
            },
        },
        func = function(self, entity_name, position, recipe_name)
            return self:set_entity_recipe(entity_name, position, recipe_name)
        end,
    },
    set_entity_filter = {
        category = "entity",
        is_async = false,
        doc = [[Set an inventory filter on an entity (inserter, container with filters).
Filters restrict which items can be placed in specific inventory slots.]],
        paramspec = {
            _param_order = { "entity_name", "position", "inventory_type", "filter_index", "filter_item" },
            entity_name = { type = "entity_name", required = true, doc = "Entity prototype name" },
            position = { type = "position", default = nil, doc = "Entity position (nil = nearest)" },
            inventory_type = { type = "inventory_type", required = true, doc = "Inventory type to filter" },
            filter_index = { type = "number", default = nil, doc = "Slot index (nil = first slot)" },
            filter_item = { type = "string", default = nil, doc = "Item to filter (nil = clear)" },
        },
        returns = {
            type = "result",
            schema = {
                success = { type = "boolean", doc = "True if filter was set" },
            },
        },
        func = function(self, entity_name, position, inventory_type, filter_index, filter_item)
            return self:set_entity_filter(entity_name, position, inventory_type, filter_index, filter_item)
        end,
    },
    set_inventory_limit = {
        category = "entity",
        is_async = false,
        doc = [[Set the inventory bar limit on a container.
This limits how many slots are usable in the container's inventory.]],
        paramspec = {
            _param_order = { "entity_name", "position", "inventory_type", "limit" },
            entity_name = { type = "entity_name", required = true, doc = "Entity prototype name" },
            position = { type = "position", default = nil, doc = "Entity position (nil = nearest)" },
            inventory_type = { type = "inventory_type", required = true, doc = "Inventory type to limit" },
            limit = { type = "number", default = nil, doc = "Slot limit (nil = no limit)" },
        },
        returns = {
            type = "result",
            schema = {
                success = { type = "boolean", doc = "True if limit was set" },
            },
        },
        func = function(self, entity_name, position, inventory_type, limit)
            return self:set_inventory_limit(entity_name, position, inventory_type, limit)
        end,
    },
    take_inventory_item = {
        category = "inventory",
        is_async = false,
        doc = [[Take items from an entity's inventory into the agent's inventory.
Returns an item reference that can be used for further operations.]],
        paramspec = {
            _param_order = { "entity_name", "position", "inventory_type", "item_name", "count" },
            entity_name = { type = "entity_name", required = true, doc = "Entity prototype name" },
            position = { type = "position", default = nil, doc = "Entity position (nil = nearest)" },
            inventory_type = { type = "inventory_type", required = true, doc = "Inventory type to take from" },
            item_name = { type = "string", required = true, doc = "Item name to take" },
            count = { type = "number", default = nil, doc = "Count to take (nil = all available)" },
        },
        returns = {
            type = "item_ref",
            schema = {
                success = { type = "boolean", doc = "True if items were taken" },
                item_name = { type = "string", doc = "Item that was taken" },
                count = { type = "number", doc = "Actual count taken" },
            },
        },
        func = function(self, entity_name, position, inventory_type, item_name, count)
            return self:get_inventory_item(entity_name, position, inventory_type, item_name, count)
        end,
    },
    put_inventory_item = {
        category = "inventory",
        is_async = false,
        doc = [[Put items from the agent's inventory into an entity's inventory.
The agent must have the items in their inventory.]],
        paramspec = {
            _param_order = { "entity_name", "position", "inventory_type", "item_name", "count" },
            entity_name = { type = "entity_name", required = true, doc = "Entity prototype name" },
            position = { type = "position", default = nil, doc = "Entity position (nil = nearest)" },
            inventory_type = { type = "inventory_type", required = true, doc = "Inventory type to put into" },
            item_name = { type = "string", required = true, doc = "Item name to put" },
            count = { type = "number", required = true, doc = "Count to put" },
        },
        returns = {
            type = "result",
            schema = {
                success = { type = "boolean", doc = "True if items were placed" },
                count = { type = "number", doc = "Actual count placed" },
            },
        },
        func = function(self, entity_name, position, inventory_type, item_name, count)
            return self:set_inventory_item(entity_name, position, inventory_type, item_name, count)
        end,
    },

    -- ========================================================================
    -- SYNC: Placement
    -- ========================================================================
    place_entity = {
        category = "placement",
        is_async = false,
        doc = [[Place an entity from the agent's inventory onto the map.
The agent must have the item in their inventory and be within build reach.
Returns an entity reference for further operations on the placed entity.]],
        paramspec = {
            _param_order = { "entity_name", "position", "direction", "ghost" },
            entity_name = { type = "entity_name", required = true, doc = "Entity prototype name to place" },
            position = { type = "position", required = true, doc = "Position to place entity" },
            direction = { type = "number", default = nil, doc = "Direction (4=east, 6=west, 8=south, 10=north)" },
            ghost = { type = "boolean", default = false, doc = "Whether to place a ghost entity" },
        },
        returns = {
            type = "entity_ref",
            schema = {
                success = { type = "boolean", doc = "True if entity was placed" },
                entity_name = { type = "string", doc = "Placed entity name" },
                position = { type = "position", doc = "Actual position placed" },
                entity_type = { type = "string", doc = "Entity type string" },
            },
        },
        func = function(self, entity_name, position, direction, ghost)
            return self:place_entity(entity_name, position, direction, ghost)
        end,
    },
    pickup_entity = {
        category = "placement",
        is_async = false,
        doc = [[Pick up an entity from the map into the agent's inventory.
The entity must be within reach and mineable/deconstructable.]],
        paramspec = {
            _param_order = { "entity_name", "position" },
            entity_name = { type = "entity_name", required = true, doc = "Entity prototype name to pick up" },
            position = { type = "position", default = nil, doc = "Entity position (nil = nearest)" },
        },
        returns = {
            type = "item_ref",
            schema = {
                success = { type = "boolean", doc = "True if entity was picked up" },
                item_name = { type = "string", doc = "Item returned to inventory" },
                count = { type = "number", doc = "Count returned (usually 1)" },
            },
        },
        func = function(self, entity_name, position)
            return self:pickup_entity(entity_name, position)
        end,
    },
    remove_ghost = {
        category = "placement",
        is_async = false,
        doc = [[Remove a ghost entity from the map.
The ghost entity must be within reach.]],
        paramspec = {
            _param_order = { "entity_name", "position" },
            entity_name = { type = "entity_name", required = true, doc = "Entity prototype name to remove" },
            position = { type = "position", default = nil, doc = "Entity position (nil = nearest)" },
        },
        returns = {
            type = "result",
            schema = {
                success = { type = "boolean", doc = "True if ghost was removed" },
            },
        },
        func = function(self, entity_name, position)
            return self:remove_ghost(entity_name, position)
        end,
    },

    -- ========================================================================
    -- SYNC: Movement
    -- ========================================================================
    teleport = {
        category = "movement",
        is_async = false,
        doc = [[Instantly teleport the agent to a position.
Use for testing/debugging. For normal gameplay, use walk_to instead.]],
        paramspec = {
            _param_order = { "position" },
            position = { type = "position", required = true, doc = "Target position" },
        },
        returns = {
            type = "result",
            schema = {
                success = { type = "boolean", doc = "True if teleport succeeded" },
                position = { type = "position", doc = "Final position" },
            },
        },
        func = function(self, position)
            return self:teleport(position)
        end,
    },

    -- ========================================================================
    -- QUERIES
    -- ========================================================================
    inspect = {
        category = "query",
        is_async = false,
        doc = [[Get current agent position.
Optionally attaches processed agent activity state (walking, mining, crafting).
This is the primary way to observe the agent's current position and activity status.]],
        paramspec = {
            _param_order = { "attach_state" },
            attach_state = { type = "boolean", default = false, doc = "Include processed activity state" },
        },
        returns = {
            type = "agent_state",
            schema = {
                agent_id = { type = "number", doc = "Agent ID" },
                tick = { type = "number", doc = "Current game tick" },
                position = { type = "position", doc = "Agent position" },
                state = { type = "table", doc = "Processed activity state: {walking, mining, crafting} with active flags (if requested)" },
            },
        },
        func = function(self, attach_state)
            return self:inspect(attach_state)
        end,
    },
    get_inventory_items = {
        category = "query",
        is_async = false,
        doc = [[Get agent's main inventory contents.
Returns a table mapping item names to counts.]],
        paramspec = {
            _param_order = {},
        },
        returns = {
            type = "table",
            schema = {
                item_name = { type = "number", doc = "Item count for each item name" },
            },
        },
        func = function(self)
            return self:get_inventory_items()
        end,
    },
    get_position = {
        category = "query",
        is_async = false,
        doc = [[Get current agent position.
Simple position query without additional state information.]],
        paramspec = {
            _param_order = {},
        },
        returns = {
            type = "position",
            schema = {
                x = { type = "number", doc = "X coordinate" },
                y = { type = "number", doc = "Y coordinate" },
            },
        },
        func = function(self)
            if not (self.character and self.character.valid) then
                error("Agent: Agent entity is invalid")
            end
            return { x = self.character.position.x, y = self.character.position.y }
        end,
    },
    get_placement_cues = {
        category = "query",
        is_async = false,
        doc = [[Get placement information for an entity type.
Returns valid positions and orientation hints for placing the entity.]],
        paramspec = {
            _param_order = { "entity_name" },
            entity_name = { type = "entity_name", required = true, doc = "Entity prototype name" },
        },
        returns = {
            type = "placement_info",
            schema = {
                entity_name = { type = "string", doc = "Entity name" },
                collision_box = { type = "table", doc = "Entity collision bounds" },
                tile_width = { type = "number", doc = "Width in tiles" },
                tile_height = { type = "number", doc = "Height in tiles" },
            },
        },
        func = function(self, entity_name)
            return self:get_placement_cues(entity_name)
        end,
    },
    get_chunks_in_view = {
        category = "query",
        is_async = false,
        doc = "Get list of map chunks currently visible/charted by the agent.",
        paramspec = { _param_order = {} },
        returns = {
            type = "table",
            schema = {
                chunks = { type = "table", doc = "Array of chunk coordinates [{x, y}, ...]" },
            },
        },
        func = function(self)
            return self:get_chunks_in_view()
        end,
    },
    get_recipes = {
        category = "query",
        is_async = false,
        doc = [[Get available recipes for the agent's force.
Optionally filter by crafting category.]],
        paramspec = {
            _param_order = { "category" },
            category = { type = "string", default = nil, doc = "Filter by category (nil = all)" },
        },
        returns = {
            type = "table",
            schema = {
                recipes = { type = "table", doc = "Array of recipe names" },
            },
        },
        func = function(self, category)
            return self:get_recipes(category)
        end,
    },
    get_technologies = {
        category = "query",
        is_async = false,
        doc = [[Get technologies for the agent's force.
Can filter to only show currently researchable technologies.]],
        paramspec = {
            _param_order = { "only_available" },
            only_available = { type = "boolean", default = false, doc = "Only show researchable techs" },
        },
        returns = {
            type = "table",
            schema = {
                technologies = { type = "table", doc = "Array of technology info objects" },
            },
        },
        func = function(self, only_available)
            return self:get_technologies(only_available)
        end,
    },

    -- ========================================================================
    -- RESEARCH
    -- ========================================================================
    enqueue_research = {
        category = "research",
        is_async = false,
        doc = [[Start researching a technology.
The agent's force must have labs with science packs available.]],
        paramspec = {
            _param_order = { "technology_name" },
            technology_name = { type = "technology_name", required = true, doc = "Technology to research" },
        },
        returns = {
            type = "result",
            schema = {
                success = { type = "boolean", doc = "True if research started" },
                technology = { type = "string", doc = "Technology being researched" },
            },
        },
        func = function(self, technology_name)
            return self:enqueue_research(technology_name)
        end,
    },
    cancel_current_research = {
        category = "research",
        is_async = false,
        doc = "Cancel the currently active research.",
        paramspec = { _param_order = {} },
        returns = {
            type = "result",
            schema = {
                success = { type = "boolean", doc = "True if research was cancelled" },
            },
        },
        func = function(self)
            return self:cancel_current_research()
        end,
    },

    -- ========================================================================
    -- REACHABILITY
    -- ========================================================================
    get_reachable = {
        category = "query",
        is_async = false,
        doc = [[Get full reachable snapshot with complete entity data.
Returns arrays of entity/resource data including volatile state (inventory, fuel, recipe, status).
Use this for the reachable_snapshot() context manager in Python.
Includes ghosts by default (set attach_ghosts=false to exclude).]],
        paramspec = {
            _param_order = { "attach_ghosts" },
            attach_ghosts = { type = "boolean", default = true, doc = "Whether to include ghosts in response (default: true)" },
        },
        returns = {
            type = "reachable_snapshot",
            schema = {
                entities = {
                    type = "array",
                    doc = "Array of entity data objects",
                    item_schema = {
                        name = { type = "string", doc = "Entity prototype name" },
                        type = { type = "string", doc = "Entity type" },
                        position = { type = "position", doc = "Entity position" },
                        position_key = { type = "string", doc = "Position key for lookups" },
                        status = { type = "string", doc = "Entity status (working, no-power, etc.)" },
                        recipe = { type = "string", doc = "Current recipe (machines only)" },
                        fuel_count = { type = "number", doc = "Fuel item count" },
                        input_contents = { type = "table", doc = "Input inventory: {item: count}" },
                        output_contents = { type = "table", doc = "Output inventory: {item: count}" },
                        contents = { type = "table", doc = "Chest contents: {item: count}" },
                    },
                },
                resources = {
                    type = "array",
                    doc = "Array of resource data objects",
                    item_schema = {
                        name = { type = "string", doc = "Resource prototype name" },
                        type = { type = "string", doc = "Resource type" },
                        position = { type = "position", doc = "Resource position" },
                        position_key = { type = "string", doc = "Position key for lookups" },
                        amount = { type = "number", doc = "Resource amount remaining" },
                        products = { type = "table", doc = "Mineable products" },
                    },
                },
                ghosts = {
                    type = "array",
                    doc = "Array of ghost entity data objects (only if attach_ghosts=true)",
                    item_schema = {
                        name = { type = "string", doc = "Always 'entity-ghost'" },
                        type = { type = "string", doc = "Always 'entity-ghost'" },
                        position = { type = "position", doc = "Ghost position" },
                        position_key = { type = "string", doc = "Position key for lookups" },
                        ghost_name = { type = "string", doc = "The entity this ghost represents" },
                        direction = { type = "number", doc = "Ghost direction (if applicable)" },
                    },
                },
                agent_position = { type = "position", doc = "Agent position at snapshot time" },
                tick = { type = "number", doc = "Game tick when snapshot was taken" },
            },
        },
        func = function(self, attach_ghosts)
            return self:get_reachable(attach_ghosts)
        end,
    },

    -- ========================================================================
    -- DEBUG
    -- ========================================================================
    inspect_state = {
        category = "development",
        is_async = false,
        doc = "Get raw agent state object (for debugging).",
        paramspec = { _param_order = {} },
        returns = {
            type = "raw",
            schema = {},
        },
        func = function(self)
            return self
        end,
    },
}

-- ============================================================================
-- SCHEMA EXPORT
-- ============================================================================

--- Export interface schema as JSON-serializable table
--- Used for:
---   1. Python binding generation
---   2. LLM documentation generation
---   3. Runtime validation
--- @return table Schema with methods, params, returns, and docs
function M.export_interface_schema()
    local schema = {
        version = "1.0.0",
        description = "FactoryVerse Agent Remote Interface",
        methods = {},
        types = {
            position = {
                description = "2D position on the map",
                schema = { x = "number", y = "number" },
            },
            inventory_type = {
                description = "Inventory slot type identifier",
                enum = { "input", "output", "fuel", "chest", "character" },
            },
            entity_ref = {
                description = "Reference to a placed entity (use for further operations)",
                schema = {
                    entity_name = "string",
                    position = "position",
                    entity_type = "string",
                },
            },
            item_ref = {
                description = "Reference to items in inventory",
                schema = {
                    item_name = "string",
                    count = "number",
                },
            },
        },
        categories = {
            movement = "Agent movement and pathfinding",
            mining = "Resource extraction",
            crafting = "Hand crafting recipes",
            entity = "Entity configuration (recipes, filters)",
            inventory = "Item transfer between agent and entities",
            placement = "Building and deconstructing entities",
            query = "Information retrieval (no side effects)",
            research = "Technology research",
            debug = "Debugging utilities",
        },
    }

    for method_name, meta in pairs(INTERFACE_METHODS) do
        -- Build param list (excluding internal fields)
        local params = {}
        for _, param_name in ipairs(meta.paramspec._param_order or {}) do
            local param_spec = meta.paramspec[param_name]
            if param_spec then
                params[param_name] = {
                    type = param_spec.type,
                    required = param_spec.required or false,
                    default = param_spec.default,
                    doc = param_spec.doc,
                }
                -- Include nested schema if present
                if param_spec.schema then
                    params[param_name].schema = param_spec.schema
                end
            end
        end

        schema.methods[method_name] = {
            category = meta.category,
            is_async = meta.is_async or false,
            doc = meta.doc,
            params = params,
            param_order = meta.paramspec._param_order,
            returns = meta.returns,
        }
    end

    return schema
end

--- Get list of async method names (for Python ASYNC_ACTIONS set)
--- @return table Array of async method names
function M.get_async_methods()
    local async_methods = {}
    for method_name, meta in pairs(INTERFACE_METHODS) do
        if meta.is_async then
            table.insert(async_methods, method_name)
        end
    end
    return async_methods
end

--- Get methods by category
--- @param category string Category name
--- @return table Methods in that category
function M.get_methods_by_category(category)
    local methods = {}
    for method_name, meta in pairs(INTERFACE_METHODS) do
        if meta.category == category then
            methods[method_name] = meta
        end
    end
    return methods
end

-- ============================================================================
-- PUBLIC API
-- ============================================================================

--- Get interface methods metadata (for introspection)
--- @return table Interface methods with paramspec
function M.get_interface_methods()
    return INTERFACE_METHODS
end

--- Register per-agent remote interface
--- Interface name: "agent_{agent_id}"
function M:register_remote_interface()
    local interface_name = "agent_" .. self.agent_id

    if remote.interfaces[interface_name] then
        remote.remove_interface(interface_name)
    end

    local interface = {}
    for method_name, meta in pairs(INTERFACE_METHODS) do
        interface[method_name] = function(...)
            return meta.func(self, ...)
        end
    end

    remote.add_interface(interface_name, interface)
end

--- Unregister per-agent remote interface
function M:unregister_remote_interface()
    local interface_name = "agent_" .. self.agent_id
    if remote.interfaces[interface_name] then
        remote.remove_interface(interface_name)
    end
end

return M
