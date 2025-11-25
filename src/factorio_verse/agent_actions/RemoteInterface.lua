local M = {}

-- ============================================================================
-- REMOTE INTERFACE REGISTRATION
-- ============================================================================

--- Interface method metadata: paramspec, output_schema, description, and func
--- Each entry defines a method available on the agent remote interface
local INTERFACE_METHODS = {
    -- Walking, Async
    walk_to = {
        paramspec = {
            _param_order = {"goal", "strict_goal", "options"},
            goal = { type = "position", required = true },
            strict_goal = { type = "boolean", default = false },
            options = { type = "table", default = {} },
        },
        output_schema = {
            type = "object",
            properties = {
                success = { type = "boolean" },
                queued = { type = "boolean" },
                action_id = { type = "string" },
                tick = { type = "number" },
                result = { type = "object" },
            },
        },
        description = "Navigate agent to target position using pathfinding. Returns immediately with action_id; completion is notified via UDP. If strict_goal is false, agent will adjust to nearest non-colliding position if goal is blocked.",
        func = function(self, goal, strict_goal, options)
            return self:walk_to(goal, strict_goal, options)
        end,
    },
    stop_walking = {
        paramspec = {
            _param_order = {},
        },
        output_schema = {
            type = "object",
            properties = {
                success = { type = "boolean" },
                position = { type = "object", properties = { x = { type = "number" }, y = { type = "number" } } },
                error = { type = "string" },
            },
        },
        description = "Stop the agent's current walking action. Returns success status and current position, or error if agent is not walking.",
        func = function(self)
            return self:stop_walking()
        end,
    },

    -- Mining, Async
    mine_resource = {
        paramspec = {
            _param_order = {"resource_name", "max_count"},
            resource_name = { type = "string", required = true },
            max_count = { type = "number", default = nil },
        },
        output_schema = {
            type = "object",
            properties = {
                success = { type = "boolean" },
                queued = { type = "boolean" },
                action_id = { type = "string" },
                tick = { type = "number" },
                resource_name = { type = "string" },
                max_count = { type = "number" },
                estimated_ticks = { type = "number" },
            },
        },
        description = "Start mining a resource (ore, tree, or rock) within reach. Returns immediately with action_id; completion is notified via UDP. For ores, max_count limits how many to mine. For trees/rocks, max_count is ignored.",
        func = function(self, resource_name, max_count)
            return self:mine_resource(resource_name, max_count)
        end,
    },
    stop_mining = {
        paramspec = {
            _param_order = {},
        },
        output_schema = {
            type = "object",
            properties = {
                success = { type = "boolean" },
                position = { type = "object", properties = { x = { type = "number" }, y = { type = "number" } } },
                error = { type = "string" },
            },
        },
        description = "Stop the agent's current mining action. Returns success status and current position, or error if agent is not mining.",
        func = function(self)
            return self:stop_mining()
        end,
    },

    -- Crafting, Async
    craft_enqueue = {
        paramspec = {
            _param_order = {"recipe_name", "count"},
            recipe_name = { type = "recipe", required = true },
            count = { type = "number", default = 1 },
        },
        output_schema = {
            type = "object",
            properties = {
                success = { type = "boolean" },
                queued = { type = "boolean" },
                action_id = { type = "string" },
                tick = { type = "number" },
                recipe = { type = "string" },
                count_queued = { type = "number" },
                estimated_ticks = { type = "number" },
            },
        },
        description = "Enqueue a crafting recipe for the agent to craft. Returns immediately with action_id; completion is notified via UDP. Count specifies how many times to craft the recipe.",
        func = function(self, recipe_name, count)
            return self:craft_enqueue(recipe_name, count)
        end,
    },
    craft_dequeue = {
        paramspec = {
            _param_order = {"recipe_name", "count"},
            recipe_name = { type = "recipe", required = true },
            count = { type = "number", default = nil },
        },
        output_schema = {
            type = "object",
            properties = {
                success = { type = "boolean" },
                cancelled = { type = "boolean" },
                action_id = { type = "string" },
                recipe = { type = "string" },
                count_cancelled = { type = "number" },
                remaining_queue_size = { type = "number" },
            },
        },
        description = "Dequeue/cancel a crafting recipe from the agent's crafting queue. If count is nil, cancels all instances of the recipe. Returns cancellation status and remaining queue size.",
        func = function(self, recipe_name, count)
            return self:craft_dequeue(recipe_name, count)
        end,
    },

    -- Entity operations
    set_entity_recipe = {
        paramspec = {
            _param_order = {"entity_name", "position", "recipe_name"},
            entity_name = { type = "entity_name", required = true },
            position = { type = "position", default = nil },
            recipe_name = { type = "recipe", default = nil },
        },
        output_schema = {
            type = "object",
            properties = {
                success = { type = "boolean" },
                entity_name = { type = "string" },
                position = { type = "object", properties = { x = { type = "number" }, y = { type = "number" } } },
                recipe_name = { type = "string" },
            },
        },
        description = "Set the recipe on a crafting entity (e.g., assembling machine). If position is nil, searches for entity near agent. If recipe_name is nil, clears the recipe. Entity must be within reach.",
        func = function(self, entity_name, position, recipe_name)
            return self:set_entity_recipe(entity_name, position, recipe_name)
        end,
    },
    set_entity_filter = {
        paramspec = {
            _param_order = {"entity_name", "position", "inventory_type", "filter_index", "filter_item"},
            entity_name = { type = "entity_name", required = true },
            position = { type = "position", default = nil },
            inventory_type = { type = "any", required = true },
            filter_index = { type = "number", default = nil },
            filter_item = { type = "string", default = nil },
        },
        output_schema = {
            type = "object",
            properties = {
                success = { type = "boolean" },
                entity_name = { type = "string" },
                position = { type = "object", properties = { x = { type = "number" }, y = { type = "number" } } },
                inventory_type = { type = "any" },
                filter_index = { type = "number" },
                filter_item = { type = "string" },
            },
        },
        description = "Set a filter on an entity's inventory slot. If position is nil, searches for entity near agent. If filter_index is nil, sets filter on all slots. If filter_item is nil, clears the filter. Entity must be within reach.",
        func = function(self, entity_name, position, inventory_type, filter_index, filter_item)
            return self:set_entity_filter(entity_name, position, inventory_type, filter_index, filter_item)
        end,
    },
    set_inventory_limit = {
        paramspec = {
            _param_order = {"entity_name", "position", "inventory_type", "limit"},
            entity_name = { type = "entity_name", required = true },
            position = { type = "position", default = nil },
            inventory_type = { type = "any", required = true },
            limit = { type = "number", default = nil },
        },
        output_schema = {
            type = "object",
            properties = {
                success = { type = "boolean" },
                entity_name = { type = "string" },
                position = { type = "object", properties = { x = { type = "number" }, y = { type = "number" } } },
                inventory_type = { type = "any" },
                limit = { type = "number" },
            },
        },
        description = "Set an inventory limit on an entity's inventory. If position is nil, searches for entity near agent. If limit is nil, clears the limit. Entity must be within reach.",
        func = function(self, entity_name, position, inventory_type, limit)
            return self:set_inventory_limit(entity_name, position, inventory_type, limit)
        end,
    },
    take_inventory_item = {
        paramspec = {
            _param_order = {"entity_name", "position", "inventory_type", "item_name", "count"},
            entity_name = { type = "entity_name", required = true },
            position = { type = "position", default = nil },
            inventory_type = { type = "any", required = true },
            item_name = { type = "string", required = true },
            count = { type = "number", default = nil },
        },
        output_schema = {
            type = "object",
            properties = {
                success = { type = "boolean" },
                entity_name = { type = "string" },
                position = { type = "object", properties = { x = { type = "number" }, y = { type = "number" } } },
                inventory_type = { type = "any" },
                item_name = { type = "string" },
                count = { type = "number" },
            },
        },
        description = "Transfer items from an entity's inventory to the agent's inventory. If position is nil, searches for entity near agent. If count is nil, transfers all available. Entity must be within reach.",
        func = function(self, entity_name, position, inventory_type, item_name, count)
            return self:get_inventory_item(entity_name, position, inventory_type, item_name, count)
        end,
    },
    put_inventory_item = {
        paramspec = {
            _param_order = {"entity_name", "position", "inventory_type", "item_name", "count"},
            entity_name = { type = "entity_name", required = true },
            position = { type = "position", default = nil },
            inventory_type = { type = "any", required = true },
            item_name = { type = "string", required = true },
            count = { type = "number", required = true },
        },
        output_schema = {
            type = "object",
            properties = {
                success = { type = "boolean" },
                entity_name = { type = "string" },
                position = { type = "object", properties = { x = { type = "number" }, y = { type = "number" } } },
                inventory_type = { type = "any" },
                item_name = { type = "string" },
                count = { type = "number" },
            },
        },
        description = "Transfer items from the agent's inventory to an entity's inventory. If position is nil, searches for entity near agent. Count is required. Entity must be within reach.",
        func = function(self, entity_name, position, inventory_type, item_name, count)
            return self:set_inventory_item(entity_name, position, inventory_type, item_name, count)
        end,
    },

    -- Placement
    place_entity = {
        paramspec = {
            _param_order = {"entity_name", "position", "options"},
            entity_name = { type = "entity_name", required = true },
            position = { type = "position", required = true },
            options = { type = "table", default = {} },
        },
        output_schema = {
            type = "object",
            properties = {
                success = { type = "boolean" },
                position = { type = "object", properties = { x = { type = "number" }, y = { type = "number" } } },
                entity_name = { type = "string" },
                entity_type = { type = "string" },
            },
        },
        description = "Place an entity at the specified position. Requires the entity item in agent's inventory. Options can include 'direction' (number 0-7) or 'orient_towards' (table with position or entity_name+position). Returns immediately with placement result.",
        func = function(self, entity_name, position, options)
            return self:place_entity(entity_name, position, options)
        end,
    },

    -- Teleport
    teleport = {
        paramspec = {
            _param_order = {"position"},
            position = { type = "position", required = true },
        },
        output_schema = {
            type = "boolean",
        },
        description = "Instantly teleport the agent to the specified position. Returns true on success, false if agent entity is invalid.",
        func = function(self, position)
            return self:teleport(position)
        end,
    },

    -- Queries
    inspect = {
        paramspec = {
            _param_order = {"attach_inventory", "attach_entities"},
            attach_inventory = { type = "boolean", default = false },
            attach_entities = { type = "boolean", default = false },
        },
        output_schema = {
            type = "object",
            properties = {
                agent_id = { type = "number" },
                tick = { type = "number" },
                position = { type = "object", properties = { x = { type = "number" }, y = { type = "number" } } },
                inventory = { type = "object" },
                reachable_resources = { type = "array", items = { type = "object" } },
                reachable_entities = { type = "array", items = { type = "object" } },
                error = { type = "string" },
            },
        },
        description = "Inspect the agent's current state. Returns position, optionally includes inventory contents and reachable entities/resources. attach_inventory includes agent inventory, attach_entities includes entities within reach.",
        func = function(self, attach_inventory, attach_entities)
            return self:inspect(attach_inventory, attach_entities)
        end,
    },
    get_placement_cues = {
        paramspec = {
            _param_order = {"entity_name"},
            entity_name = { type = "entity_name", required = true },
        },
        output_schema = {
            type = "array",
            items = {
                type = "object",
                properties = {
                    position = { type = "object", properties = { x = { type = "number" }, y = { type = "number" } } },
                    can_place = { type = "boolean" },
                    direction = { type = "string" },
                    resource_name = { type = "string" },
                },
            },
        },
        description = "Get valid placement positions for an entity type based on chunk resource tracking. Returns array of positions where the entity can be placed. Currently supports electric-mining-drill, pumpjack, and offshore-pump.",
        func = function(self, entity_name)
            return self:get_placement_cues(entity_name)
        end,
    },
    get_chunks_in_view = {
        paramspec = {
            _param_order = {},
        },
        output_schema = {
            type = "array",
            items = {
                type = "object",
                properties = {
                    x = { type = "number" },
                    y = { type = "number" },
                },
            },
        },
        description = "Get all chunk coordinates in a 5x5 area centered on the agent's current chunk. Returns array of {x, y} chunk coordinates.",
        func = function(self)
            return self:get_chunks_in_view()
        end,
    },
    get_recipes = {
        paramspec = {
            _param_order = {"category"},
            category = { type = "string", default = nil },
        },
        output_schema = {
            type = "array",
            items = {
                type = "object",
                properties = {
                    name = { type = "string" },
                    category = { type = "string" },
                    energy = { type = "number" },
                    ingredients = { type = "array" },
                },
            },
        },
        description = "Get all available recipes for the agent's force. If category is provided (e.g., 'crafting', 'smelting'), filters to that category. Returns array of recipe details including name, category, energy cost, and ingredients.",
        func = function(self, category)
            return self:get_recipes(category)
        end,
    },
    get_technologies = {
        paramspec = {
            _param_order = {"only_available"},
            only_available = { type = "boolean", default = false },
        },
        output_schema = {
            type = "array",
            items = {
                type = "object",
                properties = {
                    name = { type = "string" },
                    researched = { type = "boolean" },
                    enabled = { type = "boolean" },
                    prerequisites = { type = "object" },
                    successors = { type = "array" },
                    research_unit_ingredients = { type = "array" },
                    research_unit_count = { type = "number" },
                    research_unit_energy = { type = "number" },
                    saved_progress = { type = "number" },
                    effects = { type = "array" },
                    research_trigger = { type = "object" },
                },
            },
        },
        description = "Get all technologies available to the agent's force. If only_available is true, returns only technologies that can be researched right now (all prerequisites met). Returns array of technology details including prerequisites, research costs, and effects.",
        func = function(self, only_available)
            return self:get_technologies(only_available)
        end,
    },

    -- Research actions
    enqueue_research = {
        paramspec = {
            _param_order = {"technology_name"},
            technology_name = { type = "technology_name", required = true },
        },
        output_schema = {
            type = "object",
            properties = {
                success = { type = "boolean" },
                technology_name = { type = "string" },
                tick = { type = "number" },
                queue_position = { type = "number" },
                queue_length = { type = "number" },
            },
        },
        description = "Enqueue a technology for research. Adds the technology to the research queue. Returns success status, queue position, and queue length. Technology must be enabled and not already researched.",
        func = function(self, technology_name)
            return self:enqueue_research(technology_name)
        end,
    },
    cancel_current_research = {
        paramspec = {
            _param_order = {},
        },
        output_schema = {
            type = "object",
            properties = {
                success = { type = "boolean" },
                cancelled_technology = { type = "string" },
                tick = { type = "number" },
                error = { type = "string" },
            },
        },
        description = "Cancel the currently active research (first in queue). Returns success status and the name of the cancelled technology, or error if no research is active.",
        func = function(self)
            return self:cancel_current_research()
        end,
    },
}

--- Get interface methods metadata (for documentation API)
--- @return table Interface methods metadata
function M.get_interface_methods()
    return INTERFACE_METHODS
end

--- Register per-agent remote interface
--- Interface name: "agent_{agent_id}"
function M:register_remote_interface()
    local interface_name = "agent_" .. self.agent_id

    -- Remove existing interface if present
    if remote.interfaces[interface_name] then
        remote.remove_interface(interface_name)
    end

    -- Create interface dynamically from metadata
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